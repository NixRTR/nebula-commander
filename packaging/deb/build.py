#!/usr/bin/env python3
"""
Build .deb packages for nebula-commander: three separate, independently
installable packages (matching the project's Windows MSI split between the
service and the WinUI3 app):

  nebula-commander-client   - frozen ncclient CLI binary (arch-specific)
  nebula-commander-service  - systemd unit + D-Bus policy + polkit action/
                               rule; depends on the distro's own packaged
                               'nebula' rather than bundling one (arch: all)
  nebula-commander-desktop  - GTK4/libadwaita desktop app, shipped as plain
                               Python source (not frozen - GTK/PyGObject
                               freezes poorly with PyInstaller) depending on
                               python3-gi/gir1.2-gtk-4.0/gir1.2-adw-1 (arch: all)

Desktop <-> service IPC is a system D-Bus service (org.beardedtek.
NebulaCommander1, hosted inside the privileged ncclient process - see
client/linux/dbus_server.py), authorized per-call via polkit for any active
local session - not a shared group/group-writable directory, so there's no
usermod/relogin step in nebula-commander-service's postinst.

Builds via plain `dpkg-deb --build --root-owner-group` against a staged
directory tree, not full dpkg-buildpackage/debhelper - these are standalone
binary .deb files attached to GitHub Releases, not uploaded to a real Debian
archive, so the lighter-weight approach is enough (see the approved
packaging plan for the reasoning).

Requires: dpkg-deb - run this on a Debian/Ubuntu host (a debian:12 or
ubuntu:24.04 container, or WSL, work fine; the Windows dev machine this was
written on does not have dpkg-deb natively).

Usage:
    python3 build.py --version 0.5.2
    python3 build.py --version 0.5.2 --only desktop service
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess  # nosec B404 - fixed args, shell=False throughout
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent.resolve()
REPO_ROOT = HERE.parent.parent
DIST_DIR = HERE / "dist"

_DEB_ARCH_MAP = {"x86_64": "amd64", "aarch64": "arm64", "amd64": "amd64", "arm64": "arm64"}

# The desktop app no longer imports client.config/client.token_store/
# client.ncclient at all - everything goes through client/linux/dbus_client.py
# to the D-Bus service client/linux/dbus_server.py hosts inside the
# privileged ncclient process instead (see client/linux/desktop.py's module
# docstring). Only __init__.py is still needed, so `client` is unambiguously
# a regular package (not relying on PEP 420 namespace-package behavior) for
# the `from client.linux import ...` imports below to resolve.
_CLIENT_SOURCE_FILES = [
    "__init__.py",
]
_LINUX_SOURCE_FILES = [
    "__init__.py",
    "desktop.py",
    "notify.py",
    "service_control.py",
    "autostart.py",
    "dbus_client.py",
]


def deb_arch(machine: str | None) -> str:
    machine = (machine or platform.machine()).lower()
    if machine not in _DEB_ARCH_MAP:
        raise SystemExit(f"Unsupported architecture for .deb build: {machine}")
    return _DEB_ARCH_MAP[machine]


def get_version(explicit: str | None) -> str:
    if explicit:
        return explicit.lstrip("v")
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        tag = out.stdout.strip().lstrip("v")
        return tag or "0.0.0"
    except (subprocess.SubprocessError, OSError):
        return "0.0.0"


def render_control(template_path: Path, version: str, arch: str) -> str:
    text = template_path.read_text(encoding="utf-8")
    return text.replace("@VERSION@", version).replace("@ARCH@", arch)


def copy_tree(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def build_deb(stage_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # nosec B603
        ["dpkg-deb", "--build", "--root-owner-group", str(stage_dir), str(output_path)],
        check=True,
    )
    print(f"Built {output_path}")


def stage_client(version: str, arch: str, ncclient_binary: Path, work_dir: Path) -> Path:
    stage = work_dir / "nebula-commander-client"
    copy_tree(HERE / "client" / "payload", stage)
    (stage / "DEBIAN").mkdir(parents=True, exist_ok=True)
    control = render_control(HERE / "client" / "DEBIAN" / "control.in", version, arch)
    (stage / "DEBIAN" / "control").write_text(control, encoding="utf-8")

    bin_dir = stage / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest_bin = bin_dir / "ncclient"
    shutil.copy2(ncclient_binary, dest_bin)
    dest_bin.chmod(0o755)
    return stage


def stage_service(version: str, arch: str, work_dir: Path) -> Path:
    stage = work_dir / "nebula-commander-service"
    copy_tree(HERE / "service" / "payload", stage)
    (stage / "DEBIAN").mkdir(parents=True, exist_ok=True)
    control = render_control(HERE / "service" / "DEBIAN" / "control.in", version, arch)
    (stage / "DEBIAN" / "control").write_text(control, encoding="utf-8")
    for name in ("postinst", "postrm", "conffiles"):
        src = HERE / "service" / "DEBIAN" / name
        if not src.exists():
            continue
        dst = stage / "DEBIAN" / name
        shutil.copy2(src, dst)
        dst.chmod(0o755 if name in ("postinst", "postrm") else 0o644)

    (stage / "usr" / "lib" / "nebula-commander" / "ncclient-run.sh").chmod(0o755)
    (stage / "usr" / "lib" / "systemd" / "system" / "ncclient.service").chmod(0o644)
    (stage / "etc" / "default" / "ncclient").chmod(0o644)
    (stage / "usr" / "share" / "polkit-1" / "rules.d" / "org.nixrtr.nebulacommander.rules").chmod(0o644)
    (stage / "usr" / "share" / "polkit-1" / "actions" / "org.beardedtek.NebulaCommander1.policy").chmod(0o644)
    (stage / "usr" / "share" / "dbus-1" / "system.d" / "org.beardedtek.NebulaCommander1.conf").chmod(0o644)
    (stage / "usr" / "lib" / "tmpfiles.d" / "ncclient.conf").chmod(0o644)
    return stage


def stage_desktop(version: str, arch: str, work_dir: Path) -> Path:
    stage = work_dir / "nebula-commander-desktop"
    copy_tree(HERE / "desktop" / "payload", stage)
    (stage / "DEBIAN").mkdir(parents=True, exist_ok=True)
    control = render_control(HERE / "desktop" / "DEBIAN" / "control.in", version, arch)
    (stage / "DEBIAN" / "control").write_text(control, encoding="utf-8")
    for name in ("postinst", "postrm"):
        src = HERE / "desktop" / "DEBIAN" / name
        dst = stage / "DEBIAN" / name
        shutil.copy2(src, dst)
        dst.chmod(0o755)

    app_client_dir = stage / "usr" / "share" / "nebula-commander-desktop" / "client"
    app_client_dir.mkdir(parents=True, exist_ok=True)
    for name in _CLIENT_SOURCE_FILES:
        shutil.copy2(REPO_ROOT / "client" / name, app_client_dir / name)
        (app_client_dir / name).chmod(0o644)
    linux_dir = app_client_dir / "linux"
    linux_dir.mkdir(parents=True, exist_ok=True)
    for name in _LINUX_SOURCE_FILES:
        shutil.copy2(REPO_ROOT / "client" / "linux" / name, linux_dir / name)
        (linux_dir / name).chmod(0o644)

    (stage / "usr" / "bin" / "nebula-commander-desktop").chmod(0o755)
    (stage / "usr" / "share" / "applications" / "org.beardedtek.NebulaCommander.desktop").chmod(0o644)

    icon_dst = (
        stage / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "org.beardedtek.NebulaCommander.svg"
    )
    icon_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "frontend" / "public" / "logo.svg", icon_dst)
    icon_dst.chmod(0o644)
    return stage


def main() -> int:
    ap = argparse.ArgumentParser(description="Build nebula-commander .deb packages")
    ap.add_argument("--version", help="Package version (default: git describe)")
    ap.add_argument("--arch", default=None, help="Debian arch for nebula-commander-client (default: detect from host)")
    ap.add_argument(
        "--ncclient-binary",
        default=None,
        help="Path to a pre-built frozen ncclient binary (default: client/binaries/dist/ncclient, built if missing)",
    )
    ap.add_argument(
        "--only",
        nargs="*",
        choices=["client", "service", "desktop"],
        help="Build only these packages (default: all three)",
    )
    args = ap.parse_args()

    if shutil.which("dpkg-deb") is None:
        print(
            "dpkg-deb not found - run this on a Debian/Ubuntu host "
            "(a debian:12/ubuntu:24.04 container or WSL works).",
            file=sys.stderr,
        )
        return 1

    version = get_version(args.version)
    arch = deb_arch(args.arch)
    only = set(args.only) if args.only else {"client", "service", "desktop"}

    print(f"Building nebula-commander .deb packages: version={version} arch={arch} packages={sorted(only)}")

    with tempfile.TemporaryDirectory(prefix="nc-deb-") as tmp:
        work_dir = Path(tmp)

        if "client" in only:
            default_binary = REPO_ROOT / "client" / "binaries" / "dist" / "ncclient"
            ncclient_binary = Path(args.ncclient_binary) if args.ncclient_binary else default_binary
            if not ncclient_binary.is_file():
                print(f"{ncclient_binary} not found - building it first...")
                subprocess.run(  # nosec B603
                    [sys.executable, "build.py"], cwd=REPO_ROOT / "client" / "binaries", check=True
                )
            if not ncclient_binary.is_file():
                print(f"ncclient binary still not found at {ncclient_binary} after build", file=sys.stderr)
                return 1
            stage = stage_client(version, arch, ncclient_binary, work_dir)
            build_deb(stage, DIST_DIR / f"nebula-commander-client_{version}_{arch}.deb")

        if "service" in only:
            stage = stage_service(version, arch, work_dir)
            build_deb(stage, DIST_DIR / f"nebula-commander-service_{version}_all.deb")

        if "desktop" in only:
            stage = stage_desktop(version, arch, work_dir)
            build_deb(stage, DIST_DIR / f"nebula-commander-desktop_{version}_all.deb")

    return 0


if __name__ == "__main__":
    sys.exit(main())
