# Nano Banana Pro Render - Rhino Command Installer
# Run this script once in Rhino to register the NanoBananaRender command alias.
# After running, type "NanoBananaRender" in Rhino to launch the plugin.

import os
import Rhino

script_dir = os.path.dirname(os.path.abspath(__file__))
main_script = os.path.join(script_dir, 'nano_banana_render_rhino.py')

# Create a command alias
alias_name = "NanoBananaRender"
alias_macro = '_-RunPythonScript "{}"'.format(main_script.replace('\\', '\\\\'))

Rhino.ApplicationSettings.CommandAliasList.Add(alias_name, alias_macro)

print("=" * 50)
print("Nano Banana Pro Render installed!")
print("Type 'NanoBananaRender' in the Rhino command line to launch.")
print("=" * 50)
