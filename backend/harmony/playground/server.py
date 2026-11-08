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
from backend.harmony.dissonance import Listener, chord_scene
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
        elif bpm is not None:  # an explicit tempo (API callers)
            tr = transcribe(v16, PITCH_SR, bpm, offset, align_first_note=source != "mic")
        else:  # voice only: tempo detected from the singing
            tr = transcribe(v16, PITCH_SR)
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


def _listener(job_id: str | None) -> tuple[Listener | None, tuple | None]:
    """(listener over the real accompaniment or None, lead f0 track or None) for a job."""
    job = _jobs.get(job_id or "")
    if job is None or "f0" not in job:
        return None, None
    if "accompaniment" in job["audio"] and "listener" not in job:
        acc, sr = job["audio"]["accompaniment"]
        job["listener"] = Listener(acc, sr, *job["f0"])
    return job.get("listener"), job["f0"]


def _lead_hz(f0, n) -> float | None:
    if f0 is None:
        return None
    times, hz = f0
    sel = (times >= n["t0"]) & (times <= n["t1"]) & ~np.isnan(hz)
    return float(np.median(hz[sel])) if sel.any() else None


def _studio_payload(paths, names, melody, beats, voice: dict, job_id: str | None = None,
                    every: int | None = None, phase: int = 0, voice_chord_at=None) -> list[dict]:
    from backend.harmony.reharmonize import _parse_voice_profile

    rng = _parse_voice_profile(voice)
    timed = [n for n in melody if "t0" in n and "t1" in n]
    listener, f0 = _listener(job_id)
    personal = _song_personal(timed)
    out = []
    for p, name in zip(paths, names):
        d = p.to_dict()
        for seg in d["timeline"]:
            seg["voicing"] = _voicing(seg["symbol"])
        chord_at = _chord_at_fn(p.chords, beats)
        by_note = voice_chord_at is not None and name == "Plain"
        if by_note:
            chord_at = voice_chord_at     # changes on the sung notes, not the beat grid
            d["note_chords"] = [chord_at(0.5 * (n["t0"] + n["t1"])).name for n in timed]
        if listener is not None and name == "Plain":
            # Sung over the real band: measure what's actually sounding.
            scene_for = lambda n: listener.scene(n["t0"], n["t1"], int(n["pitch"]))  # noqa: E731
            d["backing"] = "band"
        else:
            # New chords (or no band): the option's chords as a pad + the lead's real pitch.
            def scene_for(n, _at=chord_at):
                ch = _at(0.5 * (n["t0"] + n["t1"]))
                tones = list(ch.tones) if ch is not None else []
                return chord_scene(tones, int(n["pitch"]), _lead_hz(f0, n))
            d["backing"] = "pad"
        d["parts"] = {arr: plan_parts(timed, chord_at, p.key, rng, arr, scene_for, personal=personal) for arr in ARRANGEMENTS}
        if listener is None and name == "Plain" and beats and not by_note:
            # A cappella: the chords were only a guess; the voices now spell the
            # real ones. Re-label (and re-voice the pad) so nothing contradicts.
            from backend.harmony.harmonizer import implied_chords
            from backend.harmony.reharmonize import Reharmonization

            cl = d["parts"]["classic"]
            chords = implied_chords(timed, [cl["high"], cl["low"]], beats, len(p.chords), p.key, p.chords,
                                    every=every or 1, phase=phase)
            q = Reharmonization(chords, p.score, p.beat_len, [], p.original, p.key).to_dict()
            for k in ("chords", "romans", "timeline"):
                d[k] = q[k]
            for seg in d["timeline"]:
                seg["voicing"] = _voicing(seg["symbol"])
            p = Reharmonization(chords, p.score, p.beat_len, [], p.original, p.key)
        d["tension"] = round(progression_tension(p.chords, *p.key), 3)
        out.append(d)
    return out


def downbeat_phase(melody: list[dict], beats_per_bar: int) -> int:
    """Which beat (mod the bar) is beat 1, from the melody alone: long, stressed
    notes ("moon", "stars") tend to start on the downbeat."""
    w = np.zeros(beats_per_bar)
    for n in melody:
        if n.get("start") is None:
            continue
        b = float(n["start"])
        if abs(b - round(b)) < 0.2:
            w[int(round(b)) % beats_per_bar] += max(float(n.get("duration", 1.0)), 0.25) ** 1.5
    return int(np.argmax(w)) if w.any() else 0


