require 'sketchup.rb'
require 'json'
require 'net/http'
require 'uri'
require 'base64'
require 'fileutils'

module NanoBananaRender
  PLUGIN_DIR = File.join(File.dirname(File.dirname(__FILE__)), 'nano_banana_render')
  TEMP_DIR = File.join(PLUGIN_DIR, 'temp')
  CONFIG_FILE = File.join(PLUGIN_DIR, 'config.json')

  DEFAULT_CONFIG = {
    'api_key' => '',
    'model' => 'gemini-2.5-flash-image',
    'num_options' => 2,
    'last_prompt' => ''
  }.freeze

  @config = nil
  @dialog = nil
  @results_dialog = nil

  class << self
    def config
      @config ||= load_config
    end

    def load_config
      if File.exist?(CONFIG_FILE)
        JSON.parse(File.read(CONFIG_FILE))
      else
        DEFAULT_CONFIG.dup
      end
    rescue StandardError
      DEFAULT_CONFIG.dup
    end

    def save_config
      FileUtils.mkdir_p(File.dirname(CONFIG_FILE))
      File.write(CONFIG_FILE, JSON.pretty_generate(@config))
    end

    def capture_view
      FileUtils.mkdir_p(TEMP_DIR)
      view = Sketchup.active_model.active_view
      timestamp = Time.now.strftime('%Y%m%d_%H%M%S')
      filepath = File.join(TEMP_DIR, "capture_#{timestamp}.png")

      keys = {
        filename: filepath,
        width: view.vpwidth * 2,
        height: view.vpheight * 2,
        antialias: true,
        transparent: false
      }
      view.write_image(keys)
      filepath
    end

    def image_to_base64(filepath)
      Base64.strict_encode64(File.binread(filepath))
    end

    def call_nano_banana_api(prompt, image_base64, num_options = 1)
      api_key = config['api_key']
      model = config['model']
      uri = URI("https://generativelanguage.googleapis.com/v1beta/models/#{model}:generateContent")
      uri.query = URI.encode_www_form('key' => api_key)

      parts = []
      parts << { 'text' => prompt }
      parts << {
        'inline_data' => {
          'mime_type' => 'image/png',
          'data' => image_base64
        }
      }

      results = []
      threads = []

      num_options.times do |i|
        threads << Thread.new do
          begin
            http = Net::HTTP.new(uri.host, uri.port)
            http.use_ssl = true
            http.read_timeout = 120
            http.open_timeout = 30

            request = Net::HTTP::Post.new(uri)
            request['Content-Type'] = 'application/json'
            request.body = JSON.generate({
              'contents' => [{ 'parts' => parts }],
              'generationConfig' => {
                'responseModalities' => ['TEXT', 'IMAGE'],
                'temperature' => 1.0 + (i * 0.1)
              }
            })

            response = http.request(request)
            body = JSON.parse(response.body)

            if response.code == '200' && body['candidates']
              candidate = body['candidates'][0]
              image_data = nil
              text_data = nil

              candidate['content']['parts']&.each do |part|
                if part['inline_data']
                  image_data = part['inline_data']['data']
                elsif part['text']
                  text_data = part['text']
                end
              end

              if image_data
                output_path = File.join(TEMP_DIR, "render_#{Time.now.strftime('%Y%m%d_%H%M%S')}_#{i}.png")
                File.binwrite(output_path, Base64.decode64(image_data))
                results[i] = { 'success' => true, 'path' => output_path, 'text' => text_data }
              else
                results[i] = { 'success' => false, 'error' => text_data || 'No image in response' }
              end
            else
              error_msg = body.dig('error', 'message') || "API error (#{response.code})"
              results[i] = { 'success' => false, 'error' => error_msg }
            end
          rescue StandardError => e
            results[i] = { 'success' => false, 'error' => e.message }
          end
        end
      end

      threads.each(&:join)
      results
    end

    def enhance_prompt(base_prompt)
      api_key = config['api_key']
      uri = URI("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent")
      uri.query = URI.encode_www_form('key' => api_key)

      system_prompt = <<~PROMPT
        You are an expert architectural visualization and rendering prompt engineer.
        You are an expert architectural visualization prompt engineer.
        The user will give you a short description of how they want their 3D model rendered.
        Your job is to rewrite it into a single, detailed rendering prompt that a generative AI image model can use.
        The prompt should read as one cohesive paragraph — NOT a list of bullet points.
        Include vivid, specific details about:
        lighting (time of day, light direction, shadows, warmth),
        materials (concrete, wood, glass — describe finishes and reflections),
        atmosphere (weather, sky, haze, mood),
        surroundings (landscaping, street context, furniture, people),
        and rendering style (photorealistic, V-Ray quality, architectural photography).
        The output must be ONLY the enhanced prompt text — no labels, no headings, no explanation.
        Write it as a complete, natural sentence or paragraph that flows well.
        Aim for 2-4 sentences, roughly 80-150 words.
      PROMPT

      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = true
      http.read_timeout = 30

      request = Net::HTTP::Post.new(uri)
      request['Content-Type'] = 'application/json'
      request.body = JSON.generate({
        'contents' => [{
          'parts' => [
            { 'text' => "#{system_prompt}\n\nUser prompt: #{base_prompt}" }
          ]
        }],
        'generationConfig' => {
          'temperature' => 0.8,
          'maxOutputTokens' => 1024
        }
      })

      response = http.request(request)
      body = JSON.parse(response.body)

      if response.code == '200' && body['candidates']
        body.dig('candidates', 0, 'content', 'parts', 0, 'text')&.strip || base_prompt
      else
        base_prompt
      end
    rescue StandardError
      base_prompt
    end

    def show_prompt_dialog
      if @dialog && @dialog.visible?
        @dialog.bring_to_front
        return
      end

      html_path = File.join(PLUGIN_DIR, 'html', 'prompt_dialog.html')

      @dialog = UI::HtmlDialog.new({
        dialog_title: 'Nano Banana Pro Render',
        width: 520,
        height: 620,
        resizable: true,
        style: UI::HtmlDialog::STYLE_DIALOG
      })

      @dialog.add_action_callback('get_config') do |_ctx|
        @dialog.execute_script("setConfig(#{JSON.generate(config)})")
      end

      @dialog.add_action_callback('save_api_key') do |_ctx, key|
        config['api_key'] = key.to_s.strip
        save_config
        @dialog.execute_script("showStatus('API key saved', 'success')")
      end

      @dialog.add_action_callback('enhance_prompt') do |_ctx, prompt|
        if config['api_key'].empty?
          @dialog.execute_script("showStatus('Set your API key first', 'error')")
          next
        end

        Thread.new do
          enhanced = enhance_prompt(prompt)
          UI.start_timer(0, false) do
            @dialog.execute_script("setEnhancedPrompt(#{JSON.generate(enhanced)})")
          end
        end
      end

      @dialog.add_action_callback('render') do |_ctx, prompt, num_options, model_name|
        if config['api_key'].empty?
          @dialog.execute_script("showStatus('Set your API key first', 'error')")
          next
        end

        num = num_options.to_i
        num = 1 if num < 1
        num = 4 if num > 4
        config['num_options'] = num
        config['last_prompt'] = prompt
        config['model'] = model_name.to_s if model_name && !model_name.to_s.empty?
        save_config

        @dialog.execute_script("setLoading(true)")

        Thread.new do
          begin
            capture_path = capture_view
            image_b64 = image_to_base64(capture_path)
            results = call_nano_banana_api(prompt, image_b64, num)

            original_b64 = image_b64
            render_data = results.map do |r|
              if r['success']
                { 'success' => true, 'image' => image_to_base64(r['path']), 'text' => r['text'] }
              else
                { 'success' => false, 'error' => r['error'] }
              end
            end

            payload = JSON.generate({
              'original' => original_b64,
              'renders' => render_data
            })

            UI.start_timer(0, false) do
              @dialog.execute_script("setLoading(false)")
              show_results_dialog(payload)
            end
          rescue StandardError => e
            UI.start_timer(0, false) do
              @dialog.execute_script("setLoading(false)")
              @dialog.execute_script("showStatus(#{JSON.generate(e.message)}, 'error')")
            end
          end
        end
      end

      @dialog.set_file(html_path)
      @dialog.show
    end

    def show_results_dialog(payload_json)
      if @results_dialog && @results_dialog.visible?
        @results_dialog.close
      end

      html_path = File.join(PLUGIN_DIR, 'html', 'results_dialog.html')

      @results_dialog = UI::HtmlDialog.new({
        dialog_title: 'Render Results - Nano Banana Pro',
        width: 1000,
        height: 750,
        resizable: true,
        style: UI::HtmlDialog::STYLE_DIALOG
      })

      @results_dialog.add_action_callback('get_results') do |_ctx|
        @results_dialog.execute_script("loadResults(#{payload_json})")
      end

      @results_dialog.add_action_callback('save_image') do |_ctx, base64_data|
        path = UI.savepanel('Save Rendered Image', '', 'render.png')
        if path
          path += '.png' unless path.end_with?('.png')
          File.binwrite(path, Base64.decode64(base64_data))
          UI.messagebox("Image saved to:\n#{path}")
        end
      end

      @results_dialog.set_file(html_path)
      @results_dialog.show
    end

    def setup_menu
      menu = UI.menu('Plugins')
      submenu = menu.add_submenu('Nano Banana Pro Render')

      submenu.add_item('Render Current View') { show_prompt_dialog }
      submenu.add_item('Settings') { show_prompt_dialog }

      toolbar = UI::Toolbar.new('Nano Banana Pro')
      cmd = UI::Command.new('Render') { show_prompt_dialog }
      cmd.tooltip = 'Render with Nano Banana Pro'
      cmd.status_bar_text = 'Capture view and render with AI'

      icon_path = File.join(PLUGIN_DIR, 'icons', 'render')
      cmd.small_icon = "#{icon_path}_24.png" if File.exist?("#{icon_path}_24.png")
      cmd.large_icon = "#{icon_path}_32.png" if File.exist?("#{icon_path}_32.png")

      toolbar.add_item(cmd)
      toolbar.show
    end
  end

  setup_menu

end
