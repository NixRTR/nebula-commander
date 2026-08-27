# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ncclient-service (Windows service entry point).
Run from client/windows/: pyinstaller ncclient-service.spec
"""
import os

block_cipher = None

# SPECPATH is provided by PyInstaller and points to the directory containing this spec file
SCRIPT_DIR = SPECPATH
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

service_script = os.path.join(SCRIPT_DIR, 'service.py')

a = Analysis(
    [service_script],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        'client',
        'client.ncclient',
        'client.config',
        'client.token_store',
        'client.dns_apply',
        'client.nebula_download',
        'client.windows',
        'client.windows.shared_paths',
        'client.windows.pipe_protocol',
        'win32serviceutil',
        'win32service',
        'win32event',
        'win32pipe',
        'win32file',
        'win32security',
        'win32crypt',
        'win32timezone',
        'pywintypes',
        'servicemanager',
        'winerror',
        'requests',
        'urllib3',
        'charset_normalizer',
        'certifi',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # This is a service, not a GUI app - no need to pull in tkinter/PIL/pystray,
    # which the tray build needs but this one doesn't.
    excludes=['tkinter', 'PIL', 'pystray'],
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
    name='ncclient-service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=True is harmless: an installed service has no interactive desktop
    # regardless of this flag. It only matters for manual runs (e.g.
    # `ncclient-service.exe debug`, which pywin32's win32serviceutil.HandleCommandLine
    # supports out of the box), where a console makes the output visible.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # No uac_admin manifest - the Service Control Manager controls the run-as
    # account (LocalSystem, set via installer/windows/Product.wxs's ServiceInstall),
    # not a manifest. A manifest-elevated exe launched directly by SCM would be
    # redundant at best and can interact oddly with session-0 service processes.
)