def api_options(req: dict) -> dict:
    melody = req["melody"]
    if not melody:
        raise ValueError("melody is empty")
    bpb = int(req.get("beats_per_bar", 4))
    ce = req.get("chord_every", "bar")
    every = bpb if ce in ("bar", None) else (int(ce) or None)   # default: one chord per bar
    phase, song_key = 0, None
    if every and every > 1 and not req.get("chords"):
        # The key estimate decides the key (fit can't overrule it: minor chords
        # "explain" major melodies too easily). Fit only places beat 1.
        song_key = reharmonize(melody, None, 0.0, beats_per_bar=bpb, chord_every=every, n_paths=1)[0].key
        fits = [(reharmonize(melody, None, 0.0, beats_per_bar=bpb, chord_every=every, phase=p, n_paths=1, key=song_key)[0].score, p)
                for p in range(every)]
        phase = max(fits)[1]
    detected = req.get("chords")
    if detected:
        # The song's own chords are the starting point.
        base_chords, base_symbols = detected, list(detected)
    else:
        # A bare voice: the plain harmonization its melody implies.
        base = reharmonize(melody, None, 0.0, beats_per_bar=bpb, chord_every=every, phase=phase, key=song_key)[0]
        base_chords, base_symbols = base.chords, base.symbols

    voice_chord_at = None
    timed = [n for n in melody if "t0" in n and "t1" in n]
    if not detected and req.get("beats") and len(timed) == len(melody) and _listener(req.get("job"))[0] is None:
        # A cappella: chords from the model trained on real songs.
        from backend.harmony import melody_chords as mc

        voice_chord_at = mc.chord_at_fn(timed, mc.infer(timed, song_key or base.key))
        base_chords = mc.per_beat(voice_chord_at, req["beats"], len(base_chords))
        base_symbols = [c.name for c in base_chords]

    locks = {int(k): v for k, v in (req.get("locks") or {}).items()}
    user_palette = req.get("palette") or {}
    user_novelty = float(req.get("novelty", 0))
    chosen, names = [], []
    for name, palette, novelty in FLAVOURS:
        option_locks = dict(locks)
        if name == "Plain" and voice_chord_at is not None:
            option_locks = dict(enumerate(base_chords)) | locks
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
            phase=phase,
            key=song_key,
        )
        fresh = [c for c in cands if all(c.symbols != o.symbols for o in chosen)]
        if fresh:
            chosen.append(fresh[0])
            names.append(name)
    payload = _studio_payload(chosen, names, melody, req.get("beats"), req["voice"], req.get("job"), every, phase, voice_chord_at)
    for d, name in zip(payload, names):
        d["name"] = name
    arrangements = {k: {"label": v["label"], "parts": [{"id": pid, "label": lbl} for pid, lbl, _, _ in v["parts"]]}
                    for k, v in ARRANGEMENTS.items()}
    from backend.harmony import neural

    return {"base": base_symbols, "paths": payload, "arrangements": arrangements,
            "song": neural.song_fingerprint([n for n in melody if "t0" in n])}


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
        from backend.harmony.audio_fx import denoise, polish

        vocals, sr = job["audio"]["vocals"]
        if "vocals_clean" not in job:  # once per song: room hiss out before shifting
            job["vocals_clean"] = denoise(vocals, sr)
        times, hz = job["f0"]
        tuning = (job.get("result") or {}).get("tuning_cents", 0.0)
        y = polish(render_part(job["vocals_clean"], sr, times, hz, melody, part, tuning_cents=tuning), sr)
        if len(_render_cache) > 64:
            _render_cache.clear()
        _render_cache[key] = wav_bytes(y.astype(np.float32), sr)
    return _render_cache[key]


FEEDBACK_DIR = HERE.parents[2] / "listen"


def _personal_path(song: str) -> Path:
    return FEEDBACK_DIR / f"personal-{song}.json"


def _song_personal(notes) -> dict | None:
    """This song's adjustments learned from the user's fixes, if any."""
    from backend.harmony import neural

    from backend.harmony.harmonizer import USE_LEARNED_MODEL

    if not notes or not USE_LEARNED_MODEL or neural.base_model() is None:
        return None
    p = _personal_path(neural.song_fingerprint(notes))
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except ValueError:
        return None


