#!/usr/bin/env python3
"""
Build the signed apt + rpm package repository served at pkgs.nebulacommander.com.

Input is a directory of already-built packages (e.g. the .deb/.rpm assets of the last few
GitHub Releases, one subdirectory per release - see
.github/workflows/publish-package-repo.yml); output is a static site root:

  deb/pool/main/n/<package>/<package>_<version>_<arch>.deb
  deb/dists/stable/{Release,InRelease,Release.gpg}
  deb/dists/stable/main/binary-{amd64,arm64}/Packages(.gz)
  deb/nebula-commander.sources     sample deb822 source for /etc/apt/sources.list.d/
  rpm/<name>-<version>-<release>.<arch>.rpm   (each signed with rpmsign)
  rpm/repodata/ (+ repomd.xml.asc)
  rpm/nebula-commander.repo        for /etc/yum.repos.d/ or `zypper addrepo`
  gpg.key                          armored public signing key
  index.html                       install instructions

One `stable` suite serves every Debian/Ubuntu release: the client package is a frozen
PyInstaller binary and the service/desktop packages are Architecture: all, so nothing is
built against a specific distro. The repo is rebuilt from scratch every time - it has no
state of its own, so it can always be regenerated from the release assets.

Requires: dpkg-deb + apt-ftparchive (apt-utils) for .deb input, rpm + rpmsign +
createrepo_c for .rpm input, and gpg with the signing key's secret key imported. Run on a
Debian/Ubuntu host (CI uses ubuntu-latest; WSL works for local testing).

Usage:
    python3 build_repo.py --input release-assets/ --output site/ --key-id <fingerprint>
    PACKAGE_SIGNING_KEY_PASSPHRASE=... python3 build_repo.py ...   # if the key has a passphrase
"""
from __future__ import annotations

import argparse
import gzip
import html
import os
import shutil
import subprocess  # nosec B404 - fixed args, shell=False throughout
import sys
import tempfile
from pathlib import Path

DEFAULT_BASE_URL = "https://pkgs.nebulacommander.com"
SUITE = "stable"
COMPONENT = "main"
DEB_ARCHES = ("amd64", "arm64")
REPO_ID = "nebula-commander"
# apt (1.4+) reads an armored key directly when the file ends in .asc - no gpg --dearmor step.
KEYRING_PATH = "/etc/apt/keyrings/nebula-commander.asc"


def require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise SystemExit(f"{tool} not found - see this script's docstring for what to install.")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)  # nosec B603 - fixed argv, shell=False


