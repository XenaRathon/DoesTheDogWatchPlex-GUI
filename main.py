"""Entry point for `flet build` — launches the GUI as a native desktop app.

`flet build` packages this module (default module name "main"). The web/Docker
path uses `gui.py --web` instead; both share the same DTDDApp.
"""
import flet as ft

from gui import main

ft.run(main)
