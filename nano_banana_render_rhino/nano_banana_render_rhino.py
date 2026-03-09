# -*- coding: utf-8 -*-
# Nano Banana Pro Render - Rhino Plugin
# AI-powered rendering for Rhinoceros 3D using Google Gemini API
# Run via: _RunPythonScript "nano_banana_render_rhino.py"

import os
import json
import base64
import time
import threading
import shutil

import Rhino
import Rhino.UI
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
    'model': 'gemini-2.5-flash-image',
    'num_options': 2,
    'last_prompt': ''
}


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
        d = os.path.dirname(CONFIG_FILE)
        if not os.path.exists(d):
            os.makedirs(d)
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

    bitmap = view.CaptureToBitmap()
    if bitmap is None:
        raise Exception("Failed to capture viewport")

    ts = time.strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(TEMP_DIR, "capture_{}.png".format(ts))
    bitmap.Save(filepath, Drawing.Imaging.ImageFormat.Png)
    bitmap.Dispose()
    return filepath


def image_to_base64(filepath):
    with open(filepath, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


# -- Gemini API ---------------------------------------------------------------

def call_gemini_api(api_key, model, prompt, image_base64, variation_index=0):
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}".format(model, api_key)

        parts = [
            {'text': prompt},
            {'inline_data': {'mime_type': 'image/png', 'data': image_base64}}
        ]

        payload = json.dumps({
            'contents': [{'parts': parts}],
            'generationConfig': {
                'responseModalities': ['TEXT', 'IMAGE'],
                'temperature': 1.0 + (variation_index * 0.1)
            }
        })

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

        # Free the upload payload from memory immediately
        del payload
        del payload_bytes

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
                    f.flush()
                    os.fsync(f.fileno())
                # Free decoded image from memory
                del image_data
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


