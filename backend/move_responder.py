#!/usr/bin/env python3
"""
Nebula Commander move responder: keeps an old server address pointing devices at the
server they moved to, after the old Nebula Commander instance is gone.

Standalone - Python 3 standard library only, no Nebula Commander install needed:

    python3 move_responder.py move-responder.json [--host 127.0.0.1] [--port 8099]

move-responder.json is downloaded from the old instance's Move page. Put this behind
your reverse proxy for /api/device/ only, so the rest of the domain is free for
anything else; e.g. nginx:

    location /api/device/ { proxy_pass http://127.0.0.1:8099; }

or Caddy:

    handle /api/device/* { reverse_proxy 127.0.0.1:8099 }

Every /api/device/* request gets 410 Gone with the signed move statement in the
X-Nebula-Commander-Move header (and as the body of GET /api/device/move). ncclient
0.9.0+ checks the signature against the key it pinned and moves. Anything else: 404.
Never 401 - ncclient treats that as "this device was revoked".
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOVE_HEADER = "X-Nebula-Commander-Move"


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("statement") or not data.get("new_url"):
        raise SystemExit(f"{path} is not a move-responder.json from the Move page")
    return data


def make_handler(data: dict):
    statement = str(data["statement"])
    new_url = str(data["new_url"])

    class Handler(BaseHTTPRequestHandler):
        server_version = "nc-move-responder"
        sys_version = ""

        def _send(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8", move: bool = True):
            raw = body.encode("utf-8")
            self.send_response(code)
            if move:
                self.send_header(MOVE_HEADER, statement)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def _route(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/device/move":
                self._send(200, statement)
            elif path.startswith("/api/device/"):
                self._send(410, json.dumps({"detail": f"This server has moved to {new_url}"}), "application/json")
            elif path == "/api/health":
                self._send(200, json.dumps({"status": "moved", "new_url": new_url}), "application/json", move=False)
            else:
                self._send(404, "Not found", move=False)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _route

        def log_message(self, fmt, *args):  # quiet: one line per request on stderr
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    return Handler


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Answer old Nebula Commander device requests with a move statement.")
    p.add_argument("file", help="move-responder.json from the Move page")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8099)
    args = p.parse_args(argv)
    data = load(args.file)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(data))
    print(f"Pointing devices at {data['new_url']} on http://{args.host}:{args.port}/api/device/", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
