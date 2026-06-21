"""Tiny path-routing reverse proxy so two agents share one public tunnel.

On a restricted network only one tunnel (e.g. ngrok on :443) may be available,
but ngrok-free gives a single URL. This proxy fans that one URL out by path:

    POST https://<tunnel>/d/submit  -> http://127.0.0.1:8001/submit   (designer)
    POST https://<tunnel>/s/submit  -> http://127.0.0.1:8002/submit   (simulator)

Run it on PORT (default 8000), point one ngrok tunnel at it, and register each
agent with the matching prefixed endpoint URL.

    .venv/bin/python -m loop.tunnel_proxy        # serves on :8000
"""
from __future__ import annotations

import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("TUNNEL_PROXY_PORT", "8000"))
ROUTES = {"/d": 8001, "/s": 8002}  # prefix -> local agent port


def _target(path: str) -> tuple[str, str] | None:
    for prefix, port in ROUTES.items():
        if path == prefix or path.startswith(prefix + "/"):
            return f"http://127.0.0.1:{port}", path[len(prefix):] or "/"
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self, method: str) -> None:
        route = _target(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"no route (use /d/... or /s/...)")
            return
        base, rest = route
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(base + rest, data=body, method=method)
        for h in ("Content-Type", "Accept", "User-Agent"):
            if h in self.headers:
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                self.send_response(resp.status)
                ct = resp.headers.get("Content-Type", "application/octet-stream")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:  # forward the agent's own error status
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001
            msg = f"proxy error: {type(e).__name__}: {e}".encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_POST(self):
        self._proxy("POST")

    def do_GET(self):
        self._proxy("GET")

    def log_message(self, fmt, *args):  # quieter logs
        print(f"[proxy] {self.path} -> {fmt % args}")


if __name__ == "__main__":
    print(f"tunnel proxy on :{PORT}  routes={ROUTES}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
