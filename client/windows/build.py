#!/usr/bin/env python3
"""
Run PyInstaller to build ncclient-tray.exe. By default Nebula is not bundled;
the tray uses nebula from the user's PATH or from Settings.

Usage (from client/windows/):
  python build.py [--with-nebula [--nebula-version v1.10.2]]

With --with-nebula, downloads the Windows asset and extracts nebula.exe into
nebula/nebula.exe for packaging. Without it, builds without bundling Nebula.
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
NEBULA_VERSION_DEFAULT = "v1.10.2"
NEBULA_URL_TEMPLATE = "https://github.com/slackhq/nebula/releases/download/{version}/nebula-windows-amd64.zip"
NEBULA_DIR = os.path.join(SCRIPT_DIR, "nebula")
NEBULA_EXE = os.path.join(NEBULA_DIR, "nebula.exe")


def download_nebula(version: str) -> bool:
    url = NEBULA_URL_TEMPLATE.format(version=version)
    zip_path = os.path.join(SCRIPT_DIR, "nebula-windows-amd64.zip")
    print(f"Downloading {url} ...")
    try:
        import urllib.request
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return False
    os.makedirs(NEBULA_DIR, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            found = False
            for name in zf.namelist():
                if name.endswith("nebula.exe"):
                    os.makedirs(NEBULA_DIR, exist_ok=True)
                    with zf.open(name) as src:
                        with open(NEBULA_EXE, "wb") as dst:
                            dst.write(src.read())
                    found = True
                    break
            if not found:
                print("nebula.exe not found in archive", file=sys.stderr)
                return False
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    print(f"Extracted {NEBULA_EXE}")
    return True


def run_pyinstaller() -> int:
    spec = os.path.join(SCRIPT_DIR, "ncclient-tray.spec")
    if not os.path.isfile(spec):
        print(f"Spec not found: {spec}", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", spec]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=SCRIPT_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ncclient-tray.exe (Nebula not bundled by default)")
    parser.add_argument("--with-nebula", action="store_true", help="Download and bundle nebula.exe in the build")
    parser.add_argument("--nebula-version", default=NEBULA_VERSION_DEFAULT, help=f"Nebula release tag when using --with-nebula (default: {NEBULA_VERSION_DEFAULT})")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("This build script is for Windows. Run on Windows to produce ncclient-tray.exe.", file=sys.stderr)
        return 1

    if args.with_nebula:
        if not download_nebula(args.nebula_version):
            return 1
    else:
        if os.path.isdir(NEBULA_DIR):
            shutil.rmtree(NEBULA_DIR, ignore_errors=True)
            print("Removed", NEBULA_DIR, "so the build does not bundle Nebula.")
        print("Building without bundled Nebula. Tray will use nebula from PATH (or Settings, Nebula path).")

    rc = run_pyinstaller()
    if rc == 0 and not args.with_nebula:
        print("Done. ncclient-tray will use the nebula binary from your system PATH (or the path set in Settings).")
    return rc


if __name__ == "__main__":
    sys.exit(main())
