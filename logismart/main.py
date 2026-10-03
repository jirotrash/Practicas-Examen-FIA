"""
LogiSmart - Centro de control inteligente.

Uso:
    python main.py          -> abre la aplicación de escritorio
    python main.py --web    -> la abre en el navegador (http://localhost:8550)
"""

import logging
import sys

from pathlib import Path

import flet as ft

from gui.app import main

ASSETS = str(Path(__file__).resolve().parent / "assets")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

if __name__ == "__main__":
    if "--web" in sys.argv:
        print("Abre en tu navegador: http://localhost:8550")
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=8550, no_cdn=True, assets_dir=ASSETS)
    else:
        ft.run(main, assets_dir=ASSETS)
