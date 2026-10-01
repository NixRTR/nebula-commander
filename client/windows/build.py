#!/usr/bin/env python3
"""
Run PyInstaller to build the Windows service exe. The service does not bundle
Nebula - it downloads, SHA256-verifies and installs the official release itself
into its SYSTEM/Administrators-only %ProgramData% folder at runtime (see
nebula_install.py), and only ever runs that copy.

Usage (from client/windows/):
  python build.py
"""
import os
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPEC = "ncclient-service.spec"


def run_pyinstaller() -> int:
    spec = os.path.join(SCRIPT_DIR, SPEC)
    if not os.path.isfile(spec):
        print(f"Spec not found: {spec}", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", spec]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=SCRIPT_DIR)  # nosec B603 - sys.executable is absolute, shell=False


def main() -> int:
    if sys.platform != "win32":
        print("This build script is for Windows. Run on Windows to produce the exe.", file=sys.stderr)
        return 1
    return run_pyinstaller()


if __name__ == "__main__":
    sys.exit(main())
