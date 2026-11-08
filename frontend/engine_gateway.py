"""The only door from the internet to the engine running on this machine.

    ALLOWED_ORIGINS=https://your-site.vercel.app python3 engine_gateway.py
    ngrok http 8770

Forwards just the calls the website makes, only for the listed site origins,
with a cap on upload size and on how often one visitor can start an analysis.
The engine itself (backend/harmony) stays bound to localhost, unchanged.
"""

from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = int(os.environ.get("GATEWAY_PORT", "8770"))
ENGINE = os.environ.get("ENGINE_URL", "http://127.0.0.1:8765")
COUNTER = os.environ.get("COUNTER_URL", "http://127.0.0.1:8001")
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://127.0.0.1:5173").split(",") if o.strip()}

MAX_BODY_BYTES = 200 * 1024 * 1024  # ten minutes of 48 kHz stereo 16-bit is 115 MB
ANALYSES_PER_HOUR = 30
ALLOW_HEADERS = "Content-Type, ngrok-skip-browser-warning"

GET_ROUTES = (
    (re.compile(r"^/api/job/[a-f0-9]{12}$"), ENGINE),
    (re.compile(r"^/api/job/[a-f0-9]{12}/audio/(vocals|accompaniment)\.wav$"), ENGINE),
)
POST_ROUTES = {"/api/analyze": ENGINE, "/api/options": ENGINE, "/api/render": ENGINE, "/api/counter": COUNTER}

_recent: dict[str, deque] = defaultdict(deque)
_recent_lock = threading.Lock()


def allow_analysis(visitor: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    with _recent_lock:
        times = _recent[visitor]
        while times and now - times[0] > 3600:
            times.popleft()
        if len(times) >= ANALYSES_PER_HOUR:
            return False
        times.append(now)
        return True


def upstream_for(method: str, path: str) -> str | None:
    if method == "POST":
        return POST_ROUTES.get(path)
    return next((base for pattern, base in GET_ROUTES if pattern.match(path)), None)


class Gateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refuse(self, code: int, message: str) -> None:
        self.close_connection = True
        self._reply(code, b'{"error": "' + message.encode() + b'"}')

    def do_OPTIONS(self) -> None:
        if self.headers.get("Origin") not in ALLOWED_ORIGINS:
            return self._refuse(403, "origin not allowed")
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", ALLOW_HEADERS)
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _forward(self, method: str) -> None:
        url = urlparse(self.path)
        base = upstream_for(method, url.path)
        if self.headers.get("Origin") not in ALLOWED_ORIGINS:
            return self._refuse(403, "origin not allowed")
        if base is None:
            return self._refuse(404, "not found")
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY_BYTES:
            return self._refuse(413, "audio is too large")
        visitor = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        if url.path == "/api/analyze" and not allow_analysis(visitor):
            return self._refuse(429, "too many songs this hour, try again later")
        body = self.rfile.read(size) if method == "POST" else None
        target = base + url.path + (f"?{url.query}" if url.query else "")
        request = urllib.request.Request(target, data=body, method=method,
                                         headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            with urllib.request.urlopen(request, timeout=300) as r:
                self._reply(r.status, r.read(), r.headers.get("Content-Type", "application/octet-stream"))
        except urllib.error.HTTPError as e:
            self._reply(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
        except (urllib.error.URLError, TimeoutError):
            self._refuse(502, "the harmony engine is offline")

    def do_GET(self) -> None:
        self._forward("GET")

    def do_POST(self) -> None:
        self._forward("POST")

    def log_message(self, fmt: str, *args) -> None:
        pass


if __name__ == "__main__":
    print(f"Engine gateway on :{PORT} for {sorted(ALLOWED_ORIGINS)}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Gateway).serve_forever()
