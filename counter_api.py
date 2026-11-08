"""counter_api.py — JSON API that connects the browser app (src/) to the
counter-melody generator (counter.py).

The browser records and transcribes the melody, then POSTs it here using the
shared note model (see src/noteModel.js):

    POST /api/counter
    {
      "notes": [{"midi": 60, "start": 0, "duration": 1}, ...],   # times in beats
      "key": "C" | "F#m" | ... | null,    # same key names as src/analyzeMelody.js; null = detect
      "meter": "4/4" | "3/4" | "6/8",
      "bpm": 120,
      "voice": "soprano" | "alto" | "tenor" | "bass"
    }

and gets the counter-melody back in the same format:

    {"counter": [{"midi": 67, "start": 0, "duration": 2}, ...], "clef": "treble", ...}

    python counter_api.py            # serves on http://127.0.0.1:8001 (Vite proxies /api here)

Uses only the standard library.
"""
from __future__ import annotations

import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import counter as C
import lily
from lily import KeySig, Meter, Note, Score

DEFAULT_PORT = 8001
MAX_NOTES = 4096
METERS = {"4/4": (4, 4), "3/4": (3, 4), "6/8": (6, 8)}
# Python's clef names -> ABC clef names used by src/melodyToAbc.js
ABC_CLEFS = {"treble": "treble", "treble_8": "treble-8", "bass": "bass"}
_QUALITY_NAMES = {"": "", "m": "m", "dim": "°", "aug": "+", "7": "7"}
_ACC = {1: "#", 2: "##", -1: "b", -2: "bb", 0: ""}


def key_from_name(name: str) -> KeySig:
    """'C', 'F#', 'Db', 'Am', 'Ebm' (the names in src/analyzeMelody.js KEYS) -> KeySig."""
    text = name.strip()
    mode = "major"
    if text.endswith("m"):
        mode, text = "minor", text[:-1]
    if not text or text[0].upper() not in "CDEFGAB" or text[1:] not in ("", "#", "b"):
        raise ValueError(f"Unknown key '{name}'.")
    step = "CDEFGAB".index(text[0].upper())
    alter = {"": 0, "#": 1, "b": -1}[text[1:]]
    return KeySig(step, alter, mode)


def notes_from_json(raw) -> list[Note]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("Send at least one melody note.")
    if len(raw) > MAX_NOTES:
        raise ValueError(f"Use at most {MAX_NOTES} notes.")
    notes = []
    for i, n in enumerate(raw, 1):
        if not isinstance(n, dict):
            raise ValueError(f"Note {i} must be an object.")
        midi, start, dur = n.get("midi"), n.get("start"), n.get("duration")
        if not isinstance(midi, int) or isinstance(midi, bool) or not 0 <= midi <= 127:
            raise ValueError(f"Note {i}: midi must be an integer from 0 to 127.")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, dur)) \
                or start < 0 or dur <= 0:
            raise ValueError(f"Note {i}: start must be >= 0 and duration > 0 (beats).")
        notes.append(Note(midi, float(start), float(dur)))
    return notes


def score_from_payload(payload: dict) -> Score:
    meter = str(payload.get("meter", "4/4"))
    if meter not in METERS:
        raise ValueError("Meter must be 4/4, 3/4 or 6/8.")
    key = payload.get("key")
    bpm = payload.get("bpm", 100)
    if not isinstance(bpm, (int, float)) or not 20 <= bpm <= 300:
        raise ValueError("Tempo must be between 20 and 300 BPM.")
    return Score(notes=notes_from_json(payload.get("notes")),
                 key=key_from_name(str(key)) if key else None,
                 meter=Meter(*METERS[meter]), tempo_bpm=int(round(bpm)))


def _notes_json(notes: list[Note]) -> list[dict]:
    return [{"midi": n.midi, "start": n.start, "duration": n.dur}
            for n in notes if n.midi is not None]


def api_counter(payload: dict) -> dict:
    """Generate a counter-melody for a JSON melody. Raises ValueError on bad input."""
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object.")
    voice = str(payload.get("voice", "alto"))
    if voice not in C.VOICES:
        raise ValueError(f"Unknown voice '{voice}'.")
    score = score_from_payload(payload)
    res = C.generate(score, voice)
    table = lily._spelling(res.key)
    chords = []
    for s in res.segs:
        st, alt = table[s.chord.root]
        chords.append({"start": s.start, "end": s.end,
                       "name": lily.STEP_NAMES[st].upper() + _ACC.get(alt, "")
                       + _QUALITY_NAMES.get(s.chord.quality, "")})
    return {
        "counter": _notes_json(res.counter),
        "melody": _notes_json(res.melody),      # the melody as the generator saw it (cleaned)
        "voice": res.voice.name,
        "clef": ABC_CLEFS.get(res.voice.clef, "treble"),
        "key": res.key.name(),
        "style": res.style,
        "echo": res.echo,
        "fallback": res.fallback,
        "quality": round(res.quality, 2),
        "independence": round(C.independence(res.melody, res.counter), 2),
        "chords": chords,
        "warnings": C._grouped(res.warnings),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/counter":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 2_000_000:
                raise ValueError("Request too large.")
            self._send(200, api_counter(json.loads(self.rfile.read(length) or b"{}")))
        except (ValueError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # keep the server alive on unexpected input
            self._send(500, {"error": f"Could not write a counter-melody ({type(e).__name__}: {e})"})

    def log_message(self, fmt: str, *args) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Counter-melody JSON API for the web app")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Counter-melody API on http://127.0.0.1:{args.port}/api/counter  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
