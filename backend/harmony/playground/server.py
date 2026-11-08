"""Local studio for the harmony engine.

    python3 -m backend.harmony.playground.server        # then open http://localhost:8765

Pages
    /         the studio: upload a song or record yourself -> harmonies -> karaoke
    /manual   type a melody and chords by hand

API
    POST /api/analyze?sr=44100&channels=2&source=upload|mic[&bpm=96&offset=2.5&bpb=4&lyrics=1]
         body: little-endian int16 PCM, interleaved. Returns {"job": id}.
    GET  /api/job/<id>                    progress + result
    GET  /api/job/<id>/audio/<stem>.wav   vocals | accompaniment
    POST /api/options      {melody, chords?, novelty, palette, locks, voice, beats_per_bar, chord_every}
    POST /api/render       {job, melody, part} -> WAV: the lead's voice singing the part
    POST /api/lyrics       {notes, text}  -> notes with typed lyrics + lines
    POST /api/reharmonize  {melody, chords, ...}   (manual page)
"""

from __future__ import annotations

import io
import json
import sys
import threading
import traceback
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from backend.harmony.beats import BeatGrid, resample, track_beats
from backend.harmony.chords import detect_chords
from backend.harmony.harmonizer import ARRANGEMENTS, plan_parts, render_part
from backend.harmony.lyrics import (
    attach_lyrics,
    hear_words,
    lines_from_notes,
    lyric_for_harmony,
    lyrics_from_text,
)
from backend.harmony.reharmonize import (
    HARMONY_STYLES,
    LENSES,
    harmony_variations,
    parse_chord,
    reharmonize,
)
from backend.harmony.tis import progression_tension
from backend.harmony.transcribe import transcribe

HERE = Path(__file__).parent
DEFAULT_PORT = 8765
MAX_AUDIO_SECONDS = 600
PITCH_SR = 16000

# (name, lens palette, minimum novelty) for the three options.
FLAVOURS = (
    ("Plain", {}, 0.0),
    ("Lush", {"color": 1.0, "secondary": 0.7}, 0.3),
    ("Twist", {"borrowed": 1.0, "suspense": 0.5}, 0.55),  # parallel-mode chords: darker in major, brighter in minor
)


# ---------------------------------------------------------------------------
# Analysis jobs
# ---------------------------------------------------------------------------

STAGES = {
    "upload": ["Separating voice from music", "Finding the beat", "Transcribing the melody",
               "Hearing the chords", "Reading the lyrics"],
    "mic": ["Transcribing the melody", "Reading the lyrics"],
}

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_models = threading.Semaphore(1)  # one heavy analysis at a time


def _new_job(source: str) -> dict:
    job = {"id": uuid.uuid4().hex[:12], "stages": list(STAGES[source]), "stage": None, "done_stages": [],
           "done": False, "error": None, "result": None, "audio": {}}
    with _jobs_lock:
        _jobs[job["id"]] = job
        if len(_jobs) > 20:  # keep memory bounded
            for old in list(_jobs)[:-20]:
                _jobs.pop(old, None)
    return job


def _stage(job: dict, name: str | None) -> None:
    if job["stage"] and job["stage"] not in job["done_stages"]:
        job["done_stages"].append(job["stage"])
    job["stage"] = name


def analyze(job: dict, x: np.ndarray, sr: int, source: str, bpm: float | None, offset: float,
            bpb: int, want_lyrics: bool) -> None:
    """x: (channels, n) float32."""
    with _models:
        mono = x.mean(axis=0)
        has_music, music_ratio, accomp, chords, beat_grid = False, 0.0, None, None, None
        vocals, vsr = mono, sr

        if source == "upload":
            from backend.harmony.separate import separate
            _stage(job, "Separating voice from music")
            stems = separate(x, sr)
            has_music, music_ratio = stems.has_music, stems.music_ratio
            if has_music:
                vocals, vsr, accomp = stems.vocals, stems.sr, stems.accompaniment
                job["audio"]["vocals"] = (vocals, vsr)
                job["audio"]["accompaniment"] = (accomp, vsr)
                _stage(job, "Finding the beat")
                beat_grid = track_beats(accomp, vsr, bpm_hint=bpm, beats_per_bar=bpb)
            else:
                job["stages"] = [s for s in job["stages"] if s not in ("Finding the beat", "Hearing the chords")]

        _stage(job, "Transcribing the melody")
        v16 = resample(vocals, vsr, PITCH_SR)
        if beat_grid is not None:
            tr = transcribe(v16, PITCH_SR, beat_grid=beat_grid)
        elif source == "mic":
            tr = transcribe(v16, PITCH_SR, bpm or 90, offset)
        else:
            tr = transcribe(v16, PITCH_SR, bpm or 90, align_first_note=True)
        if not tr.notes:
            raise ValueError("didn't hear a melody. Is there singing in this audio?")
        job["audio"]["vocals"] = (vocals, vsr)          # source for harmony in the lead's voice
        job["f0"] = (tr.times, tr.f0_hz())
        result = tr.to_dict()
        n_beats = int(np.ceil(max(n["start"] + n["duration"] for n in tr.notes))) + 1

        if accomp is not None:
            _stage(job, "Hearing the chords")
            found = detect_chords(accomp, vsr, beat_grid, n_beats)
            chords = [c.name if c else "N.C." for c in found]

        notes = tr.notes
        words = []
        if want_lyrics:
            _stage(job, "Reading the lyrics")
            try:
                words = hear_words(vocals, vsr)
                notes = attach_lyrics(notes, words)
            except Exception as e:  # lyrics are optional; never lose the analysis over them
                traceback.print_exc()
                result["lyrics_error"] = f"{type(e).__name__}: {e}"
        notes = [dict(n, lyric=n.get("lyric", ""), word_start=n.get("word_start", False)) for n in notes]

        result.update({
            "notes": notes,
            "lines": lines_from_notes(notes),
            "words": [{"text": w.text, "t0": round(w.t0, 3), "t1": round(w.t1, 3)} for w in words],
            "has_music": has_music,
            "music_ratio": round(music_ratio, 3),
            "chords": chords,
            "beats_per_bar": bpb,
            "stems": sorted(job["audio"]),
        })
        _stage(job, None)
        job["result"] = result


