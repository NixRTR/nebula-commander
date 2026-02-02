#!/usr/bin/env python3
"""
ncclient - Nebula Commander device client (dnclient-style).

Enroll once with a code from the Nebula Commander UI, then run as a daemon
to poll for config and certs and optionally orchestrate the Nebula process
(dnclientd-style: start/restart Nebula when config changes).

  ncclient enroll --server https://nebula-commander.example.com --code XXXXXXXX
  ncclient run --server https://nebula-commander.example.com [--output-dir /etc/nebula] [--interval 60]
  ncclient run --server ... --nebula /usr/bin/nebula
  ncclient run --server ... --restart-service nebula

Requires: requests

Copyright (C) 2025 NixRTR.  This program is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public License as
published by the Free Software Foundation, version 3 or later.  See the
LICENSE file in this directory for the full text.
"""

import argparse
import atexit
import os
import signal
import subprocess
import sys
import time
import zipfile
import io

try:
    import requests
except ImportError:
    print("ncclient requires 'requests'. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


def _server_url(server: str) -> str:
    base = server.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    return base


def _token_path() -> str:
    try:
        if os.getuid() == 0:
            return "/etc/nebula-commander/token"
    except (AttributeError, OSError):
        pass  # Windows or other
    return os.path.expanduser("~/.config/nebula-commander/token")


def _default_output_dir() -> str:
    """Default directory for config/certs; Windows-friendly."""
    if sys.platform == "win32":
        return os.path.join(os.path.expanduser("~"), ".nebula")
    return "/etc/nebula"


def cmd_enroll(server: str, code: str, token_path_out: str | None) -> None:
    base = _server_url(server)
    url = f"{base}/api/device/enroll"
    code = code.strip().upper()
    r = requests.post(url, json={"code": code}, timeout=30)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        print(f"Enroll failed: {detail}", file=sys.stderr)
        sys.exit(1)
    data = r.json()
    token = data["device_token"]
    out_path = token_path_out or _token_path()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(token)
    os.chmod(out_path, 0o600)
    print(f"Enrolled. Token saved to {out_path}")
    print(f"Run: ncclient run --server {base}")


def _config_path(output_dir: str) -> str:
    return os.path.join(output_dir, "config.yaml")


def _start_nebula(nebula_bin: str, output_dir: str) -> subprocess.Popen | None:
    config = _config_path(output_dir)
    if not os.path.exists(config):
        return None
    try:
        proc = subprocess.Popen(
            [nebula_bin, "-config", config],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        print(f"Started Nebula (PID {proc.pid})")
        return proc
    except FileNotFoundError:
        print(f"Nebula binary not found: {nebula_bin}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Failed to start Nebula: {e}", file=sys.stderr)
        return None


def _stop_nebula(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except Exception:
        pass
    print("Stopped Nebula")


def _restart_systemd_service(service_name: str) -> bool:
    try:
        subprocess.run(
            ["systemctl", "restart", service_name],
            check=True,
            capture_output=True,
            timeout=30,
        )
        print(f"Restarted systemd service: {service_name}")
        return True
    except FileNotFoundError:
        print("systemctl not found (not Linux systemd?)", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"systemctl restart failed: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)
        return False


def cmd_run(
    server: str,
    token_path_in: str | None,
    output_dir: str,
    interval: int,
    nebula_bin: str | None,
    restart_service: str | None,
) -> None:
    base = _server_url(server)
    path = token_path_in or _token_path()
    if not os.path.exists(path):
        print(f"Token not found at {path}. Run 'ncclient enroll' first.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        token = f.read().strip()
    url = f"{base}/api/device/bundle"
    headers = {"Authorization": f"Bearer {token}"}
    os.makedirs(output_dir, exist_ok=True)
    last_etag: str | None = None
    nebula_proc: subprocess.Popen | None = None

    if nebula_bin:
        print(f"Orchestrating Nebula: {nebula_bin} (restart on config change)")
    if restart_service:
        print(f"Orchestrating service: systemctl restart {restart_service} on config change")
    print(f"Polling {url} every {interval}s. Output: {output_dir}. Ctrl+C to stop.")

    def on_exit() -> None:
        _stop_nebula(nebula_proc)

    atexit.register(on_exit)
    try:
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    except (ValueError, OSError):
        pass  # not main thread or Windows

    while True:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 401:
                print("Token invalid or expired. Re-enroll with a new code.", file=sys.stderr)
                sys.exit(1)
            if not r.ok:
                print(f"Poll failed: {r.status_code} {r.text[:200]}", file=sys.stderr)
                time.sleep(interval)
                continue
            etag = r.headers.get("ETag")
            # Skip write only when we have a previous etag and it's unchanged (saves re-writing when server sends ETag).
            # When server sends no ETag, we always write (first time and every poll).
            if last_etag is not None and etag == last_etag:
                if nebula_bin and (nebula_proc is None or nebula_proc.poll() is not None):
                    nebula_proc = _start_nebula(nebula_bin, output_dir)
                time.sleep(interval)
                continue
            last_etag = etag
            z = zipfile.ZipFile(io.BytesIO(r.content), "r")
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                data = z.read(name)
                out = os.path.join(output_dir, name)
                os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
                with open(out, "wb") as f:
                    f.write(data)
                print(f"Wrote {out}")
            if nebula_bin:
                _stop_nebula(nebula_proc)
                nebula_proc = _start_nebula(nebula_bin, output_dir)
            if restart_service:
                _restart_systemd_service(restart_service)
        except requests.RequestException as e:
            print(f"Request error: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        time.sleep(interval)

    atexit.unregister(on_exit)
    _stop_nebula(nebula_proc)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Nebula Commander device client (dnclient/dnclientd-style). Enroll once, then run to poll config and certs and optionally start/restart Nebula."
    )
    ap.add_argument("--server", "-s", required=True, help="Nebula Commander base URL (e.g. https://nc.example.com)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_enroll = sub.add_parser("enroll", help="Enroll with a one-time code from the UI")
    p_enroll.add_argument("--code", "-c", required=True, help="Enrollment code")
    p_enroll.add_argument("--token-file", help="Path to save device token (default: ~/.config/nebula-commander/token or /etc/nebula-commander/token)")

    p_run = sub.add_parser("run", help="Run daemon: poll for config and certs, optionally start/restart Nebula (dnclientd-style)")
    p_run.add_argument("--token-file", help="Path to device token file")
    p_run.add_argument("--output-dir", "-o", default=None, help="Directory to write config.yaml, ca.crt, host.crt (default: /etc/nebula on Linux, ~/.nebula on Windows)")
    p_run.add_argument("--interval", "-i", type=int, default=60, help="Poll interval in seconds (default: 60)")
    p_run.add_argument("--nebula", "-n", metavar="PATH", help="Path to nebula binary if not in PATH (default: run 'nebula' from PATH)")
    p_run.add_argument("--restart-service", "-r", metavar="NAME", help="Restart this systemd service after config change instead of running nebula (e.g. nebula)")

    args = ap.parse_args()
    server = args.server

    if args.cmd == "enroll":
        cmd_enroll(server, args.code, getattr(args, "token_file", None))
    elif args.cmd == "run":
        if getattr(args, "nebula", None) and getattr(args, "restart_service", None):
            print("Use only one of --nebula or --restart-service.", file=sys.stderr)
            sys.exit(1)
        nebula_bin = getattr(args, "nebula", None)
        restart_service = getattr(args, "restart_service", None)
        # Default: run nebula from PATH; use --nebula only when it's in a non-standard place.
        if nebula_bin is None and restart_service is None:
            nebula_bin = "nebula"
        cmd_run(
            server,
            getattr(args, "token_file", None),
            args.output_dir or _default_output_dir(),
            args.interval,
            nebula_bin,
            restart_service,
        )


if __name__ == "__main__":
    main()
