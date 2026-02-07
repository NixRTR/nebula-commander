# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ncclient-tray (Windows system-tray app).
Bundles tray app and optionally nebula/nebula.exe.
Run from client/windows/: pyinstaller ncclient-tray.spec
"""
import os

block_cipher = None

# SPECPATH is provided by PyInstaller and points to the directory containing this spec file
SCRIPT_DIR = SPECPATH
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# Entry script (run from client/windows/, so tray.py is here)
tray_script = os.path.join(SCRIPT_DIR, 'tray.py')

# Bundled Nebula (optional): nebula/nebula.exe next to this spec
nebula_exe = os.path.join(SCRIPT_DIR, 'nebula', 'nebula.exe')
datas_extra = []
if os.path.isfile(nebula_exe):
    datas_extra.append((nebula_exe, 'nebula'))

a = Analysis(
    [tray_script],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas_extra,
    hiddenimports=[
        'client',
        'client.ncclient',
        'client.windows',
        'client.windows.dialogs',
        'client.windows.icons',
        'client.windows.autostart',
        'pystray',
        'PIL',
        'PIL._tkinter_finder',
        'tkinter',
        'requests',
        'urllib3',
        'charset_normalizer',
        'certifi',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ncclient-tray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
