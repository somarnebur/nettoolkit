"""Launcher for the Concurrent URL File Downloader GUI.

Double-click this .pyw file to start the app without a console window.
"""

import os
import sys

# Point to the src directory so sibling imports work.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
sys.path.insert(0, _SRC)

from app import main

main()
