# Nano Banana Pro Render - SketchUp Plugin

One-click AI rendering for SketchUp using Google's Nano Banana Pro (Gemini 3 Pro Image) API. Capture your current view, describe how you want it rendered, and compare the result with a before/after slider.

## Features

- **One-click view capture** - Snapshots your current SketchUp viewport at 2x resolution
- **Nano Banana Pro rendering** - Sends your view + prompt to Google's Gemini 3 Pro Image API
- **Prompt enhancer** - AI-powered prompt expansion that adds lighting, materials, atmosphere details
- **Before/after slider** - Interactive comparison slider between original and rendered views
- **Multiple variations** - Generate 1-4 render options per prompt to pick the best one
- **Model selection** - Choose between Nano Banana Pro, Nano Banana 2 (fast), or legacy Nano Banana
- **Dark mode UI** - Sleek dark interface throughout
- **Save renders** - Export rendered images as PNG

## Installation

1. Download or clone this repository
2. Copy `nano_banana_render.rb` and the `nano_banana_render/` folder into your SketchUp Plugins directory:
   - **Windows:** `C:\Users\<YOU>\AppData\Roaming\SketchUp\SketchUp 2024\SketchUp\Plugins\`
   - **macOS:** `~/Library/Application Support/SketchUp 2024/SketchUp/Plugins/`
3. Restart SketchUp
4. The plugin appears under **Plugins > Nano Banana Pro Render** and in the toolbar

## Setup

1. Get a Google AI API key from [Google AI Studio](https://aistudio.google.com/apikey)
2. Open the plugin (Plugins > Nano Banana Pro Render > Render Current View)
3. Paste your API key and click **Save**

## Usage

1. Set up your SketchUp view (camera angle, scene, etc.)
2. Click **Render Current View** from the Plugins menu or toolbar
3. Type a prompt describing the render style you want (e.g., "Photorealistic exterior, golden hour, lush landscaping")
4. Optionally click **Enhance Prompt** to auto-expand your prompt with professional rendering details
5. Choose how many variations (1-4) to generate
6. Click **Capture View & Render**
7. Compare results using the before/after slider
8. Save your favorite render

## API Pricing

Nano Banana Pro uses the Gemini API which charges ~$0.04 per generated image. See [Google AI pricing](https://ai.google.dev/pricing) for current rates.

## File Structure

```
nano_banana_render.rb              # Plugin loader/registration
nano_banana_render/
  main.rb                          # Core plugin logic (capture, API, UI management)
  html/
    prompt_dialog.html             # Prompt input UI (dark mode)
    results_dialog.html            # Before/after comparison slider UI
```

## Future Plans

- Rhino (Grasshopper) plugin port
- Batch rendering across saved scenes
- Style presets library
- Render history
