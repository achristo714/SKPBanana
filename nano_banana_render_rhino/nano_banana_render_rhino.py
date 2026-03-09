# Nano Banana Pro Render - Rhino Plugin
# AI-powered rendering for Rhinoceros 3D using Google Gemini API
# Run via: _RunPythonScript "nano_banana_render_rhino.py"

import os
import sys
import json
import base64
import threading
import tempfile
import time

import Rhino
import Rhino.UI
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System
import System.Drawing as Drawing
import System.IO as IO

import Eto.Forms as Forms
import Eto.Drawing as EtoDrawing

# -- Config ------------------------------------------------------------------

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(PLUGIN_DIR, 'temp')
CONFIG_FILE = os.path.join(PLUGIN_DIR, 'config.json')

DEFAULT_CONFIG = {
    'api_key': '',
    'model': 'gemini-3.1-pro-image-preview',
    'num_options': 2,
    'last_prompt': ''
}

MODELS = [
    ('gemini-3.1-pro-image-preview', 'Nano Banana Pro'),
    ('gemini-3.1-flash-image-preview', 'Nano Banana 2 (Fast)'),
    ('gemini-2.5-flash-image', 'Nano Banana (Legacy)'),
]


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        if not os.path.exists(os.path.dirname(CONFIG_FILE)):
            os.makedirs(os.path.dirname(CONFIG_FILE))
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# -- Viewport Capture --------------------------------------------------------

def capture_viewport():
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)

    view = Rhino.RhinoDoc.ActiveDoc.Views.ActiveView
    if view is None:
        raise Exception("No active viewport found")

    vp = view.ActiveViewport
    size = view.ClientRectangle.Size
    width = size.Width * 2
    height = size.Height * 2

    bitmap = view.CaptureToBitmap(System.Drawing.Size(width, height))
    if bitmap is None:
        raise Exception("Failed to capture viewport")

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(TEMP_DIR, "capture_{}.png".format(timestamp))
    bitmap.Save(filepath, Drawing.Imaging.ImageFormat.Png)
    bitmap.Dispose()
    return filepath


