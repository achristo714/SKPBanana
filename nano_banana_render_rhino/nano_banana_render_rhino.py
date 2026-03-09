# -*- coding: utf-8 -*-
# Nano Banana Pro Render - Rhino Plugin
# AI-powered rendering for Rhinoceros 3D using Google Gemini API
# Run via: _RunPythonScript "nano_banana_render_rhino.py"

import os
import json
import base64
import time

import Rhino
import Rhino.UI
import System
import System.Drawing as Drawing
import System.IO as IO

import Eto.Forms as Forms
import Eto.Drawing as EtoDrawing

# -- Theme Colors -------------------------------------------------------------

class Theme:
    BG_PRIMARY = EtoDrawing.Color.FromArgb(26, 26, 46)
    BG_CARD = EtoDrawing.Color.FromArgb(30, 42, 71)
    BG_INPUT = EtoDrawing.Color.FromArgb(15, 22, 41)
    BORDER = EtoDrawing.Color.FromArgb(42, 58, 92)
    TEXT = EtoDrawing.Color.FromArgb(232, 232, 232)
    TEXT_DIM = EtoDrawing.Color.FromArgb(160, 168, 192)
    TEXT_MUTED = EtoDrawing.Color.FromArgb(107, 115, 148)
    ACCENT = EtoDrawing.Color.FromArgb(233, 69, 96)
    ACCENT_CYAN = EtoDrawing.Color.FromArgb(10, 189, 227)
    SUCCESS = EtoDrawing.Color.FromArgb(46, 213, 115)
    ERROR = EtoDrawing.Color.FromArgb(255, 71, 87)

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

