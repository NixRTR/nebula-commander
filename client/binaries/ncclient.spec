# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ncclient.

This creates a single-file executable that includes:
- Python interpreter
- All dependencies (requests)
- ncclient code

Build with: pyinstaller ncclient.spec
"""

import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Path to the ncclient.py file (parent directory)
ncclient_path = '../ncclient.py'

a = Analysis(
    [ncclient_path],
    pathex=[],
    binaries=[],
    datas=[
        # Include LICENSE file in the bundle
        ('../LICENSE', '.'),
        ('../README.md', '.'),
    ],
    hiddenimports=[
        'requests',
        'urllib3',
        'charset_normalizer',
        'certifi',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ncclient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Use UPX compression if available (reduces size)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # CLI application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Icon (optional - uncomment and provide icon file)
    # icon='ncclient.ico',
)