class Signer:
    """Wraps gpg/rpmsign with the chosen key, feeding the passphrase (if any) from a
    private temp file so it never appears on a command line."""

    def __init__(self, key_id: str, passphrase: str | None, work_dir: Path) -> None:
        self.key_id = key_id
        self.passphrase_file: Path | None = None
        if passphrase:
            self.passphrase_file = work_dir / "passphrase"
            fd = os.open(self.passphrase_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(passphrase)

    def _gpg_extra(self) -> list[str]:
        if self.passphrase_file is None:
            return []
        return ["--pinentry-mode", "loopback", "--passphrase-file", str(self.passphrase_file)]

    def gpg(self, *args: str) -> None:
        run(["gpg", "--batch", "--yes", "--local-user", self.key_id, *self._gpg_extra(), *args])

    def rpmsign(self, rpm_path: Path) -> None:
        extra = " ".join(self._gpg_extra())
        # Ubuntu's rpm macros point %__gpg at /usr/bin/gpg2, which doesn't exist there.
        cmd = ["rpmsign", "--define", f"__gpg {shutil.which('gpg')}", "--define", f"_gpg_name {self.key_id}"]
        if extra:
            cmd += ["--define", f"_gpg_sign_cmd_extra_args {extra}"]
        run([*cmd, "--addsign", str(rpm_path)], stdout=subprocess.DEVNULL)

    def export_public_key(self) -> str:
        out = run(["gpg", "--armor", "--export", self.key_id], capture_output=True, text=True).stdout
        if "BEGIN PGP PUBLIC KEY BLOCK" not in out:
            raise SystemExit(f"Could not export public key for {self.key_id!r}")
        return out


# ---- apt ----


def deb_field(deb: Path, field: str) -> str:
    return run(["dpkg-deb", "-f", str(deb), field], capture_output=True, text=True).stdout.strip()


def build_deb_repo(debs: list[Path], out: Path, signer: Signer, base_url: str) -> None:
    require("dpkg-deb")
    require("apt-ftparchive")
    deb_root = out / "deb"
    seen: set[str] = set()
    for deb in debs:
        package = deb_field(deb, "Package")
        version = deb_field(deb, "Version")
        arch = deb_field(deb, "Architecture")
        name = f"{package}_{version}_{arch}.deb"
        if name in seen:
            continue
        seen.add(name)
        dest = deb_root / "pool" / COMPONENT / package[0] / package / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deb, dest)
        print(f"  deb  {name}")

    suite_dir = deb_root / "dists" / SUITE
    for arch in DEB_ARCHES:
        bin_dir = suite_dir / COMPONENT / f"binary-{arch}"
        bin_dir.mkdir(parents=True, exist_ok=True)
        # Run from the repo root so Filename: paths are relative to it (pool/...).
        # --arch keeps *_<arch>.deb and *_all.deb, so Architecture: all packages
        # appear in every binary-<arch> index as apt expects.
        packages = run(
            ["apt-ftparchive", "--arch", arch, "packages", "pool"],
            cwd=deb_root, capture_output=True, text=True,
        ).stdout
        (bin_dir / "Packages").write_text(packages, encoding="utf-8")
        with gzip.open(bin_dir / "Packages.gz", "wt", encoding="utf-8") as f:
            f.write(packages)

    release = run(
        [
            "apt-ftparchive",
            "-o", "APT::FTPArchive::Release::Origin=Nebula Commander",
            "-o", "APT::FTPArchive::Release::Label=Nebula Commander",
            "-o", f"APT::FTPArchive::Release::Suite={SUITE}",
            "-o", f"APT::FTPArchive::Release::Codename={SUITE}",
            "-o", f"APT::FTPArchive::Release::Architectures={' '.join(DEB_ARCHES)}",
            "-o", f"APT::FTPArchive::Release::Components={COMPONENT}",
            "-o", "APT::FTPArchive::Release::Description=Nebula Commander packages",
            "release", ".",
        ],
        cwd=suite_dir, capture_output=True, text=True,
    ).stdout
    (suite_dir / "Release").write_text(release, encoding="utf-8")
    signer.gpg("--clearsign", "--output", str(suite_dir / "InRelease"), str(suite_dir / "Release"))
    signer.gpg("--armor", "--detach-sign", "--output", str(suite_dir / "Release.gpg"), str(suite_dir / "Release"))

    (deb_root / f"{REPO_ID}.sources").write_text(
        "Types: deb\n"
        f"URIs: {base_url}/deb\n"
        f"Suites: {SUITE}\n"
        f"Components: {COMPONENT}\n"
        f"Signed-By: {KEYRING_PATH}\n",
        encoding="utf-8",
    )


# ---- rpm ----


