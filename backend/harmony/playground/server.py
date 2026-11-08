"""Tiny local playground for the harmony engine. Standard library + numpy.

    python3 -m backend.harmony.playground.server        # then open http://localhost:8765

Pages
    /         record yourself, get harmony options, hear them (tones or your own voice)
    /manual   type a melody and chords by hand

API
    POST /api/transcribe?sr=16000&bpm=96&offset=2.5[&align=1]
         body: raw little-endian float32 mono samples
    POST /api/options      JSON {melody, novelty, palette, locks, voice, beats_per_bar, chord_every}
    POST /api/reharmonize  JSON {melody, chords, ...}   (manual page)
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from backend.harmony.reharmonize import (
    HARMONY_STYLES,
    LENSES,
    harmony_variations,
    parse_chord,
    reharmonize,
)
from backend.harmony.transcribe import transcribe

HERE = Path(__file__).parent
DEFAULT_PORT = 8765
MAX_AUDIO_SECONDS = 180


def _voicing(symbol: str) -> list[int]:
    """Simple playback voicing: bass root in octave 2, chord tones around middle C."""
    chord = parse_chord(symbol)
    if chord is None:
        return []
    return [36 + chord.root] + sorted(55 + ((pc - 55) % 12) for pc in chord.tones)


def _paths_payload(paths, melody, voice) -> list[dict]:
    out = []
    for p in paths:
        d = p.to_dict()
        for seg in d["timeline"]:
            seg["voicing"] = _voicing(seg["symbol"])
        d["harmony"] = harmony_variations(melody, p, voice)
        out.append(d)
    return out


def api_transcribe(query: dict, body: bytes) -> dict:
    sr = int(query.get("sr", ["16000"])[0])
    bpm = float(query.get("bpm", ["96"])[0])
    offset = float(query.get("offset", ["0"])[0])
    align = query.get("align", ["0"])[0] in ("1", "true")
    if not 8000 <= sr <= 96000 or not 30 <= bpm <= 260:
        raise ValueError("sr or bpm out of range")
    x = np.frombuffer(body, dtype="<f4")
    if x.size < sr * 0.3:
        raise ValueError("recording is too short")
    if x.size > sr * MAX_AUDIO_SECONDS:
        raise ValueError(f"recording is longer than {MAX_AUDIO_SECONDS}s")
    tr = transcribe(x, sr, bpm, offset, align_first_note=align)
    if not tr.notes:
        raise ValueError("didn't hear any notes. Sing a bit louder or closer to the mic?")
    return tr.to_dict()


def api_options(req: dict) -> dict:
    melody = req["melody"]
    if not melody:
        raise ValueError("melody is empty")
    bpb = int(req.get("beats_per_bar", 4))
    every = int(req.get("chord_every", 2)) or None
    # 1. A plain harmonization of what was sung: the starting point.
    base = reharmonize(melody, None, 0.0, beats_per_bar=bpb, chord_every=every)[0]
    # 2. Three options with distinct characters. The user's knobs stack on top
    #    of each, so "Adventure" and flavours move all three together.
    locks = {int(k): v for k, v in (req.get("locks") or {}).items()}
    user_palette = req.get("palette") or {}
    user_novelty = float(req.get("novelty", 0))
    chosen, names = [], []
    for name, palette, novelty in FLAVOURS:
        cands = reharmonize(
            melody, base.chords,
            novelty=max(novelty, user_novelty),
            palette={**palette, **user_palette},
            locks=locks or None,
            beats_per_bar=bpb,
            chord_every=every,
        )
        # Skip anything identical to an option we already have.
        fresh = [c for c in cands if all(c.symbols != o.symbols for o in chosen)]
        if fresh:
            chosen.append(fresh[0])
            names.append(name)
    payload = _paths_payload(chosen, melody, req["voice"])
    for d, name in zip(payload, names):
        d["name"] = name
    return {"base": base.symbols, "paths": payload}


# (name, lens palette, minimum novelty) for the three options.
FLAVOURS = (
    ("Plain", {}, 0.0),
    ("Lush", {"color": 1.0, "secondary": 0.7}, 0.3),
    ("Twist", {"borrowed": 1.0, "suspense": 0.5}, 0.55),  # parallel-mode chords: darker in major, brighter in minor
)


def api_reharmonize(req: dict) -> dict:
    melody, chords = req["melody"], req["chords"]
    if not melody:
        raise ValueError("melody is empty")
    if not chords:
        raise ValueError("chords are empty")
    locks = {int(k): v for k, v in (req.get("locks") or {}).items()}
    paths = reharmonize(
        melody, chords,
        novelty=float(req.get("novelty", 0)),
        palette=req.get("palette") or {},
        locks=locks or None,
        beats_per_bar=int(req.get("beats_per_bar", 4)),
    )
    return {"paths": _paths_payload(paths, melody, req["voice"])}


PAGES = {"/": "record.html", "/index.html": "record.html", "/manual": "manual.html", "/manual.html": "manual.html"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in PAGES:
            self._send(200, (HERE / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/meta":
            self._json(200, {"lenses": LENSES, "styles": HARMONY_STYLES})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        url = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            if url.path == "/api/transcribe":
                self._json(200, api_transcribe(parse_qs(url.query), body))
            elif url.path == "/api/options":
                self._json(200, api_options(json.loads(body or b"{}")))
            elif url.path == "/api/reharmonize":
                self._json(200, api_reharmonize(json.loads(body or b"{}")))
            else:
                self._send(404, b"not found", "text/plain")
        except (ValueError, KeyError, TypeError) as e:
            self._json(400, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # only log API calls
        if args and "POST" in str(args[0]):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Harmony playground: http://localhost:{port}  (manual mode: /manual)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
