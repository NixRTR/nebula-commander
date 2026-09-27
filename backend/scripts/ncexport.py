"""
Offline tool for Nebula Commander instance exports (no server or database needed).

    python -m backend.scripts.ncexport inspect export.ncexport.age
    python -m backend.scripts.ncexport decrypt export.ncexport.age export.zip

Exports are standard age files, so `age -d` works too.
"""
import argparse
import getpass
import io
import json
import sys
import zipfile
from pathlib import Path

from backend.services.export_crypto import ExportDecryptError, decrypt


def _open(path: str) -> bytes:
    passphrase = getpass.getpass("Export passphrase: ")
    try:
        return decrypt(Path(path).read_bytes(), passphrase)
    except ExportDecryptError as e:
        sys.exit(f"Could not decrypt: {e}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="ncexport", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("inspect", help="decrypt in memory and print the manifest")
    sp.add_argument("file")
    sp = sub.add_parser("decrypt", help="decrypt to a zip file")
    sp.add_argument("file")
    sp.add_argument("output")
    a = p.parse_args(argv)

    archive = _open(a.file)
    if a.cmd == "inspect":
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            print(json.dumps(json.loads(zf.read("manifest.json")), indent=2))
    else:
        out = Path(a.output)
        out.write_bytes(archive)
        try:
            out.chmod(0o600)  # contains private keys
        except OSError:
            pass
        print(f"Wrote {out} ({len(archive)} bytes). It contains private keys: keep it safe.")


if __name__ == "__main__":
    main()
