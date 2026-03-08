# Nano Banana Pro Render - SketchUp Plugin Loader
# Renders the current SketchUp view using Google's Nano Banana Pro (Gemini 3 Pro Image) API

require 'sketchup.rb'
require 'extensions.rb'

module NanoBananaRender
  PLUGIN_DIR = File.dirname(__FILE__)
  PLUGIN_NAME = 'Nano Banana Pro Render'.freeze
  PLUGIN_VERSION = '1.0.0'.freeze
  PLUGIN_DESCRIPTION = 'One-click AI rendering via Nano Banana Pro with before/after comparison'.freeze

  extension = SketchupExtension.new(PLUGIN_NAME, File.join('nano_banana_render', 'main'))
  extension.description = PLUGIN_DESCRIPTION
  extension.version = PLUGIN_VERSION
  extension.creator = 'SKPBanana'
  extension.copyright = '2026'

  Sketchup.register_extension(extension, true)
end
