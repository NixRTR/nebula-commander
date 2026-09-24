#!/usr/bin/env python3
"""
Vendors the desktop app's Python source into packaging/flatpak/src/ so the
Flatpak manifest's sources are self-contained (local files inside this
directory), not a `type: dir` reference reaching outside it via `../../client`.

This matters specifically for Flathub: a submission lives in its own
isolated repo (just the manifest + whatever local sources it carries), not
the whole nebula-commander monorepo - a source path like `../../client`
would have nothing to resolve to once this manifest is submitted there.
Flathub's docs do allow local sources committed alongside the manifest
(no PyPI/git URL required for pure local files), so vendoring a copy here
is the actual fix, not a workaround.

Run this before every Flatpak build/submission to refresh the vendored
copy from the real source of truth (client/linux/*.py). Keep the file list
below in sync with packaging/deb/build.py's _LINUX_SOURCE_FILES - both
packages ship the same plain-Python payload; there's no cross-package
import between the two build scripts on purpose (keeps packaging/deb/ and
packaging/flatpak/ independently runnable from a bare submission checkout).
"""
from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).parent.resolve()
REPO_ROOT = HERE.parent.parent
SRC_DIR = HERE / "src"

_CLIENT_SOURCE_FILES = ["__init__.py"]
_LINUX_SOURCE_FILES = [
    "__init__.py",
    "desktop.py",
    "notify.py",
    "service_control.py",
    "autostart.py",
    "dbus_client.py",
]


def main() -> None:
    if SRC_DIR.exists():
        shutil.rmtree(SRC_DIR)

    client_dir = SRC_DIR / "client"
    linux_dir = client_dir / "linux"
    linux_dir.mkdir(parents=True, exist_ok=True)

    for name in _CLIENT_SOURCE_FILES:
        shutil.copy2(REPO_ROOT / "client" / name, client_dir / name)
    for name in _LINUX_SOURCE_FILES:
        shutil.copy2(REPO_ROOT / "client" / "linux" / name, linux_dir / name)

    print(f"Vendored {len(_CLIENT_SOURCE_FILES) + len(_LINUX_SOURCE_FILES)} files into {SRC_DIR}")


if __name__ == "__main__":
    main()