def image_to_base64(filepath):
    with open(filepath, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


# -- Gemini API ---------------------------------------------------------------

def call_gemini_api(api_key, model, prompt, image_base64, variation_index=0):
    """Call Gemini API for a single image generation request."""
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}".format(model, api_key)

        parts = [
            {'text': prompt},
            {
                'inline_data': {
                    'mime_type': 'image/png',
                    'data': image_base64
                }
            }
        ]

        payload = json.dumps({
            'contents': [{'parts': parts}],
            'generationConfig': {
                'responseModalities': ['TEXT', 'IMAGE'],
                'temperature': 1.0 + (variation_index * 0.1)
            }
        })

        # Use .NET WebRequest for HTTPS
        request = System.Net.WebRequest.Create(url)
        request.Method = "POST"
        request.ContentType = "application/json"
        request.Timeout = 120000

        payload_bytes = System.Text.Encoding.UTF8.GetBytes(payload)
        request.ContentLength = payload_bytes.Length

        stream = request.GetRequestStream()
        stream.Write(payload_bytes, 0, payload_bytes.Length)
        stream.Close()

        response = request.GetResponse()
        reader = IO.StreamReader(response.GetResponseStream())
        response_text = reader.ReadToEnd()
        reader.Close()
        response.Close()

        body = json.loads(response_text)

        if 'candidates' in body and len(body['candidates']) > 0:
            candidate = body['candidates'][0]
            image_data = None
            text_data = None

            for part in candidate.get('content', {}).get('parts', []):
                if 'inline_data' in part:
                    image_data = part['inline_data']['data']
                elif 'text' in part:
                    text_data = part['text']

            if image_data:
                output_path = os.path.join(TEMP_DIR, "render_{}_{}.png".format(
                    time.strftime('%Y%m%d_%H%M%S'), variation_index))
                with open(output_path, 'wb') as f:
                    f.write(base64.b64decode(image_data))
                return {'success': True, 'path': output_path, 'text': text_data}
            else:
                return {'success': False, 'error': text_data or 'No image in response'}
        else:
            error_msg = body.get('error', {}).get('message', 'Unknown API error')
            return {'success': False, 'error': error_msg}

    except System.Net.WebException as e:
        if e.Response:
            reader = IO.StreamReader(e.Response.GetResponseStream())
            error_body = reader.ReadToEnd()
            reader.Close()
            try:
                err = json.loads(error_body)
                return {'success': False, 'error': err.get('error', {}).get('message', str(e))}
            except Exception:
                return {'success': False, 'error': error_body}
        return {'success': False, 'error': str(e)}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def enhance_prompt(api_key, base_prompt):
    """Use Gemini Flash to enhance a rendering prompt."""
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={}".format(api_key)

        system_prompt = (
            "You are an expert architectural visualization and rendering prompt engineer. "
            "Given a short user prompt about how they want a 3D model rendered, "
            "expand it into a detailed, high-quality rendering prompt. Include specific details about: "
            "lighting, materials and textures, atmosphere and mood, camera perspective, "
            "environmental context (landscaping, sky, weather), and rendering style. "
            "Keep the enhanced prompt concise but rich. Output ONLY the enhanced prompt."
        )

        payload = json.dumps({
            'contents': [{
                'parts': [{'text': "{}\n\nUser prompt: {}".format(system_prompt, base_prompt)}]
            }],
            'generationConfig': {
                'temperature': 0.7,
                'maxOutputTokens': 300
            }
        })

        request = System.Net.WebRequest.Create(url)
        request.Method = "POST"
        request.ContentType = "application/json"
        request.Timeout = 30000

        payload_bytes = System.Text.Encoding.UTF8.GetBytes(payload)
        request.ContentLength = payload_bytes.Length

        stream = request.GetRequestStream()
        stream.Write(payload_bytes, 0, payload_bytes.Length)
        stream.Close()

        response = request.GetResponse()
        reader = IO.StreamReader(response.GetResponseStream())
        response_text = reader.ReadToEnd()
        reader.Close()
        response.Close()

        body = json.loads(response_text)
        if 'candidates' in body:
            text = body.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            return text.strip() if text else base_prompt
        return base_prompt
    except Exception:
        return base_prompt


# -- Results Dialog -----------------------------------------------------------

class ResultsDialog(Forms.Dialog):
    def __init__(self, original_b64, results):
        self.Title = "Render Results - Nano Banana Pro"
        self.ClientSize = EtoDrawing.Size(900, 650)
        self.Resizable = True
        self.original_b64 = original_b64
        self.results = results
        self._build_ui()

    def _build_ui(self):
        layout = Forms.DynamicLayout()
        layout.DefaultSpacing = EtoDrawing.Size(8, 8)
        layout.Padding = EtoDrawing.Padding(16)

        # Title
        title = Forms.Label()
        title.Text = "Render Results"
        title.Font = EtoDrawing.Font(EtoDrawing.FontFamilies.SansFamilyName, 16, EtoDrawing.FontStyle.Bold)
        layout.AddRow(title)
        layout.AddRow(None)

        # Tabs for variations
        self.tab_control = Forms.TabControl()

        for i, result in enumerate(self.results):
            page = Forms.TabPage()
            page.Text = "Variation {}".format(i + 1) if result['success'] else "Variation {} (Failed)".format(i + 1)

            page_layout = Forms.DynamicLayout()
            page_layout.DefaultSpacing = EtoDrawing.Size(8, 8)
            page_layout.Padding = EtoDrawing.Padding(12)

            if result['success']:
                # Show rendered image
                render_b64 = image_to_base64(result['path'])
                img_bytes = System.Convert.FromBase64String(render_b64)
                stream = IO.MemoryStream(img_bytes)
                eto_image = EtoDrawing.Bitmap(stream)

                image_view = Forms.ImageView()
                image_view.Image = eto_image

                page_layout.AddRow(image_view)

                if result.get('text'):
                    note = Forms.Label()
                    note.Text = "AI Notes: {}".format(result['text'])
                    note.Wrap = Forms.WrapMode.Word
                    page_layout.AddRow(note)

                # Save button
                save_btn = Forms.Button()
                save_btn.Text = "Save Image"
                save_btn.Tag = result['path']
                save_btn.Click += self._on_save
                page_layout.AddRow(save_btn)
            else:
                error_label = Forms.Label()
                error_label.Text = "Rendering Failed: {}".format(result.get('error', 'Unknown error'))
                error_label.TextColor = EtoDrawing.Color.FromArgb(255, 71, 87)
                error_label.Wrap = Forms.WrapMode.Word
                page_layout.AddRow(error_label)

            page_layout.AddRow(None)
            page.Content = page_layout
            self.tab_control.Pages.Add(page)

        layout.AddRow(self.tab_control)
        self.Content = layout

    def _on_save(self, sender, e):
        source_path = sender.Tag
        dialog = Forms.SaveFileDialog()
        dialog.Title = "Save Rendered Image"
        dialog.Filters.Add(Forms.FileFilter("PNG Images", ".png"))

        if dialog.ShowDialog(self) == Forms.DialogResult.Ok:
            dest = dialog.FileName
            if not dest.endswith('.png'):
                dest += '.png'
            System.IO.File.Copy(source_path, dest, True)
            Forms.MessageBox.Show(self, "Image saved to:\n{}".format(dest), "Saved")