MODELS = [
    ('gemini-2.5-flash-image', 'Nano Banana (Stable)'),
    ('gemini-3.1-flash-image-preview', 'Nano Banana 2 (Latest)'),
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

    size = view.ClientRectangle.Size
    w = max(size.Width * 2, 800)
    h = max(size.Height * 2, 600)

    bitmap = view.CaptureToBitmap(System.Drawing.Size(w, h))
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
            'contents': [{'parts': [{'text': "{}\n\nUser prompt: {}".format(system_prompt, base_prompt)}]}],
            'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 300}
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


# -- Dark Themed Panel Helper -------------------------------------------------

def make_dark_panel(content, padding=12):
    panel = Forms.Panel()
    panel.BackgroundColor = Theme.BG_CARD
    panel.Padding = EtoDrawing.Padding(padding)
    panel.Content = content
    return panel


def styled_label(text, color=None, bold=False, size=12):
    label = Forms.Label()
    label.Text = text
    label.TextColor = color or Theme.TEXT
    if bold:
        label.Font = EtoDrawing.Font(EtoDrawing.FontFamilies.SansFamilyName, size, EtoDrawing.FontStyle.Bold)
    else:
        label.Font = EtoDrawing.Font(EtoDrawing.FontFamilies.SansFamilyName, size)
    return label


def styled_button(text, accent=False):
    btn = Forms.Button()
    btn.Text = text
    btn.Height = 32
    return btn


# -- Results Dialog -----------------------------------------------------------

class ResultsDialog(Forms.Form):
    def __init__(self, original_b64, results):
        self.Title = "Render Results - Nano Banana Pro"
        self.ClientSize = EtoDrawing.Size(920, 680)
        self.Resizable = True
        self.BackgroundColor = Theme.BG_PRIMARY
        self.original_b64 = original_b64
        self.results = results
        self._build_ui()

    def _build_ui(self):
        layout = Forms.DynamicLayout()
        layout.DefaultSpacing = EtoDrawing.Size(10, 10)
        layout.Padding = EtoDrawing.Padding(20)

        # Header
        layout.AddRow(styled_label("Render Results", Theme.ACCENT, bold=True, size=18))
        layout.AddRow(styled_label("Compare your AI-rendered variations below", Theme.TEXT_MUTED, size=11))
        layout.AddRow(None)

        # Tabs
        self.tab_control = Forms.TabControl()

        for i, result in enumerate(self.results):
            page = Forms.TabPage()
            page.Text = "  Variation {}  ".format(i + 1) if result['success'] else "  Variation {} (Failed)  ".format(i + 1)

            page_layout = Forms.DynamicLayout()
            page_layout.DefaultSpacing = EtoDrawing.Size(8, 8)
            page_layout.Padding = EtoDrawing.Padding(16)

            if result['success']:
                render_b64 = image_to_base64(result['path'])
                img_bytes = System.Convert.FromBase64String(render_b64)
                stream = IO.MemoryStream(img_bytes)
                eto_image = EtoDrawing.Bitmap(stream)

                image_view = Forms.ImageView()
                image_view.Image = eto_image

                page_layout.AddRow(image_view)

                if result.get('text'):
                    note_label = styled_label("AI Notes: {}".format(result['text']), Theme.TEXT_DIM, size=11)
                    note_label.Wrap = Forms.WrapMode.Word
                    page_layout.AddRow(make_dark_panel(note_label, 10))

                save_btn = styled_button("Save Image")
                save_btn.Tag = result['path']
                save_btn.Click += self._on_save
                page_layout.AddRow(save_btn)
            else:
                err_layout = Forms.DynamicLayout()
                err_layout.DefaultSpacing = EtoDrawing.Size(4, 8)
                err_layout.Padding = EtoDrawing.Padding(20)
                err_layout.AddRow(styled_label("Rendering Failed", Theme.ERROR, bold=True, size=14))
                err_msg = styled_label(result.get('error', 'Unknown error'), Theme.TEXT_DIM, size=11)
                err_msg.Wrap = Forms.WrapMode.Word
                err_layout.AddRow(err_msg)
                page_layout.AddRow(make_dark_panel(err_layout))

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


# -- Main Prompt Dialog (Modeless - you can move the camera!) -----------------

class PromptDialog(Forms.Form):
    def __init__(self):
        self.config = load_config()
        self.Title = "Nano Banana Pro Render"
        self.ClientSize = EtoDrawing.Size(440, 560)
        self.Resizable = True
        self.BackgroundColor = Theme.BG_PRIMARY
        self.Topmost = True
        self._build_ui()

    def _build_ui(self):
        layout = Forms.DynamicLayout()
        layout.DefaultSpacing = EtoDrawing.Size(6, 6)
        layout.Padding = EtoDrawing.Padding(20)

        # ---- Header ----
        layout.AddRow(styled_label("Nano Banana Pro Render", Theme.ACCENT, bold=True, size=18))
        layout.AddRow(styled_label("AI-powered rendering for Rhino", Theme.TEXT_MUTED, size=11))
        layout.AddRow(None)

        # ---- API Key Card ----
        key_layout = Forms.DynamicLayout()
        key_layout.DefaultSpacing = EtoDrawing.Size(6, 6)

        key_layout.AddRow(styled_label("API CONFIGURATION", Theme.TEXT_MUTED, bold=True, size=9))
        key_layout.AddRow(styled_label("Google AI API Key", Theme.TEXT_DIM, size=11))

        key_row = Forms.DynamicLayout()
        key_row.DefaultSpacing = EtoDrawing.Size(6, 0)
        self.api_key_input = Forms.PasswordBox()
        self.api_key_input.Text = self.config.get('api_key', '')

        save_key_btn = styled_button("Save")
        save_key_btn.Width = 60
        save_key_btn.Click += self._on_save_key

        key_row.AddRow(self.api_key_input, save_key_btn)
        key_layout.AddRow(key_row)

        layout.AddRow(make_dark_panel(key_layout))
        layout.AddRow(None)

        # ---- Prompt Card ----
        prompt_layout = Forms.DynamicLayout()
        prompt_layout.DefaultSpacing = EtoDrawing.Size(6, 6)

        prompt_layout.AddRow(styled_label("RENDER PROMPT", Theme.TEXT_MUTED, bold=True, size=9))

        prompt_header = Forms.DynamicLayout()
        prompt_header.DefaultSpacing = EtoDrawing.Size(6, 0)
        enhance_btn = styled_button("Enhance Prompt")
        enhance_btn.Click += self._on_enhance
        prompt_header.AddRow(styled_label("Describe your desired render", Theme.TEXT_DIM, size=11), None, enhance_btn)
        prompt_layout.AddRow(prompt_header)

        self.prompt_input = Forms.TextArea()
        self.prompt_input.Height = 90
        self.prompt_input.Text = self.config.get('last_prompt', '')
        self.prompt_input.BackgroundColor = Theme.BG_INPUT
        self.prompt_input.TextColor = Theme.TEXT
        prompt_layout.AddRow(self.prompt_input)

        # Options
        options_row = Forms.DynamicLayout()
        options_row.DefaultSpacing = EtoDrawing.Size(12, 0)

        var_layout = Forms.DynamicLayout()
        var_layout.DefaultSpacing = EtoDrawing.Size(0, 4)
        var_layout.AddRow(styled_label("Variations", Theme.TEXT_DIM, size=11))
        self.num_options = Forms.DropDown()
        for n in range(1, 5):
            self.num_options.Items.Add("{} option{}".format(n, 's' if n > 1 else ''))
        self.num_options.SelectedIndex = min(self.config.get('num_options', 2) - 1, 3)
        var_layout.AddRow(self.num_options)

        model_layout = Forms.DynamicLayout()
        model_layout.DefaultSpacing = EtoDrawing.Size(0, 4)
        model_layout.AddRow(styled_label("Model", Theme.TEXT_DIM, size=11))
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
        prompt_layout.AddRow(options_row)

        layout.AddRow(make_dark_panel(prompt_layout))
        layout.AddRow(None)

        # ---- Render Button ----
        render_btn = Forms.Button()
        render_btn.Text = "Capture View & Render"
        render_btn.Height = 40
        render_btn.Click += self._on_render
        layout.AddRow(render_btn)

        # ---- Hint ----
        hint = styled_label("Move your camera freely, then click Capture View & Render", Theme.TEXT_MUTED, size=10)
        hint.TextAlignment = Forms.TextAlignment.Center
        layout.AddRow(hint)

        # ---- Status ----
        self.status_label = Forms.Label()
        self.status_label.Text = ""
        self.status_label.TextColor = Theme.SUCCESS
        layout.AddRow(self.status_label)

        layout.AddRow(None)
        self.Content = layout

    def _set_status(self, msg, is_error=False):
        self.status_label.Text = msg
        self.status_label.TextColor = Theme.ERROR if is_error else Theme.SUCCESS

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

        results = []
        for i in range(num):
            self._set_status("Rendering variation {} of {}...".format(i + 1, num))
            result = call_gemini_api(api_key, model_id, prompt, image_b64, i)
            results.append(result)

        self._set_status("Done!")

        results_dlg = ResultsDialog(image_b64, results)
        results_dlg.Owner = self
        results_dlg.Show()


# -- Entry Point --------------------------------------------------------------

def main():
    dialog = PromptDialog()
    dialog.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dialog.Show()


main()