def _examples_from_feedback(fb: dict) -> list:
    """Training examples from one feedback file: every lyric line the user
    touched (or all lines, for a fully labelled example), per labelled part."""
    from backend.harmony import neural
    from backend.harmony.harmonizer import ARRANGEMENTS as ARR, NET_WINDOW, make_example
    from backend.harmony.reharmonize import NOTE_NAMES

    notes, parts = fb["notes"], fb["parts"]
    if str(fb.get("arrangement", "")).startswith("satb"):
        return []   # four-part voicing is rule-based; fixes there don't train the two-part model
    arr = ARR[fb.get("arrangement", "classic")]
    key = (NOTE_NAMES.index(fb["key"]["tonic"]), fb["key"]["mode"])
    chord_at = _chord_at_fn(fb["chords"], fb["beats"])
    lo = min(n["pitch"] for n in notes)
    hi = max(n["pitch"] for n in notes)
    voice = (lo - 5, hi + 5, lo - 3, hi + 3)
    labelled = fb.get("labelled_parts") or list(parts)
    changed_idx = {c["index"] for c in fb.get("changes", [])}
    lines = fb.get("lines") or [{"notes": list(range(len(notes)))}]
    if not fb.get("fully_labelled"):
        lines = [ln for ln in lines if changed_idx & set(ln["notes"])]

    def scene_for(n):
        ch = chord_at(0.5 * (n["t0"] + n["t1"]))
        return chord_scene(list(ch.tones) if ch is not None else [], int(n["pitch"]))

    out = []
    done: dict[str, list[int]] = {}
    for pid, _, side, target in arr["parts"]:
        if pid in labelled:
            for ln in lines:
                idx = ln["notes"]
                mel = [notes[i] for i in idx]
                gold = [int(parts[pid][i]["pitch"]) for i in idx]
                others = [[v[i] for i in idx] for v in done.values()]
                out.append(make_example(mel, chord_at, key, voice, side, target, gold, scene_for, others,
                                        max_iv=NET_WINDOW if neural.base_model() is not None else None))
        done[pid] = [int(h["pitch"]) for h in parts[pid]]
    return out


def learn_style(song: str | None = None) -> dict:
    """Refit from the user's fixes. With the learned base model, fixes are a
    per-song layer (they only reshape that song); otherwise the old rule style."""
    from backend.harmony import neural
    from backend.harmony.harmonizer import DEFAULT_WEIGHTS, agreement, fit_style, save_style

    files = sorted(p for p in FEEDBACK_DIR.glob("feedback-*.json") if p.name != "feedback-latest.json")
    examples = []
    for f in files:
        try:
            fb = json.loads(f.read_text())
            if song is not None and neural.song_fingerprint(fb["notes"]) != song:
                continue
            examples += _examples_from_feedback(fb)
        except (KeyError, ValueError, IndexError) as e:
            sys.stderr.write(f"skipping {f.name}: {e}\n")
    if not examples:
        return {"examples": 0}
    n_notes = sum(len(e.gold) for e in examples)
    net = neural.base_model()
    if net is not None and song is not None:
        # General rules come from the base model (thousands of songs); the
        # user's fixes are this song's arrangement choices, applied to it only.
        before = neural.personal_agreement(examples, net, None)
        personal = neural.fit_personal(examples, net)
        personal["note"] = f"your fixes for this song ({n_notes} notes)"
        _personal_path(song).write_text(json.dumps(personal, indent=1))
        after = neural.personal_agreement(examples, net, personal)
    else:
        before = agreement(examples, DEFAULT_WEIGHTS)
        w = fit_style(examples)
        save_style(w, note=f"learned from {len(files)} feedback file(s), {n_notes} labelled notes")
        after = agreement(examples, w)
    return {"examples": len(examples), "notes": n_notes, "before": round(before, 3), "after": round(after, 3)}


def api_feedback(req: dict) -> dict:
    """Save the user's hand-corrected harmony, then relearn the style from all of it."""
    import time

    FEEDBACK_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    data = json.dumps(req, indent=1)
    (FEEDBACK_DIR / f"feedback-{stamp}.json").write_text(data)
    (FEEDBACK_DIR / "feedback-latest.json").write_text(data)
    from backend.harmony import neural

    song = neural.song_fingerprint(req["notes"])
    return {"saved": f"listen/feedback-{stamp}.json", "changes": len(req.get("changes", [])), "song": song,
            "learned": learn_style(song)}


def api_style(song: str | None = None, reset: bool = False) -> dict:
    from backend.harmony import neural
    from backend.harmony.harmonizer import STYLE_PATH

    targets = [_personal_path(song)] if song else []
    if reset:
        for p in targets + [STYLE_PATH, neural.PERSONAL_PATH]:
            if p.exists():
                p.unlink()
    from backend.harmony.harmonizer import USE_LEARNED_MODEL

    net = neural.base_model() if USE_LEARNED_MODEL else None
    base = (f"harmony learned from {net.meta.get('songs', '?')} real arrangements" if net is not None else "hand-weighted harmony rules")
    if song and _personal_path(song).exists():
        note = json.loads(_personal_path(song).read_text()).get("note", "")
        return {"learned": True, "note": f"{base} + {note}"}
    return {"learned": False, "note": base}


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
            elif path == "/api/style":
                self._json(200, api_style(parse_qs(urlparse(self.path).query).get("song", [None])[0]))
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
            elif url.path == "/api/style/reset":
                self._json(200, api_style(parse_qs(url.query).get("song", [None])[0], reset=True))
            elif url.path == "/api/feedback":
                self._json(200, api_feedback(json.loads(body or b"{}")))
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