# -- Main Prompt Dialog -------------------------------------------------------

class PromptDialog(Forms.Dialog):
    def __init__(self):
        self.config = load_config()
        self.Title = "Nano Banana Pro Render"
        self.ClientSize = EtoDrawing.Size(480, 520)
        self.Resizable = True
        self._build_ui()

    def _build_ui(self):
        layout = Forms.DynamicLayout()
        layout.DefaultSpacing = EtoDrawing.Size(8, 8)
        layout.Padding = EtoDrawing.Padding(20)

        # Title
        title = Forms.Label()
        title.Text = "Nano Banana Pro Render"
        title.Font = EtoDrawing.Font(EtoDrawing.FontFamilies.SansFamilyName, 16, EtoDrawing.FontStyle.Bold)
        layout.AddRow(title)

        subtitle = Forms.Label()
        subtitle.Text = "AI-powered rendering for Rhino"
        layout.AddRow(subtitle)
        layout.AddRow(None)

        # API Key section
        section_label = Forms.Label()
        section_label.Text = "API CONFIGURATION"
        section_label.Font = EtoDrawing.Font(EtoDrawing.FontFamilies.SansFamilyName, 10, EtoDrawing.FontStyle.Bold)
        layout.AddRow(section_label)

        layout.AddRow(Forms.Label(Text="Google AI API Key"))
        key_row = Forms.DynamicLayout()
        key_row.DefaultSpacing = EtoDrawing.Size(8, 0)

        self.api_key_input = Forms.PasswordBox()
        self.api_key_input.Text = self.config.get('api_key', '')

        save_key_btn = Forms.Button(Text="Save")
        save_key_btn.Click += self._on_save_key

        key_row.AddRow(self.api_key_input, save_key_btn)
        layout.AddRow(key_row)
        layout.AddRow(None)

        # Prompt section
        prompt_section = Forms.Label()
        prompt_section.Text = "RENDER PROMPT"
        prompt_section.Font = EtoDrawing.Font(EtoDrawing.FontFamilies.SansFamilyName, 10, EtoDrawing.FontStyle.Bold)
        layout.AddRow(prompt_section)

        prompt_header = Forms.DynamicLayout()
        prompt_header.DefaultSpacing = EtoDrawing.Size(8, 0)
        prompt_label = Forms.Label(Text="Describe your desired render")
        enhance_btn = Forms.Button(Text="Enhance Prompt")
        enhance_btn.Click += self._on_enhance
        prompt_header.AddRow(prompt_label, None, enhance_btn)
        layout.AddRow(prompt_header)

        self.prompt_input = Forms.TextArea()
        self.prompt_input.Height = 100
        self.prompt_input.Text = self.config.get('last_prompt', '')
        layout.AddRow(self.prompt_input)

        # Options row
        options_row = Forms.DynamicLayout()
        options_row.DefaultSpacing = EtoDrawing.Size(16, 0)

        # Variations
        var_layout = Forms.DynamicLayout()
        var_layout.AddRow(Forms.Label(Text="Variations"))
        self.num_options = Forms.DropDown()
        for n in range(1, 5):
            self.num_options.Items.Add("{} option{}".format(n, 's' if n > 1 else ''))
        self.num_options.SelectedIndex = self.config.get('num_options', 2) - 1
        var_layout.AddRow(self.num_options)

        # Model
        model_layout = Forms.DynamicLayout()
        model_layout.AddRow(Forms.Label(Text="Model"))
        self.model_dropdown = Forms.DropDown()
        current_model = self.config.get('model', MODELS[0][0])
        selected_idx = 0
        for idx, (model_id, model_name) in enumerate(MODELS):
            self.model_dropdown.Items.Add(model_name)
            if model_id == current_model:
                selected_idx = idx
        self.model_dropdown.SelectedIndex = selected_idx
        model_layout.AddRow(self.model_dropdown)

        options_row.AddRow(var_layout, model_layout)
        layout.AddRow(options_row)
        layout.AddRow(None)

        # Render button
        render_btn = Forms.Button(Text="Capture View & Render")
        render_btn.Click += self._on_render
        layout.AddRow(render_btn)

        # Status label
        self.status_label = Forms.Label()
        self.status_label.Text = ""
        layout.AddRow(self.status_label)

        layout.AddRow(None)
        self.Content = layout

    def _set_status(self, msg, is_error=False):
        self.status_label.Text = msg
        if is_error:
            self.status_label.TextColor = EtoDrawing.Color.FromArgb(255, 71, 87)
        else:
            self.status_label.TextColor = EtoDrawing.Color.FromArgb(46, 213, 115)

    def _on_save_key(self, sender, e):
        key = self.api_key_input.Text.strip() if self.api_key_input.Text else ''
        if not key:
            self._set_status("Please enter an API key", True)
            return
        self.config['api_key'] = key
        save_config(self.config)
        self._set_status("API key saved")

    def _on_enhance(self, sender, e):
        prompt = self.prompt_input.Text.strip()
        if not prompt:
            self._set_status("Type a prompt first", True)
            return
        api_key = self.config.get('api_key', '')
        if not api_key:
            self._set_status("Set your API key first", True)
            return

        self._set_status("Enhancing prompt...")
        enhanced = enhance_prompt(api_key, prompt)
        self.prompt_input.Text = enhanced
        self._set_status("Prompt enhanced!")

    def _on_render(self, sender, e):
        prompt = self.prompt_input.Text.strip()
        if not prompt:
            self._set_status("Enter a render prompt", True)
            return

        api_key = self.config.get('api_key', '')
        if not api_key:
            self._set_status("Set your API key first", True)
            return

        num = self.num_options.SelectedIndex + 1
        model_id = MODELS[self.model_dropdown.SelectedIndex][0]

        self.config['num_options'] = num
        self.config['last_prompt'] = prompt
        self.config['model'] = model_id
        save_config(self.config)

        self._set_status("Capturing viewport...")

        try:
            capture_path = capture_viewport()
            image_b64 = image_to_base64(capture_path)
        except Exception as ex:
            self._set_status("Capture failed: {}".format(str(ex)), True)
            return

        self._set_status("Rendering... this may take 15-60 seconds per variation")

        results = []
        for i in range(num):
            self._set_status("Rendering variation {} of {}...".format(i + 1, num))
            result = call_gemini_api(api_key, model_id, prompt, image_b64, i)
            results.append(result)

        self._set_status("Done!")

        # Show results
        results_dlg = ResultsDialog(image_b64, results)
        results_dlg.ShowModal(self)


# -- Entry Point --------------------------------------------------------------

def main():
    dialog = PromptDialog()
    dialog.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)


main()
