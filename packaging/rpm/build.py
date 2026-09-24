#!/usr/bin/env python3
"""
Build .rpm packages for nebula-commander: the same three-way split as
packaging/deb/build.py (nebula-commander-client / -service / -desktop),
built from the exact same source of truth - the shared, distro-agnostic
freedesktop.org payload files under packaging/deb/{service,desktop}/payload/
(systemd unit, D-Bus bus policy, polkit action/rule, tmpfiles.d, .desktop
entry) live at identical paths on both Debian/Ubuntu and Fedora/RHEL/
openSUSE, so there's nothing .deb-specific about them worth duplicating
here - only packaging/deb/*/DEBIAN/* (control files, dpkg scriptlets) is
Debian-specific and has an RPM-native equivalent instead (this directory's
own .spec files' %description/Requires, and post.sh/postun.sh scriptlets).

Each package is staged as a plain filesystem tree (no DEBIAN/-equivalent
metadata mixed in - see stage_client/stage_service/stage_desktop below),
then rpmbuild packages that tree directly via `cp -a` in the spec's
%install section plus a generated `%files -f <filelist>` - no %prep/%build
stage, matching packaging/deb/build.py's own "stage a directory, then
archive it" approach rather than a conventional source-tarball RPM build.
Version/release/arch and the staged tree's absolute path are injected via
`rpmbuild --define`, not textual substitution in the .spec files.

Requires: rpmbuild (the `rpm` package on Debian/Ubuntu also provides this
for cross-building, or run natively on a Fedora/RHEL/openSUSE host / WSL
with `rpm` installed via apt).

Usage:
    python3 build.py --version 0.6.2
    python3 build.py --version 0.6.2 --only desktop service
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
DEB_DIR = REPO_ROOT / "packaging" / "deb"
DIST_DIR = HERE / "dist"

_RPM_ARCH_MAP = {"x86_64": "x86_64", "aarch64": "aarch64", "amd64": "x86_64", "arm64": "aarch64"}

# Keep in sync with packaging/deb/build.py's own copies of these two lists -
# see that file's comment for why only __init__.py is needed from client/
# itself and exactly these six files from client/linux/.
_CLIENT_SOURCE_FILES = ["__init__.py"]
_LINUX_SOURCE_FILES = [
    "__init__.py",
    "desktop.py",
    "notify.py",
    "service_control.py",
    "autostart.py",
    "dbus_client.py",
]


def rpm_arch(machine: str | None) -> str:
    machine = (machine or platform.machine()).lower()
    if machine not in _RPM_ARCH_MAP:
        raise SystemExit(f"Unsupported architecture for .rpm build: {machine}")
    return _RPM_ARCH_MAP[machine]


def get_version(explicit: str | None) -> str:
    if explicit:
        version = explicit.lstrip("v")
    else:
        try:
            out = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            version = out.stdout.strip().lstrip("v") or "0.0.0"
        except (subprocess.SubprocessError, OSError):
            version = "0.0.0"
    # RPM's Version field can't contain a hyphen (unlike Debian's, which
    # commonly uses one for a revision suffix) - a raw `git describe` past
    # a tag (e.g. "0.6.2-3-gabcdef") would otherwise make rpmbuild reject
    # the spec outright.
    return version.replace("-", "_")


def copy_tree(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def write_filelist(stage: Path, path: Path, *, owned_dirs: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> None:
    """Walk `stage` and write an RPM %files-compatible list to `path`.

    Files under one of `owned_dirs` are collapsed into a single recursive
    entry for that directory (the standard RPM idiom for a package-private
    tree, so `rpm -e` removes the whole thing, not just the files
    individually listed) - see this module's docstring. Everything else is
    listed file-by-file, since those live in directories shared with other
    packages (systemd, polkit, dbus, filesystem) that this package must not
    claim ownership of. `exclude` is for files the spec already declares
    explicitly (e.g. via %config(noreplace)), which would otherwise be
    listed twice.
    """
    lines: list[str] = []
    covered_owned_dirs: set[str] = set()
    for p in sorted(stage.rglob("*")):
        if p.is_dir():
            continue
        rel = "/" + p.relative_to(stage).as_posix()
        if rel in exclude:
            continue
        owned = next((d for d in owned_dirs if rel == d or rel.startswith(d + "/")), None)
        if owned:
            if owned not in covered_owned_dirs:
                lines.append(owned)
                covered_owned_dirs.add(owned)
            continue
        lines.append(rel)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_rpm(
    spec: Path,
    stage: Path,
    filelist: Path,
    version: str,
    *,
    target_arch: str | None = None,
    post_script: Path | None = None,
    postun_script: Path | None = None,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="nc-rpm-topdir-") as topdir_s:
        topdir = Path(topdir_s)
        for sub in ("BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS", "BUILDROOT"):
            (topdir / sub).mkdir(parents=True, exist_ok=True)

        defines = [
            "--define", f"_topdir {topdir}",
            "--define", f"_version {version}",
            "--define", f"_stage_dir {stage}",
            "--define", f"_filelist {filelist}",
        ]
        if post_script is not None:
            defines += ["--define", f"_post_script {post_script}"]
        if postun_script is not None:
            defines += ["--define", f"_postun_script {postun_script}"]

        cmd = ["rpmbuild", "-bb", *defines]
        if target_arch:
            cmd += ["--target", target_arch]
        cmd.append(str(spec))
        subprocess.run(cmd, check=True)  # nosec B603

        built = list(topdir.glob("RPMS/*/*.rpm"))
        if not built:
            raise SystemExit(f"rpmbuild produced no .rpm under {topdir}/RPMS")
        if len(built) > 1:
            raise SystemExit(f"rpmbuild produced more than one .rpm: {built}")

        DIST_DIR.mkdir(parents=True, exist_ok=True)
        dest = DIST_DIR / built[0].name
        shutil.copy2(built[0], dest)
        print(f"Built {dest}")
        return dest


def stage_client(ncclient_binary: Path, work_dir: Path) -> Path:
    stage = work_dir / "nebula-commander-client"
    bin_dir = stage / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest_bin = bin_dir / "ncclient"
    shutil.copy2(ncclient_binary, dest_bin)
    dest_bin.chmod(0o755)
    return stage


def stage_service(work_dir: Path) -> Path:
    stage = work_dir / "nebula-commander-service"
    copy_tree(DEB_DIR / "service" / "payload", stage)

    (stage / "usr" / "lib" / "nebula-commander" / "ncclient-run.sh").chmod(0o755)
    (stage / "usr" / "lib" / "systemd" / "system" / "ncclient.service").chmod(0o644)
    (stage / "etc" / "default" / "ncclient").chmod(0o644)
    (stage / "usr" / "share" / "polkit-1" / "rules.d" / "org.nixrtr.nebulacommander.rules").chmod(0o644)
    (stage / "usr" / "share" / "polkit-1" / "actions" / "org.beardedtek.NebulaCommander1.policy").chmod(0o644)
    (stage / "usr" / "share" / "dbus-1" / "system.d" / "org.beardedtek.NebulaCommander1.conf").chmod(0o644)
    (stage / "usr" / "lib" / "tmpfiles.d" / "ncclient.conf").chmod(0o644)
    return stage


def stage_desktop(work_dir: Path) -> Path:
    stage = work_dir / "nebula-commander-desktop"
    copy_tree(DEB_DIR / "desktop" / "payload", stage)

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
    ap = argparse.ArgumentParser(description="Build nebula-commander .rpm packages")
    ap.add_argument("--version", help="Package version (default: git describe)")
    ap.add_argument("--arch", default=None, help="RPM arch for nebula-commander-client (default: detect from host)")
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

    if shutil.which("rpmbuild") is None:
        print(
            "rpmbuild not found - install the 'rpm' package (Debian/Ubuntu can "
            "cross-build .rpm via `apt-get install rpm`; Fedora/RHEL/openSUSE "
            "have it as 'rpm-build').",
            file=sys.stderr,
        )
        return 1

    version = get_version(args.version)
    arch = rpm_arch(args.arch)
    only = set(args.only) if args.only else {"client", "service", "desktop"}

    print(f"Building nebula-commander .rpm packages: version={version} arch={arch} packages={sorted(only)}")

    with tempfile.TemporaryDirectory(prefix="nc-rpm-") as tmp:
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
            stage = stage_client(ncclient_binary, work_dir)
            filelist = work_dir / "client.filelist"
            write_filelist(stage, filelist)
            build_rpm(HERE / "client.spec", stage, filelist, version, target_arch=arch)

        if "service" in only:
            stage = stage_service(work_dir)
            filelist = work_dir / "service.filelist"
            write_filelist(
                stage,
                filelist,
                owned_dirs=("/usr/lib/nebula-commander",),
                exclude=("/etc/default/ncclient",),
            )
            build_rpm(
                HERE / "service.spec",
                stage,
                filelist,
                version,
                post_script=HERE / "service" / "post.sh",
                postun_script=HERE / "service" / "postun.sh",
            )

        if "desktop" in only:
            stage = stage_desktop(work_dir)
            filelist = work_dir / "desktop.filelist"
            write_filelist(stage, filelist, owned_dirs=("/usr/share/nebula-commander-desktop",))
            build_rpm(
                HERE / "desktop.spec",
                stage,
                filelist,
                version,
                post_script=HERE / "desktop" / "post.sh",
                postun_script=HERE / "desktop" / "postun.sh",
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