def build_rpm_repo(rpms: list[Path], out: Path, signer: Signer, base_url: str) -> None:
    require("rpm")
    require("rpmsign")
    require("createrepo_c")
    rpm_root = out / "rpm"
    rpm_root.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for rpm in rpms:
        name = run(
            ["rpm", "-qp", "--nosignature", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm", str(rpm)],
            capture_output=True, text=True,
        ).stdout.strip()
        if name in seen:
            continue
        seen.add(name)
        dest = rpm_root / name
        shutil.copy2(rpm, dest)
        # Sign here rather than at build time so every release in the repo (including
        # ones built before signing existed) is signed with the same key.
        signer.rpmsign(dest)
        print(f"  rpm  {name}")

    run(["createrepo_c", "--quiet", str(rpm_root)])
    repomd = rpm_root / "repodata" / "repomd.xml"
    signer.gpg("--armor", "--detach-sign", "--output", str(repomd) + ".asc", str(repomd))

    (rpm_root / f"{REPO_ID}.repo").write_text(
        f"[{REPO_ID}]\n"
        "name=Nebula Commander\n"
        f"baseurl={base_url}/rpm\n"
        "enabled=1\n"
        "gpgcheck=1\n"
        "repo_gpgcheck=1\n"
        f"gpgkey={base_url}/gpg.key\n",
        encoding="utf-8",
    )


# ---- landing page ----


def write_index(out: Path, base_url: str) -> None:
    b = html.escape(base_url)
    deb_cmds = html.escape(
        "sudo apt install -y curl\n"
        "sudo install -d -m 0755 /etc/apt/keyrings\n"
        f"sudo curl -fsSL -o {KEYRING_PATH} {base_url}/gpg.key\n"
        f"sudo curl -fsSL -o /etc/apt/sources.list.d/{REPO_ID}.sources {base_url}/deb/{REPO_ID}.sources\n"
        "sudo apt update\n"
        "sudo apt install nebula-commander-desktop nebula-commander-service"
    )
    dnf_cmds = html.escape(
        f"sudo curl -fsSL -o /etc/yum.repos.d/{REPO_ID}.repo {base_url}/rpm/{REPO_ID}.repo\n"
        "sudo dnf install nebula-commander-desktop nebula-commander-service"
    )
    zypper_cmds = html.escape(
        f"sudo zypper addrepo {base_url}/rpm/{REPO_ID}.repo\n"
        "sudo zypper install nebula-commander-desktop nebula-commander-service"
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nebula Commander Packages</title>
<style>
  :root {{ --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --code-bg: #f6f8fa; --border: #d1d9e0; --link: #0969da; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --code-bg: #151b23; --border: #3d444d; --link: #4493f8; }}
  }}
  body {{ margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 32px 16px 48px; }}
  h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
  h2 {{ margin-top: 2rem; font-size: 1.15rem; }}
  p {{ color: var(--muted); }}
  pre {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 0.85rem; }}
  a {{ color: var(--link); }}
</style>
</head>
<body>
<main>
<h1>Nebula Commander packages</h1>
<p>Signed apt and dnf/zypper repositories for the Nebula Commander Linux client, service, and desktop app
(amd64 and arm64). After adding the repository, updates arrive through your normal system updates.
See the <a href="https://nebulacommander.com/docs/usage/ncclient/installation/linux/">installation docs</a>.</p>
<h2>Debian / Ubuntu</h2>
<pre>{deb_cmds}</pre>
<h2>Fedora / RHEL (dnf)</h2>
<pre>{dnf_cmds}</pre>
<h2>openSUSE (zypper)</h2>
<pre>{zypper_cmds}</pre>
<p>Signing key: <a href="{b}/gpg.key">{b}/gpg.key</a></p>
</main>
</body>
</html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the signed Nebula Commander apt/rpm repository")
    ap.add_argument("--input", required=True, type=Path, help="Directory searched recursively for .deb/.rpm files")
    ap.add_argument("--output", required=True, type=Path, help="Site root to create (must not exist or be empty)")
    ap.add_argument("--key-id", required=True, help="gpg key ID/fingerprint of the signing key (secret key must be imported)")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Public URL of the site root (default: {DEFAULT_BASE_URL})")
    ap.add_argument(
        "--passphrase-env",
        default="PACKAGE_SIGNING_KEY_PASSPHRASE",
        help="Environment variable holding the key passphrase, if it has one",
    )
    args = ap.parse_args()

    require("gpg")
    base_url = args.base_url.rstrip("/")
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"{args.output} is not empty")
    args.output.mkdir(parents=True, exist_ok=True)

    debs = sorted(p for p in args.input.rglob("*.deb") if p.is_file())
    rpms = sorted(p for p in args.input.rglob("*.rpm") if p.is_file())
    if not debs and not rpms:
        raise SystemExit(f"No .deb or .rpm files found under {args.input}")

    with tempfile.TemporaryDirectory(prefix="nc-repo-") as tmp:
        signer = Signer(args.key_id, os.environ.get(args.passphrase_env) or None, Path(tmp))
        (args.output / "gpg.key").write_text(signer.export_public_key(), encoding="utf-8")
        if debs:
            print(f"Building apt repository from {len(debs)} .deb file(s)")
            build_deb_repo(debs, args.output, signer, base_url)
        if rpms:
            print(f"Building rpm repository from {len(rpms)} .rpm file(s)")
            build_rpm_repo(rpms, args.output, signer, base_url)
    write_index(args.output, base_url)
    print(f"Repository written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
