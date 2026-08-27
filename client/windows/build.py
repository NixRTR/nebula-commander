#!/usr/bin/env python3
"""
Run PyInstaller to build the Windows tray and/or service exe. By default Nebula
is not bundled; the service uses nebula from the shared %ProgramData% location,
the user's PATH, or the path set in Settings.

Usage (from client/windows/):
  python build.py [--target {tray,service,both}] [--with-nebula [--nebula-version v1.10.2]]

With --with-nebula, downloads the Windows asset and extracts nebula.exe into
nebula/nebula.exe for packaging into the tray build. Without it, builds without
bundling Nebula. --with-nebula only affects the tray target (the service doesn't
bundle Nebula either way - it's fetched by whichever process downloads it).
"""
import argparse
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, REPO_ROOT)
from client.nebula_download import NEBULA_VERSION_DEFAULT, download_nebula_to_dir  # noqa: E402

NEBULA_DIR = os.path.join(SCRIPT_DIR, "nebula")
NEBULA_EXE = os.path.join(NEBULA_DIR, "nebula.exe")

SPECS = {
    "tray": "ncclient-tray.spec",
    "service": "ncclient-service.spec",
}


def download_nebula(version: str) -> bool:
    ok, exe_path, err = download_nebula_to_dir(version, NEBULA_DIR, log=print)
    if not ok:
        print(f"Download failed: {err}", file=sys.stderr)
        return False
    print(f"Extracted {exe_path}")
    return True


def run_pyinstaller(spec_name: str) -> int:
    spec = os.path.join(SCRIPT_DIR, spec_name)
    if not os.path.isfile(spec):
        print(f"Spec not found: {spec}", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", spec]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=SCRIPT_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Windows tray and/or service exe")
    parser.add_argument("--target", choices=["tray", "service", "both"], default="both", help="Which exe(s) to build (default: both)")
    parser.add_argument("--with-nebula", action="store_true", help="Download and bundle nebula.exe into the tray build")
    parser.add_argument("--nebula-version", default=NEBULA_VERSION_DEFAULT, help=f"Nebula release tag when using --with-nebula (default: {NEBULA_VERSION_DEFAULT})")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("This build script is for Windows. Run on Windows to produce the exe(s).", file=sys.stderr)
        return 1

    targets = ["tray", "service"] if args.target == "both" else [args.target]

    if "tray" in targets:
        if args.with_nebula:
            if not download_nebula(args.nebula_version):
                return 1
        else:
            if os.path.isdir(NEBULA_DIR):
                shutil.rmtree(NEBULA_DIR, ignore_errors=True)
                print("Removed", NEBULA_DIR, "so the tray build does not bundle Nebula.")
            print("Building tray without bundled Nebula. It will use nebula from PATH (or Settings, Nebula path).")

    for target in targets:
        rc = run_pyinstaller(SPECS[target])
        if rc != 0:
            return rc

    if "tray" in targets and not args.with_nebula:
        print("Done. ncclient-tray will use the nebula binary from your system PATH (or the path set in Settings).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