def _run_job(job: dict, *args) -> None:
    try:
        analyze(job, *args)
    except Exception as e:
        traceback.print_exc()
        job["error"] = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
    finally:
        job["done"] = True


def api_analyze(query: dict, body: bytes, background: bool = True) -> dict:
    def q(k, d=None):
        return query.get(k, [d])[0]

    sr = int(q("sr", "44100"))
    ch = int(q("channels", "1"))
    source = q("source", "upload")
    bpm = float(q("bpm")) if q("bpm") else None
    offset = float(q("offset", "0"))
    bpb = int(q("bpb", "4"))
    lyrics = q("lyrics", "1") in ("1", "true")
    if source not in STAGES or not 8000 <= sr <= 96000 or ch not in (1, 2):
        raise ValueError("bad source, sample rate or channel count")
    pcm = np.frombuffer(body, dtype="<i2")
    if pcm.size < sr * ch * 0.5:
        raise ValueError("audio is too short")
    if pcm.size > sr * ch * MAX_AUDIO_SECONDS:
        raise ValueError(f"audio is longer than {MAX_AUDIO_SECONDS // 60} minutes")
    x = pcm[: pcm.size // ch * ch].reshape(-1, ch).T.astype(np.float32) / 32768.0
    job = _new_job(source)
    args = (job, x, sr, source, bpm, offset, bpb, lyrics)
    if background:
        threading.Thread(target=_run_job, args=args, daemon=True).start()
    else:
        _run_job(*args)
    return {"job": job["id"], "stages": job["stages"]}


def api_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise KeyError("no such job")
    return {k: job[k] for k in ("id", "stages", "stage", "done_stages", "done", "error", "result")}


def wav_bytes(x: np.ndarray, sr: int) -> bytes:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    y = x / peak * 0.95 if peak > 1.0 else x
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Harmony options
# ---------------------------------------------------------------------------


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
        for style in d["harmony"].values():
            for part in ("third_above", "sixth_below"):
                style[part] = lyric_for_harmony(style[part], melody)
        out.append(d)
    return out


def _chord_at_fn(chords: list, beats: list[float] | None):
    """time (s) -> Chord, from per-beat chords and the song's beat times."""
    parsed = [parse_chord(c) if not hasattr(c, "tones") else c for c in chords]
    grid = BeatGrid(np.asarray(beats, dtype=float)) if beats and len(beats) >= 2 else None

    def at(t: float):
        if not parsed:
            return None
        b = int(np.floor(grid.to_beats(t))) if grid is not None else 0
        return parsed[min(max(b, 0), len(parsed) - 1)]
    return at


def _studio_payload(paths, melody, beats, voice: dict) -> list[dict]:
    from backend.harmony.reharmonize import _parse_voice_profile

    rng = _parse_voice_profile(voice)
    timed = [n for n in melody if "t0" in n and "t1" in n]
    out = []
    for p in paths:
        d = p.to_dict()
        for seg in d["timeline"]:
            seg["voicing"] = _voicing(seg["symbol"])
        chord_at = _chord_at_fn(p.chords, beats)
        d["parts"] = {arr: plan_parts(timed, chord_at, p.key, rng, arr) for arr in ARRANGEMENTS}
        d["tension"] = round(progression_tension(p.chords, *p.key), 3)
        out.append(d)
    return out


def api_options(req: dict) -> dict:
    melody = req["melody"]
    if not melody:
        raise ValueError("melody is empty")
    bpb = int(req.get("beats_per_bar", 4))
    every = int(req.get("chord_every", 2)) or None
    detected = req.get("chords")
    if detected:
        # The song's own chords are the starting point.
        base_chords, base_symbols = detected, list(detected)
    else:
        # A bare voice: the plain harmonization its melody implies.
        base = reharmonize(melody, None, 0.0, beats_per_bar=bpb, chord_every=every)[0]
        base_chords, base_symbols = base.chords, base.symbols

    locks = {int(k): v for k, v in (req.get("locks") or {}).items()}
    user_palette = req.get("palette") or {}
    user_novelty = float(req.get("novelty", 0))
    chosen, names = [], []
    for name, palette, novelty in FLAVOURS:
        option_locks = dict(locks)
        if detected and name == "Plain":
            # A real song's Plain option is exactly its own chords: the reference
            # everything else is compared to. The user's own locks still win.
            option_locks = {t: c for t, c in enumerate(detected) if c != "N.C."} | locks
        cands = reharmonize(
            melody, base_chords,
            novelty=max(novelty, user_novelty),
            palette={**palette, **user_palette},
            locks=option_locks or None,
            beats_per_bar=bpb,
            chord_every=every,
        )
        fresh = [c for c in cands if all(c.symbols != o.symbols for o in chosen)]
        if fresh:
            chosen.append(fresh[0])
            names.append(name)
    payload = _studio_payload(chosen, melody, req.get("beats"), req["voice"])
    for d, name in zip(payload, names):
        d["name"] = name
    arrangements = {k: {"label": v["label"], "parts": [{"id": pid, "label": lbl} for pid, lbl, _, _ in v["parts"]]}
                    for k, v in ARRANGEMENTS.items()}
    return {"base": base_symbols, "paths": payload, "arrangements": arrangements}


_render_cache: dict[tuple, bytes] = {}


def api_render(req: dict) -> bytes:
    """The lead's own voice re-pitched onto a harmony part (WAV bytes)."""
    job = _jobs.get(req["job"])
    if job is None or "f0" not in job or "vocals" not in job["audio"]:
        raise KeyError("no vocals for this job")
    melody, part = req["melody"], req["part"]
    if len(melody) != len(part):
        raise ValueError("melody and part must have the same notes")
    key = (req["job"], tuple((round(m["t0"], 3), m["pitch"], h["pitch"]) for m, h in zip(melody, part)))
    if key not in _render_cache:
        vocals, sr = job["audio"]["vocals"]
        times, hz = job["f0"]
        y = render_part(vocals, sr, times, hz, melody, part)
        if len(_render_cache) > 64:
            _render_cache.clear()
        _render_cache[key] = wav_bytes(y.astype(np.float32), sr)
    return _render_cache[key]


def api_lyrics(req: dict) -> dict:
    notes = lyrics_from_text(req["notes"], req.get("text", ""))
    return {"notes": notes, "lines": lines_from_notes(notes)}


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


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

PAGES = {"/": "studio.html", "/index.html": "studio.html", "/manual": "manual.html", "/manual.html": "manual.html"}


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
        parts = path.strip("/").split("/")
        try:
            if path in PAGES:
                self._send(200, (HERE / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/meta":
                self._json(200, {"lenses": LENSES, "styles": HARMONY_STYLES})
            elif len(parts) == 3 and parts[:2] == ["api", "job"]:
                self._json(200, api_job(parts[2]))
            elif len(parts) == 5 and parts[:2] == ["api", "job"] and parts[3] == "audio":
                job = _jobs.get(parts[2])
                stem = parts[4].removesuffix(".wav")
                if job is None or stem not in job["audio"]:
                    raise KeyError("no such audio")
                self._send(200, wav_bytes(*job["audio"][stem]), "audio/wav")
            else:
                self._send(404, b"not found", "text/plain")
        except KeyError as e:
            self._json(404, {"error": str(e)})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            if url.path == "/api/analyze":
                self._json(200, api_analyze(parse_qs(url.query), body))
            elif url.path == "/api/options":
                self._json(200, api_options(json.loads(body or b"{}")))
            elif url.path == "/api/render":
                self._send(200, api_render(json.loads(body or b"{}")), "audio/wav")
            elif url.path == "/api/lyrics":
                self._json(200, api_lyrics(json.loads(body or b"{}")))
            elif url.path == "/api/reharmonize":
                self._json(200, api_reharmonize(json.loads(body or b"{}")))
            else:
                self._send(404, b"not found", "text/plain")
        except (ValueError, KeyError, TypeError) as e:
            self._json(400, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # only log API writes
        if args and "POST" in str(args[0]):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Harmony studio: http://localhost:{port}  (manual mode: /manual)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
