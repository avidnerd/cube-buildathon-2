"""Tiny local playground for the reharmonizer. Standard library only.

    python3 -m backend.harmony.playground.server        # then open http://localhost:8765
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.harmony.reharmonize import (
    HARMONY_STYLES,
    LENSES,
    harmony_variations,
    parse_chord,
    reharmonize,
)

HERE = Path(__file__).parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


def _voicing(symbol: str) -> list[int]:
    """Simple playback voicing: bass root in octave 2, chord tones around middle C."""
    chord = parse_chord(symbol)
    if chord is None:
        return []
    bass = 36 + chord.root
    upper = sorted(55 + ((pc - 55) % 12) for pc in chord.tones)
    return [bass] + upper


def handle(req: dict) -> dict:
    melody = req["melody"]
    chords = req["chords"]
    if not melody:
        raise ValueError("melody is empty")
    if not chords:
        raise ValueError("chords are empty")
    locks = {int(k): v for k, v in (req.get("locks") or {}).items()}
    paths = reharmonize(
        melody,
        chords,
        novelty=float(req.get("novelty", 0)),
        palette=req.get("palette") or {},
        locks=locks or None,
        beats_per_bar=int(req.get("beats_per_bar", 4)),
    )
    out = []
    for p in paths:
        d = p.to_dict()
        for seg in d["timeline"]:
            seg["voicing"] = _voicing(seg["symbol"])
        d["harmony"] = harmony_variations(melody, p, req["voice"])
        out.append(d)
    return {"paths": out}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/meta":
            self._send(200, json.dumps({"lenses": LENSES, "styles": HARMONY_STYLES}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/reharmonize":
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            result = handle(json.loads(self.rfile.read(n) or b"{}"))
            self._send(200, json.dumps(result).encode(), "application/json")
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        if "POST" in (args[0] if args else ""):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Harmony playground: http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
