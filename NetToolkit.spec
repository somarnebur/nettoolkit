# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file – builds a single-file, windowed .exe."""

import os

_HERE = SPECPATH

a = Analysis(
    [os.path.join(_HERE, 'src', 'app.py')],
    pathex=[os.path.join(_HERE, 'src')],
    binaries=[],
    datas=[],
    hiddenimports=['httpx', 'httpcore', 'h11', 'certifi', 'idna', 'sniffio', 'anyio'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', '_pytest', 'unittest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NetToolkit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # No console window (like pythonw.exe)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