def enhance_prompt_api(api_key, base_prompt):
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={}".format(api_key)

        system_prompt = (
            "You are an expert architectural visualization prompt engineer. "
            "The user will give you a short description of how they want their 3D model rendered. "
            "Your job is to rewrite it into a single, detailed rendering prompt that a generative AI image model can use. "
            "The prompt should read as one cohesive paragraph — NOT a list of bullet points. "
            "Include vivid, specific details about: "
            "lighting (time of day, light direction, shadows, warmth), "
            "materials (concrete, wood, glass — describe finishes and reflections), "
            "atmosphere (weather, sky, haze, mood), "
            "surroundings (landscaping, street context, furniture, people), "
            "and rendering style (photorealistic, V-Ray quality, architectural photography). "
            "The output must be ONLY the enhanced prompt text — no labels, no headings, no explanation. "
            "Write it as a complete, natural sentence or paragraph that flows well. "
            "Aim for 2-4 sentences, roughly 80-150 words."
        )

        payload = json.dumps({
            'contents': [{'parts': [{'text': "{}\n\nUser prompt: {}".format(system_prompt, base_prompt)}]}],
            'generationConfig': {'temperature': 0.8, 'maxOutputTokens': 1024}
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


# -- HTML Templates -----------------------------------------------------------

PROMPT_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  :root {
    --bg-primary: #1a1a2e;
    --bg-card: #1e2a47;
    --bg-input: #0f1629;
    --border: #2a3a5c;
    --border-focus: #e94560;
    --text-primary: #e8e8e8;
    --text-secondary: #a0a8c0;
    --text-muted: #6b7394;
    --accent: #e94560;
    --accent-hover: #ff6b81;
    --accent-glow: rgba(233, 69, 96, 0.3);
    --success: #2ed573;
    --error: #ff4757;
    --gradient-start: #e94560;
    --gradient-end: #0abde3;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    padding: 20px;
    overflow-y: auto;
  }
  .header { text-align: center; margin-bottom: 24px; }
  .header h1 {
    font-size: 20px; font-weight: 700;
    background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
  }
  .header p { font-size: 12px; color: var(--text-muted); }
  .section {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 16px;
  }
  .section-title {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 1.2px; color: var(--text-muted); margin-bottom: 10px;
  }
  label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; font-weight: 500; }
  input[type="text"], input[type="password"], textarea, select {
    width: 100%; background: var(--bg-input); border: 1px solid var(--border);
    border-radius: 8px; color: var(--text-primary); font-size: 13px;
    padding: 10px 12px; outline: none; transition: border-color 0.2s, box-shadow 0.2s;
    font-family: inherit;
  }
  input:focus, textarea:focus, select:focus {
    border-color: var(--border-focus); box-shadow: 0 0 0 3px var(--accent-glow);
  }
  textarea { resize: vertical; min-height: 80px; line-height: 1.5; }
  select {
    cursor: pointer; appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a0a8c0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 12px center; padding-right: 32px;
  }
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    padding: 10px 18px; border: none; border-radius: 8px; font-size: 13px;
    font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: inherit;
  }
  .btn-primary {
    background: linear-gradient(135deg, var(--gradient-start), var(--accent-hover));
    color: white; width: 100%;
  }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 15px var(--accent-glow); }
  .btn-primary:active { transform: translateY(0); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }
  .btn-secondary { background: var(--bg-input); border: 1px solid var(--border); color: var(--text-secondary); }
  .btn-secondary:hover { border-color: var(--accent); color: var(--text-primary); }
  .btn-enhance {
    background: linear-gradient(135deg, #0abde3, #48dbfb); color: #1a1a2e;
    font-size: 11px; padding: 6px 12px; border-radius: 6px;
  }
  .btn-enhance:hover { transform: translateY(-1px); box-shadow: 0 3px 10px rgba(10, 189, 227, 0.3); }
  .prompt-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .options-row { display: flex; gap: 12px; margin-top: 12px; }
  .options-row > div { flex: 1; }
  .status {
    text-align: center; font-size: 12px; padding: 8px; border-radius: 6px;
    margin-top: 12px; display: none;
  }
  .status.success { display: block; background: rgba(46,213,115,0.1); border: 1px solid rgba(46,213,115,0.3); color: var(--success); }
  .status.error { display: block; background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.3); color: var(--error); }

  /* Loading overlay with progress bar */
  .loading-overlay {
    display: none; position: fixed; inset: 0; background: rgba(26,26,46,0.95);
    z-index: 100; flex-direction: column; align-items: center; justify-content: center; gap: 16px;
  }
  .loading-overlay.active { display: flex; }
  .spinner { width: 48px; height: 48px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-text { color: var(--text-secondary); font-size: 14px; font-weight: 500; }
  .loading-sub { color: var(--text-muted); font-size: 12px; margin-top: 4px; }

  .progress-container {
    width: 280px; margin-top: 8px;
  }
  .progress-bar-bg {
    width: 100%; height: 6px; background: var(--bg-input); border-radius: 3px; overflow: hidden;
  }
  .progress-bar-fill {
    height: 100%; width: 0%; border-radius: 3px;
    background: linear-gradient(90deg, var(--gradient-start), var(--gradient-end));
    transition: width 0.4s ease;
  }
  .progress-pct {
    text-align: center; font-size: 22px; font-weight: 700; color: var(--accent);
    margin-bottom: 4px; font-variant-numeric: tabular-nums;
  }

  .api-key-row { display: flex; gap: 8px; }
  .api-key-row input { flex: 1; }
  .key-toggle { background: none; border: 1px solid var(--border); border-radius: 8px; color: var(--text-muted); cursor: pointer; padding: 0 10px; font-size: 14px; transition: color 0.2s; }
  .key-toggle:hover { color: var(--text-primary); }
  .char-count { text-align: right; font-size: 11px; color: var(--text-muted); margin-top: 4px; }
  .hint { text-align: center; font-size: 11px; color: var(--text-muted); margin-top: 10px; font-style: italic; }
</style>
</head>
<body>
<div class="header">
  <h1>Nano Banana Pro Render</h1>
  <p>AI-powered rendering for Rhino</p>
</div>
<div class="section">
  <div class="section-title">API Configuration</div>
  <label>Google AI API Key</label>
  <div class="api-key-row">
    <input type="password" id="apiKey" placeholder="Enter your Gemini API key...">
    <button class="key-toggle" onclick="toggleKey()" title="Show/Hide">&#x1f441;</button>
    <button class="btn btn-secondary" onclick="doAction('save_key',{key:document.getElementById('apiKey').value.trim()})">Save</button>
  </div>
</div>
<div class="section">
  <div class="section-title">Render Prompt</div>
  <div class="prompt-header">
    <label style="margin:0">Describe your desired render</label>
    <button class="btn btn-enhance" onclick="doAction('enhance',{prompt:document.getElementById('prompt').value.trim()})">Enhance Prompt</button>
  </div>
  <textarea id="prompt" placeholder="e.g. Photorealistic exterior render, golden hour lighting, lush landscaping..."></textarea>
  <div class="char-count"><span id="charCount">0</span> chars</div>
  <div class="options-row">
    <div>
      <label>Variations</label>
      <select id="numOptions">
        <option value="1">1 option</option>
        <option value="2" selected>2 options</option>
        <option value="3">3 options</option>
        <option value="4">4 options</option>
      </select>
    </div>
    <div>
      <label>Model</label>
      <select id="model">
        <option value="gemini-2.5-flash-image">Nano Banana (Stable)</option>
        <option value="gemini-3.1-flash-image-preview">Nano Banana 2 (Latest)</option>
      </select>
    </div>
  </div>
</div>
<button class="btn btn-primary" id="renderBtn" onclick="startRender()">Capture View &amp; Render</button>
<div class="hint">Position your camera in Rhino, then click Capture View & Render</div>
<div class="status" id="status"></div>

<div class="loading-overlay" id="loadingOverlay">
  <div class="spinner"></div>
  <div class="progress-pct" id="progressPct">0%</div>
  <div class="progress-container">
    <div class="progress-bar-bg">
      <div class="progress-bar-fill" id="progressFill"></div>
    </div>
  </div>
  <div class="loading-text" id="loadingText">Capturing viewport...</div>
  <div class="loading-sub" id="loadingSub">This may take 15-60 seconds per variation</div>
</div>

<script>
  var promptEl = document.getElementById('prompt');
  var charCountEl = document.getElementById('charCount');
  promptEl.addEventListener('input', function() { charCountEl.textContent = promptEl.value.length; });

  function toggleKey() {
    var input = document.getElementById('apiKey');
    input.type = input.type === 'password' ? 'text' : 'password';
  }

  function doAction(action, data) {
    window.location.href = 'nano://' + action + '/' + encodeURIComponent(JSON.stringify(data || {}));
  }

  function startRender() {
    var prompt = promptEl.value.trim();
    if (!prompt) { showStatus('Enter a render prompt', 'error'); return; }
    doAction('render', {
      prompt: prompt,
      num: document.getElementById('numOptions').value,
      model: document.getElementById('model').value
    });
  }

  function setConfig(cfg) {
    if (cfg.api_key) document.getElementById('apiKey').value = cfg.api_key;
    if (cfg.num_options) document.getElementById('numOptions').value = cfg.num_options;
    if (cfg.model) document.getElementById('model').value = cfg.model;
    if (cfg.last_prompt) { promptEl.value = cfg.last_prompt; charCountEl.textContent = cfg.last_prompt.length; }
  }

  function setLoading(active, msg, sub) {
    document.getElementById('loadingOverlay').classList.toggle('active', active);
    document.getElementById('renderBtn').disabled = active;
    if (msg) document.getElementById('loadingText').textContent = msg;
    if (sub) document.getElementById('loadingSub').textContent = sub;
    if (!active) { setProgress(0); }
  }

  function setProgress(pct) {
    pct = Math.min(100, Math.max(0, Math.round(pct)));
    document.getElementById('progressPct').textContent = pct + '%';
    document.getElementById('progressFill').style.width = pct + '%';
  }

  function setEnhancedPrompt(text) {
    promptEl.value = text;
    charCountEl.textContent = text.length;
    showStatus('Prompt enhanced!', 'success');
    setTimeout(hideStatus, 2000);
  }

  function showStatus(msg, type) {
    var el = document.getElementById('status');
    el.textContent = msg; el.className = 'status ' + type;
  }
  function hideStatus() { document.getElementById('status').className = 'status'; }
</script>
</body>
</html>'''


RESULTS_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  :root {{
    --bg-primary: #1a1a2e; --bg-card: #1e2a47; --bg-input: #0f1629;
    --border: #2a3a5c; --text-primary: #e8e8e8; --text-secondary: #a0a8c0;
    --text-muted: #6b7394; --accent: #e94560; --accent-hover: #ff6b81;
    --accent-glow: rgba(233,69,96,0.3); --success: #2ed573;
    --gradient-start: #e94560; --gradient-end: #0abde3;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-primary); color: var(--text-primary); padding: 20px; overflow-y: auto; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
  .header h1 {{ font-size: 18px; font-weight: 700; background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .tabs {{ display: flex; gap: 4px; background: var(--bg-input); border-radius: 8px; padding: 3px; margin-bottom: 16px; overflow-x: auto; }}
  .tab {{ flex: 1; padding: 8px 16px; border: none; border-radius: 6px; background: transparent; color: var(--text-muted); font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: inherit; white-space: nowrap; }}
  .tab.active {{ background: var(--accent); color: white; }}
  .tab:hover:not(.active) {{ color: var(--text-primary); background: var(--bg-card); }}
  .tab.error-tab {{ color: #ff4757; }}
  .render-img {{ width: 100%; border-radius: 10px; border: 1px solid var(--border); display: block; }}
  .btn {{ display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 18px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: inherit; flex: 1; }}
  .btn-save {{ background: linear-gradient(135deg, var(--gradient-start), var(--accent-hover)); color: white; }}
  .btn-save:hover {{ transform: translateY(-1px); box-shadow: 0 4px 15px var(--accent-glow); }}
  .btn-folder {{ background: var(--bg-input); border: 1px solid var(--border); color: var(--text-secondary); }}
  .btn-folder:hover {{ border-color: var(--accent); color: var(--text-primary); }}
  .actions {{ display: flex; gap: 8px; margin-top: 16px; }}
  .error-card {{ background: rgba(255,71,87,0.08); border: 1px solid rgba(255,71,87,0.3); border-radius: 10px; padding: 24px; text-align: center; }}
  .error-card h3 {{ color: #ff4757; font-size: 14px; margin-bottom: 8px; }}
  .error-card p {{ color: var(--text-muted); font-size: 13px; word-break: break-word; }}
  .ai-note {{ margin-top: 12px; padding: 10px 14px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; font-size: 12px; color: var(--text-secondary); line-height: 1.5; }}
  .ai-note strong {{ color: var(--accent); }}
  .result-panel {{ display: none; }}
  .result-panel.active {{ display: block; }}
  .folder-info {{ margin-top: 16px; padding: 10px 14px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; font-size: 11px; color: var(--text-muted); text-align: center; }}
  .folder-info strong {{ color: var(--text-secondary); }}
</style>
</head>
<body>
<div class="header"><h1>Render Results</h1></div>
<div class="tabs" id="tabs">{tabs_html}</div>
{panels_html}
<div class="folder-info">
  <strong>Saved to:</strong> {output_folder}
  <br><button class="btn btn-folder" style="margin-top:8px;flex:none;padding:6px 14px;font-size:11px" onclick="doAction('open_folder','0')">Open Folder</button>
</div>
<script>
  function switchTab(index) {{
    var tabs = document.querySelectorAll('.tab');
    var panels = document.querySelectorAll('.result-panel');
    for (var i = 0; i < tabs.length; i++) {{
      tabs[i].className = tabs[i].className.replace(' active', '');
      panels[i].className = panels[i].className.replace(' active', '');
    }}
    tabs[index].className += ' active';
    panels[index].className += ' active';
  }}
  function doAction(action, idx) {{
    window.location.href = 'nano://' + action + '/' + idx;
  }}
</script>
</body>
</html>'''


def build_results_html(results, output_folder):
    """Build results HTML with relative image paths (HTML lives in same temp dir)."""
    tabs = []
    panels = []
    for i, r in enumerate(results):
        active = ' active' if i == 0 else ''
        err_class = '' if r['success'] else ' error-tab'
        label = 'Variation {}'.format(i + 1)
        if not r['success']:
            label += ' (Failed)'
        tabs.append(
            '<button class="tab{}{}" onclick="switchTab({})">{}</button>'.format(
                active, err_class, i, label))

        if r['success']:
            # Use just the filename — HTML file is in the same folder
            img_filename = os.path.basename(r['path'])
            text_html = ''
            if r.get('text'):
                safe_text = r['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                text_html = '<div class="ai-note"><strong>AI Notes:</strong> {}</div>'.format(safe_text)
            panels.append(
                '<div class="result-panel{}" id="panel-{}">'
                '<img class="render-img" src="{}">'
                '{}'
                '<div class="actions">'
                '<button class="btn btn-save" onclick="doAction(\'save\',{})">Save As...</button>'
                '<button class="btn btn-folder" onclick="doAction(\'open_folder\',{})">Open Folder</button>'
                '</div></div>'.format(active, i, img_filename, text_html, i, i))
        else:
            safe_err = r.get('error', 'Unknown error').replace('&', '&amp;').replace('<', '&lt;')
            panels.append(
                '<div class="result-panel{}" id="panel-{}">'
                '<div class="error-card"><h3>Rendering Failed</h3><p>{}</p></div>'
                '</div>'.format(active, i, safe_err))

    # Escape backslashes in folder path for display
    display_folder = output_folder.replace('\\', ' / ')

    return RESULTS_HTML_TEMPLATE.format(
        tabs_html='\n'.join(tabs),
        panels_html='\n'.join(panels),
        output_folder=display_folder
)


def write_results_html_file(results, output_folder):
    """Write results HTML to a temp file and return the file path."""
    html = build_results_html(results, output_folder)
    html_path = os.path.join(output_folder, "results_{}.html".format(
        time.strftime('%Y%m%d_%H%M%S')))
    with open(html_path, 'w') as f:
        f.write(html)
    return html_path


# -- WebView Dialog -----------------------------------------------------------

class NanoBananaForm(Forms.Form):
    def __init__(self):
        self.config = load_config()
        self.Title = "Nano Banana Pro Render"
        self.ClientSize = EtoDrawing.Size(520, 660)
        self.Resizable = True

        self.webview = Forms.WebView()
        self.webview.DocumentLoading += self._on_navigate
        self.Content = self.webview
        self.webview.LoadHtml(PROMPT_HTML)

        self.Shown += self._on_shown

    def _on_shown(self, sender, e):
        try:
            self.webview.ExecuteScript("setConfig({})".format(json.dumps(self.config)))
        except Exception:
            pass

    def _run_on_ui(self, func):
        Forms.Application.Instance.AsyncInvoke(func)

    def _exec_js(self, script):
        self._run_on_ui(lambda: self.webview.ExecuteScript(script))

    def _on_navigate(self, sender, e):
        url = e.Uri.ToString() if e.Uri else ''
        if not url.startswith('nano://'):
            return
        e.Cancel = True

        parts = url.replace('nano://', '').split('/', 1)
        action = parts[0]
        payload_str = parts[1] if len(parts) > 1 else '{}'

        try:
            import sys
            if sys.version_info[0] >= 3:
                from urllib.parse import unquote
            else:
                from urllib import unquote
            payload_str = unquote(payload_str)
        except Exception:
            pass

        if action == 'save_key':
            self._handle_save_key(payload_str)
        elif action == 'enhance':
            self._handle_enhance(payload_str)
        elif action == 'render':
            self._handle_render(payload_str)

    def _handle_save_key(self, payload_str):
        try:
            data = json.loads(payload_str)
            key = data.get('key', '').strip()
            if not key:
                self._exec_js("showStatus('Please enter an API key','error')")
                return
            self.config['api_key'] = key
            save_config(self.config)
            self._exec_js("showStatus('API key saved','success')")
        except Exception as ex:
            self._exec_js("showStatus('Error: {}','error')".format(str(ex).replace("'", "\\'")))

    def _handle_enhance(self, payload_str):
        try:
            data = json.loads(payload_str)
            prompt = data.get('prompt', '').strip()
            if not prompt:
                self._exec_js("showStatus('Type a prompt first','error')")
                return
            api_key = self.config.get('api_key', '')
            if not api_key:
                self._exec_js("showStatus('Set your API key first','error')")
                return
        except Exception:
            return

        self._exec_js("showStatus('Enhancing prompt...','success')")

        def do_enhance():
            enhanced = enhance_prompt_api(api_key, prompt)
            escaped = json.dumps(enhanced)
            self._exec_js("setEnhancedPrompt({})".format(escaped))

        threading.Thread(target=do_enhance).start()

    def _handle_render(self, payload_str):
        try:
            data = json.loads(payload_str)
            prompt = data.get('prompt', '').strip()
            num = int(data.get('num', 2))
            model = data.get('model', 'gemini-2.5-flash-image')
        except Exception:
            return

        api_key = self.config.get('api_key', '')
        if not api_key:
            self._exec_js("showStatus('Set your API key first','error')")
            return

        num = max(1, min(4, num))
        self.config['num_options'] = num
        self.config['last_prompt'] = prompt
        self.config['model'] = model
        save_config(self.config)

        # Progress: capture=10%, then each variation splits the remaining 90%
        var_pct = 90.0 / num

        self._exec_js("setLoading(true,'Capturing viewport...','Preparing your scene')")
        self._exec_js("setProgress(0)")

        def do_render():
            try:
                # Capture must run on UI thread
                capture_result = [None, None]

                def do_capture():
                    try:
                        capture_result[0] = capture_viewport()
                    except Exception as ex:
                        capture_result[1] = str(ex)

                Forms.Application.Instance.Invoke(do_capture)

                if capture_result[1]:
                    self._exec_js("setLoading(false)")
                    self._exec_js("showStatus('Capture failed: {}','error')".format(
                        capture_result[1].replace("'", "\\'")))
                    return

                capture_path = capture_result[0]
                self._exec_js("setProgress(10)")
                self._exec_js("setLoading(true,'Uploading to Gemini API...','Sending captured image')")

                image_b64 = image_to_base64(capture_path)

                results = []
                for i in range(num):
                    step_start_pct = 10 + (i * var_pct)
                    # Show "sending" at start of each variation
                    self._exec_js("setProgress({})".format(int(step_start_pct)))
                    self._exec_js(
                        "setLoading(true,'Rendering variation {} of {}...','Waiting for AI response — this takes 15-60s')".format(
                            i + 1, num))

                    result = call_gemini_api(api_key, model, prompt, image_b64, i)
                    results.append(result)

                    # After each variation completes, update progress
                    done_pct = 10 + ((i + 1) * var_pct)
                    self._exec_js("setProgress({})".format(int(done_pct)))

                    if result['success']:
                        self._exec_js(
                            "setLoading(true,'Variation {} complete!','{}')".format(
                                i + 1,
                                'Starting next variation...' if i < num - 1 else 'All done! Opening results...'))

                # Free the upload image from memory
                del image_b64

                self._exec_js("setProgress(100)")
                self._exec_js("setLoading(false)")

                # Show results in new window — using file paths, not base64!
                def show_results():
                    try:
                        results_form = ResultsForm(results, TEMP_DIR)
                        results_form.Owner = self
                        results_form.Show()
                    except Exception as ex:
                        # If viewer fails, at least tell user where files are
                        msg = "Viewer error: {}\n\nYour renders are in:\n{}".format(str(ex), TEMP_DIR)
                        Forms.MessageBox.Show(self, msg, "Render Complete")
                        try:
                            System.Diagnostics.Process.Start("explorer.exe", TEMP_DIR)
                        except Exception:
                            pass

                self._run_on_ui(show_results)

            except Exception as ex:
                self._exec_js("setLoading(false)")
                self._exec_js("showStatus('Error: {}','error')".format(
                    str(ex).replace("'", "\\'")))

        threading.Thread(target=do_render).start()


class ResultsForm(Forms.Form):
    def __init__(self, results, output_folder):
        self.Title = "Render Results - Nano Banana Pro"
        self.ClientSize = EtoDrawing.Size(950, 700)
        self.Resizable = True
        self.results = results
        self.output_folder = output_folder

        self.webview = Forms.WebView()
        self.webview.DocumentLoading += self._on_navigate
        self.Content = self.webview

        # Write HTML to temp file now, load in _on_shown when WebView is ready
        self._html_path = write_results_html_file(results, output_folder)
        self.Shown += self._on_shown

        # Log render summary for debugging
        self._write_log(results)

    def _write_log(self, results):
        """Write a log file so user can see what happened even if viewer crashes."""
        try:
            log_path = os.path.join(self.output_folder, "render_log.txt")
            with open(log_path, 'w') as f:
                f.write("Nano Banana Render Log - {}\n".format(time.strftime('%Y-%m-%d %H:%M:%S')))
                f.write("=" * 50 + "\n\n")
                for i, r in enumerate(results):
                    f.write("Variation {}:\n".format(i + 1))
                    if r.get('success'):
                        f.write("  Status: SUCCESS\n")
                        f.write("  File: {}\n".format(r.get('path', 'N/A')))
                        f.write("  Exists: {}\n".format(os.path.exists(r.get('path', ''))))
                    else:
                        f.write("  Status: FAILED\n")
                        f.write("  Error: {}\n".format(r.get('error', 'Unknown')))
                    f.write("\n")
                f.write("Results HTML: {}\n".format(self._html_path))
                f.write("Output folder: {}\n".format(self.output_folder))
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass

    def _on_shown(self, sender, e):
        """Load the results HTML once the WebView is fully initialized."""
        try:
            self.webview.Url = System.Uri(self._html_path)
        except Exception as ex:
            # Fallback: show a simple message with file paths
            self._show_fallback(str(ex))

    def _show_fallback(self, error_msg):
        """If WebView fails, show file paths in a simple dialog."""
        lines = ["Results viewer failed to load: {}\n".format(error_msg),
                 "Your rendered images are saved in:\n{}".format(self.output_folder), ""]
        for i, r in enumerate(self.results):
            if r.get('success'):
                lines.append("Variation {}: {}".format(i + 1, r.get('path', '?')))
            else:
                lines.append("Variation {}: FAILED - {}".format(i + 1, r.get('error', '?')))
        Forms.MessageBox.Show(self, "\n".join(lines), "Render Results")

    def _on_navigate(self, sender, e):
        url = e.Uri.ToString() if e.Uri else ''
        if not url.startswith('nano://'):
            return
        e.Cancel = True

        parts = url.replace('nano://', '').split('/', 1)
        action = parts[0]

        if action == 'save':
            self._save_image(parts)
        elif action == 'open_folder':
            self._open_folder()

    def _save_image(self, parts):
        try:
            idx = int(parts[1]) if len(parts) > 1 else 0
            r = self.results[idx]
            if r.get('success') and r.get('path') and os.path.exists(r['path']):
                dialog = Forms.SaveFileDialog()
                dialog.Title = "Save Rendered Image"
                dialog.Filters.Add(Forms.FileFilter("PNG Images", ".png"))
                if dialog.ShowDialog(self) == Forms.DialogResult.Ok:
                    dest = dialog.FileName
                    if not dest.endswith('.png'):
                        dest += '.png'
                    shutil.copy2(r['path'], dest)
                    Forms.MessageBox.Show(self, "Image saved to:\n{}".format(dest), "Saved")
        except Exception as ex:
            Forms.MessageBox.Show(self, "Save failed: {}".format(str(ex)), "Error")

    def _open_folder(self):
        try:
            System.Diagnostics.Process.Start("explorer.exe", self.output_folder)
        except Exception:
            try:
                os.startfile(self.output_folder)
            except Exception:
                pass


# -- Entry Point --------------------------------------------------------------

def main():
    form = NanoBananaForm()
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Show()


main()
