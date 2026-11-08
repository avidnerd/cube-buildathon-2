"""placeholder_ui/server.py — PLACEHOLDER UI, FOR TESTING ONLY. Not the real app.

A throwaway local web page for trying the generator by hand: enter a melody on a
piano, send it as LilyPond text to /api/counter, and see/play the result.

    python placeholder_ui/server.py          # then open http://localhost:8000
    python placeholder_ui/server.py --port 9000

Uses only the standard library.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))       # import counter.py / lily.py from the repo root

import counter as C  # noqa: E402
import lily  # noqa: E402

WEB_DIR = HERE
_QUALITY_NAMES = {"": "", "m": "m", "dim": "°", "aug": "+", "7": "7"}
_ACC = {1: "#", 2: "##", -1: "b", -2: "bb", 0: ""}


def _notes_json(notes: list[lily.Note]) -> list[dict]:
    return [{"midi": n.midi, "start": n.start, "dur": n.dur} for n in notes if n.midi is not None]


def api_counter(payload: dict) -> dict:
    """Run the generator on LilyPond text. Raises ValueError on bad input."""
    text = str(payload.get("lily", "")).strip()
    voice = str(payload.get("voice", "alto"))
    if not text:
        raise ValueError("Enter a melody first.")
    if voice not in C.VOICES:
        raise ValueError(f"Unknown voice '{voice}'.")
    score = lily.parse(text)
    if not any(n.midi is not None for n in score.notes):
        raise ValueError("The melody has no notes.")
    res = C.generate(score, voice)
    ly, bare = C.render(res, score, "melody")
    table = lily._spelling(res.key)
    chords = []
    for s in res.segs:
        st, alt = table[s.chord.root]
        chords.append({"start": s.start, "end": s.end,
                       "name": lily.STEP_NAMES[st].upper() + _ACC.get(alt, "")
                       + _QUALITY_NAMES.get(s.chord.quality, "")})
    return {
        "ly": ly,
        "bare": bare,
        "key": res.key.name(),
        "key_detected": score.key is None,
        "key_confidence": round(res.key_conf, 2),
        "style": res.style,
        "quality": res.quality,
        "fallback": res.fallback,
        "echo": res.echo,
        "voice": res.voice.name,
        "side": res.ctx.side,
        "independence": round(C.independence(res.melody, res.counter), 2),
        "tempo_qpm": score.tempo_qpm,
        "bar_len": res.meter.bar_len,
        "pickup": res.meter.pickup,
        "total": res.ctx.total_end,
        "melody": _notes_json(res.melody),
        "counter": _notes_json(res.counter),
        "chords": chords,
        "warnings": C._grouped(res.warnings),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            with open(os.path.join(WEB_DIR, "index.html"), "rb") as fh:
                self._send(200, fh.read(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/counter":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            body, code = api_counter(payload), 200
        except ValueError as e:
            body, code = {"error": str(e)}, 400
        except Exception as e:  # keep the UI alive on unexpected input
            body, code = {"error": f"Could not process that melody ({type(e).__name__}: {e})"}, 500
        self._send(code, json.dumps(body).encode(), "application/json")

    def log_message(self, fmt: str, *args) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Counter-melody web UI")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"PLACEHOLDER test UI (not the real app) running at http://localhost:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
