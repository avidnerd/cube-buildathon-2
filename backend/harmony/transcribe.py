"""Sung audio -> melody notes on a beat grid. numpy only.

    transcribe(samples, sr, bpm, offset=0.0) -> Transcription

Pipeline:
  1. YIN pitch tracking (de Cheveigné & Kawahara 2002), vectorized with FFTs.
  2. Loudness gate + short median filter to kill octave blips and breaths.
  3. Global tuning correction: singers are rarely at A=440, so find the
     average cents offset and remove it before rounding to semitones.
  4. Segmentation into notes: split on silence, on a sustained pitch change
     (hysteresis, so vibrato and scoops don't fragment notes), and on energy
     dips (re-articulated repeated notes like "twin-kle twin-kle").
  5. Quantize onsets and offsets to a beat grid, given the tempo the user
     recorded at and where beat 0 is in the recording (after the count-in).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from backend.harmony.beats import BeatGrid

FMIN = 70.0     # Hz, below a low bass voice
FMAX = 1100.0   # Hz, above a soprano C6; also rejects a 2 kHz metronome click
FRAME = 1024
HOP_S = 0.01    # 10 ms
YIN_THRESHOLD = 0.15
GATE_DB = -38.0          # frames quieter than this (re: loudest) are unvoiced
MIN_NOTE_S = 0.07
SPLIT_SEMITONES = 0.75   # pitch must move this far...
SPLIT_FRAMES = 5         # ...for this many frames to start a new note
DIP_RATIO = 0.55         # energy dip below this fraction of neighbours = re-articulation


@dataclass
class RawNote:
    t0: float
    t1: float
    pitch: int          # rounded, tuning-corrected MIDI
    midi: float         # median sung pitch (tuning-corrected, unrounded)


@dataclass
class Transcription:
    notes: list[dict]                 # {"pitch", "start", "duration", "t0", "t1"} start/duration in beats
    raw: list[RawNote]
    tuning_cents: float
    times: np.ndarray                 # frame times (s)
    midi_track: np.ndarray            # per-frame MIDI (tuning-corrected), nan = unvoiced
    sung_range: tuple[int, int] | None = None
    meta: dict = field(default_factory=dict)

    def f0_hz(self) -> np.ndarray:
        """The sung pitch track in Hz (tuning restored), nan where unvoiced."""
        return 440.0 * 2 ** ((self.midi_track + self.tuning_cents / 100.0 - 69) / 12)

    def to_dict(self, track_step: int = 2) -> dict:
        track = [
            [round(float(t), 3), None if np.isnan(m) else round(float(m), 2)]
            for t, m in zip(self.times[::track_step], self.midi_track[::track_step])
        ]
        return {
            "notes": self.notes,
            "tuning_cents": round(self.tuning_cents, 1),
            "range": None if self.sung_range is None else {"low": self.sung_range[0], "high": self.sung_range[1]},
            "track": track,
            **self.meta,
        }


# ---------------------------------------------------------------------------
# 1. YIN
# ---------------------------------------------------------------------------


def yin(x: np.ndarray, sr: int, fmin: float = FMIN, fmax: float = FMAX,
        frame: int = FRAME, hop: int | None = None, threshold: float = YIN_THRESHOLD):
    """Returns (times, f0 Hz with nan for unvoiced, aperiodicity 0..1, rms)."""
    hop = hop or max(1, int(round(HOP_S * sr)))
    x = np.asarray(x, dtype=np.float64)
    if len(x) < frame:
        x = np.pad(x, (0, frame - len(x)))
    tau_min = max(2, int(sr / fmax))
    tau_max = min(int(sr / fmin), frame // 2 - 1)
    w = frame - tau_max  # integration window

    frames = np.lib.stride_tricks.sliding_window_view(x, frame)[::hop]
    n_frames = frames.shape[0]

    # Difference function d(tau) = e0 + e_tau - 2 r(tau), all via FFT/cumsum.
    n_fft = 1 << int(np.ceil(np.log2(frame + w)))
    A = np.fft.rfft(frames[:, :w], n_fft)
    B = np.fft.rfft(frames, n_fft)
    r = np.fft.irfft(np.conj(A) * B, n_fft)[:, : tau_max + 1]
    sq = np.concatenate([np.zeros((n_frames, 1)), np.cumsum(frames ** 2, axis=1)], axis=1)
    e0 = sq[:, w][:, None]
    taus = np.arange(tau_max + 1)
    e_tau = sq[:, taus + w] - sq[:, taus]
    d = np.maximum(e0 + e_tau - 2 * r, 0.0)
    d[:, 0] = 0.0

    # Cumulative mean normalized difference.
    cum = np.cumsum(d[:, 1:], axis=1)
    cmnd = np.ones_like(d)
    cmnd[:, 1:] = d[:, 1:] * taus[1:] / np.maximum(cum, 1e-12)

    f0 = np.full(n_frames, np.nan)
    aper = np.ones(n_frames)
    seg = cmnd[:, tau_min: tau_max + 1]
    below = seg < threshold
    for i in range(n_frames):
        idx = np.flatnonzero(below[i])
        if idx.size:
            j = idx[0]
            while j + 1 < seg.shape[1] and seg[i, j + 1] < seg[i, j]:
                j += 1  # walk down to the local minimum
        else:
            j = int(np.argmin(seg[i]))
            if seg[i, j] > 0.35:
                aper[i] = float(seg[i, j])
                continue
        tau = j + tau_min
        # Parabolic interpolation for sub-sample period.
        if 1 <= tau < tau_max:
            a, b, c = cmnd[i, tau - 1], cmnd[i, tau], cmnd[i, tau + 1]
            den = a - 2 * b + c
            shift = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
        else:
            shift = 0.0
        f0[i] = sr / (tau + float(np.clip(shift, -1, 1)))
        aper[i] = float(cmnd[i, tau])

    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    times = (np.arange(n_frames) * hop + frame / 2) / sr
    return times, f0, aper, rms


# ---------------------------------------------------------------------------
# 2-4. Notes
# ---------------------------------------------------------------------------


def _median_filter_nan(m: np.ndarray, k: int = 5) -> np.ndarray:
    out = m.copy()
    h = k // 2
    for i in np.flatnonzero(~np.isnan(m)):
        win = m[max(0, i - h): i + h + 1]
        win = win[~np.isnan(win)]
        out[i] = np.median(win)
    return out


def _tuning_offset(m: np.ndarray) -> float:
    """Circular mean of the fractional semitone, in semitones (-0.5..0.5)."""
    v = m[~np.isnan(m)]
    if v.size == 0:
        return 0.0
    ang = 2 * np.pi * v
    return float(np.angle(np.mean(np.exp(1j * ang))) / (2 * np.pi))


ORNAMENT_S = 0.13      # shorter than this and touching a neighbour = scoop/slide/wobble
ORNAMENT_SEMITONES = 3


def absorb_ornaments(notes: list[RawNote]) -> list[RawNote]:
    """Fold scoops, slides and vibrato wobbles into the note they belong to.

    A singer sliding up into "I" produces E-F-E-F in 0.1 s chunks; as notes,
    each would get its own harmony note and the harmony would twitch. A run of
    consecutive short fragments is folded, as a whole, into the real note it
    leads into (or trails off from). The harmony then holds one note and,
    being the lead's voice re-pitched, still follows the scoop naturally.
    """
    def short(n):
        return n.t1 - n.t0 < ORNAMENT_S

    def touching(a, b):
        return b.t0 - a.t1 < 0.06

    out = list(notes)
    i = 0
    while i < len(out):
        if not short(out[i]):
            i += 1
            continue
        j = i  # extend the run of touching short fragments
        while j + 1 < len(out) and short(out[j + 1]) and touching(out[j], out[j + 1]):
            j += 1
        run = out[i: j + 1]
        near = lambda n: min(abs(n.pitch - r.pitch) for r in run) <= ORNAMENT_SEMITONES  # noqa: E731
        nxt = out[j + 1] if j + 1 < len(out) and touching(out[j], out[j + 1]) and near(out[j + 1]) else None
        prv = out[i - 1] if i > 0 and touching(out[i - 1], out[i]) and near(out[i - 1]) else None
        host = nxt if nxt is not None and (prv is None or nxt.t1 - nxt.t0 >= prv.t1 - prv.t0) else prv
        if host is None:
            i = j + 1
            continue
        merged = RawNote(min(host.t0, run[0].t0), max(host.t1, run[-1].t1), host.pitch, host.midi)
        if host is nxt:
            out[i: j + 2] = [merged]
        else:
            out[i - 1: j + 1] = [merged]
            i -= 1
        i += 1
    return out


# ---------------------------------------------------------------------------
# Drift-aware, key-aware note naming
# ---------------------------------------------------------------------------

_SCALES = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10)}
DRIFT_GRID = np.round(np.arange(-1.2, 1.2001, 0.05), 3)  # semitones: singers drift up to ~a semitone over a phrase
DRIFT_STEP = 0.12      # typical tuning change between consecutive notes
PITCH_SIGMA = 0.35     # per-note intonation scatter: real singers overshoot leaps by up to ~a semitone
OUT_OF_KEY = 4.0       # cost of a chromatic note (allowed when clearly sung)
DRIFT_PRIOR = 0.05     # tie-breaker: prefer drift near the average tuning when the key evidence is thin


def name_notes(midi: Sequence[float], dur: Sequence[float]) -> tuple[list[int], tuple[int, str], np.ndarray]:
    """Each note = scale pitch + slowly drifting tuning, found jointly (Viterbi).

    A global tuning offset fails for real singers, who drift (often flat on a
    descending line): a note 0.5 semitone off can't be rounded reliably. Here
    every key is tried; for each, the best path of (pitch, drift) explains the
    sung pitches closely, prefers in-key notes, and lets the drift move only
    slowly. Returns (pitches, key, drift per note).
    """
    m = np.asarray(midi, dtype=float)
    w = np.sqrt(np.clip(np.asarray(dur, dtype=float), 0.05, 1.0) / 0.25)  # longer notes count more
    n = len(m)
    if n == 0:
        return [], (0, "major"), np.zeros(0)
    D = DRIFT_GRID
    trans = ((D[:, None] - D[None, :]) / DRIFT_STEP) ** 2  # (d_prev, d)
    best = None
    for mode, sc in _SCALES.items():
        for tonic in range(12):
            inkey = {(tonic + i) % 12 for i in sc}
            Q = [np.arange(int(np.floor(v)) - 1, int(np.ceil(v)) + 2) for v in m]  # candidate pitches
            def emit(i):
                q = Q[i][:, None]
                e = w[i] * ((m[i] - q - D[None, :]) / PITCH_SIGMA) ** 2
                e = e + OUT_OF_KEY * np.array([[0.0 if int(p) % 12 in inkey else 1.0] for p in Q[i]])
                # Drift wanders around the singer's average tuning, not a whole
                # semitone away from it for the whole song (that's just the same
                # tune named a semitone off).
                e = e + DRIFT_PRIOR * (D[None, :] / 0.5) ** 2
                return e  # (|Q|, |D|)
            acc = emit(0)                       # cost per (q, d)
            back = []
            for i in range(1, n):
                prev_best_d = acc.min(axis=0)     # best over previous q for each previous d
                arg_q = acc.argmin(axis=0)
                tot = prev_best_d[:, None] + trans  # (d_prev, d)
                bd = tot.argmin(axis=0)
                acc = emit(i) + tot.min(axis=0)[None, :]
                back.append((arg_q, bd))
            cost = float(acc.min())
            if best is None or cost < best[0]:
                qi, di = np.unravel_index(int(acc.argmin()), acc.shape)
                path_q, path_d = [int(Q[n - 1][qi])], [float(D[di])]
                for i in range(n - 1, 0, -1):
                    arg_q, bd = back[i - 1]
                    di = int(bd[di])
                    qi = int(arg_q[di])
                    path_q.append(int(Q[i - 1][qi]))
                    path_d.append(float(D[di]))
                best = (cost, path_q[::-1], (tonic, mode), np.array(path_d[::-1]))
    return best[1], best[2], best[3]


def split_level_changes(notes: list[RawNote], times: np.ndarray, midi: np.ndarray,
                        min_side: float = 0.12, min_step: float = 0.7) -> list[RawNote]:
    """Split a note where the pitch settles at a new level (a slid step like
    'Fly-me'), even if it got there smoothly. Both sides must be held and steady."""
    out: list[RawNote] = []
    for n in notes:
        sel = np.flatnonzero((times >= n.t0) & (times <= n.t1) & ~np.isnan(midi))
        v = midi[sel]
        best = None
        for k in range(len(v)):
            a, b = v[:k], v[k:]
            if len(a) < 2 or len(b) < 2:
                continue
            if times[sel[k]] - n.t0 < min_side or n.t1 - times[sel[k]] < min_side:
                continue
            ma, mb = np.median(a[len(a) // 3:]), np.median(b[: max(1, 2 * len(b) // 3)])
            if abs(mb - ma) < min_step:
                continue
            if np.std(a[len(a) // 3:]) > 0.35 or np.std(b[: max(2, 2 * len(b) // 3)]) > 0.35:
                continue
            gain = abs(mb - ma)
            if best is None or gain > best[0]:
                best = (gain, k, ma, mb)
        if best is None:
            out.append(n)
            continue
        _, k, ma, mb = best
        t = float(times[sel[k]])
        out.append(RawNote(n.t0, t, int(round(ma)), float(ma)))
        out.append(RawNote(t, n.t1, int(round(mb)), float(mb)))
    return out


def _short_rms(x: np.ndarray, sr: int, times: np.ndarray, win_s: float = 0.016) -> np.ndarray:
    """Loudness on a short window at each frame centre (pitch frames are too long
    to see the brief dip between re-articulated notes)."""
    w = max(8, int(win_s * sr))
    sq = np.concatenate([[0.0], np.cumsum(x ** 2)])
    c = np.clip((times * sr).astype(int), 0, len(x))
    a = np.clip(c - w // 2, 0, len(x))
    b = np.clip(c + w // 2, 0, len(x))
    return np.sqrt((sq[b] - sq[a]) / np.maximum(b - a, 1))


def _segment(times: np.ndarray, midi: np.ndarray, rms: np.ndarray) -> list[RawNote]:
    voiced = ~np.isnan(midi)
    hop = float(times[1] - times[0]) if len(times) > 1 else HOP_S
    smooth_rms = np.convolve(rms, np.ones(3) / 3, mode="same")
    look = max(3, int(0.12 / hop))

    # Candidate split points from energy dips (re-articulations).
    dips = set()
    for i in range(1, len(rms) - 1):
        v = smooth_rms[i]
        if v <= smooth_rms[i - 1] and v <= smooth_rms[i + 1]:
            before = smooth_rms[max(0, i - look): i].max(initial=0)
            after = smooth_rms[i + 1: i + 1 + look].max(initial=0)
            if v < DIP_RATIO * min(before, after):
                dips.add(i)

    notes: list[RawNote] = []
    cur: list[int] = []

    def close():
        if not cur:
            return
        # Pitch frames are long and see a note early; refine the edges to
        # where short-window loudness crosses half the note's level.
        level = 0.5 * float(np.median(rms[cur]))
        loud_idx = [j for j in cur if rms[j] >= level] or cur
        t0, t1 = times[loud_idx[0]] - hop / 2, times[loud_idx[-1]] + hop / 2
        if t1 - t0 >= MIN_NOTE_S:
            vals = midi[cur]
            core = vals[len(vals) // 5: len(vals) - len(vals) // 5] if len(vals) >= 5 else vals  # skip scoops
            med = float(np.median(core))
            notes.append(RawNote(float(t0), float(t1), int(round(med)), med))

    gap = 0
    split_next = False       # an energy dip fell inside a short unvoiced gap
    pending: list[int] = []  # frames that disagree with the current note
    for i in range(len(midi)):
        if not voiced[i]:
            gap += 1
            split_next |= i in dips
            if gap >= 3:
                cur.extend(pending)
                pending = []
                close()
                cur = []
            continue
        gap = 0
        if (i in dips or split_next) and cur:
            split_next = False
            cur.extend(pending)
            pending = []
            close()
            cur = [i]
            continue
        split_next = False
        if not cur:
            cur = [i]
            continue
        ref = np.median(midi[cur[-15:]])
        if abs(midi[i] - ref) >= SPLIT_SEMITONES:
            pending.append(i)
            if len(pending) >= SPLIT_FRAMES:
                close()
                cur = pending
                pending = []
        else:
            cur.extend(pending)
            pending = []
            cur.append(i)
    cur.extend(pending)
    close()
    return notes


# ---------------------------------------------------------------------------
# 5. Beat grid
# ---------------------------------------------------------------------------


# Snap preference: (grid, tolerance in beats). People mostly land on beats,
# then off-beats, then sixteenths; a note 0.15 beats late is "on the beat,
# sung late", not "a sixteenth after the beat".
SNAP_LEVELS = ((1.0, 0.2), (0.5, 0.13))


def _snap(b: float, grid: float) -> float:
    for g, tol in SNAP_LEVELS:
        if g >= grid:
            q = round(b / g) * g
            if abs(b - q) <= tol:
                return q
    return round(b / grid) * grid


def estimate_lag(raw: list[RawNote], beats: BeatGrid) -> float:
    """Constant lateness of onsets vs. the beat, in beats: input latency plus habit.

    Median residual to the nearest beat, using only onsets that are close to
    a beat (others are off-beat notes and say nothing about lag).
    """
    res = []
    for n in raw:
        b = beats.to_beats(n.t0)
        r = b - round(b)
        if abs(r) < 0.2:
            res.append(r)
    return float(np.median(res)) if len(res) >= 3 else 0.0


def quantize(raw: list[RawNote], beats: BeatGrid, grid: float = 0.25) -> list[dict]:
    """Every sung note, with its real timing (t0/t1, seconds) and a beat
    position (start/duration) used only to line it up with the chords.

    Nothing is dropped or merged: harmony parts are built note-for-note on the
    real timing, so the beat values are labels, never playback times.
    """
    out: list[dict] = []
    for n in raw:
        s = _snap(beats.to_beats(n.t0), grid)
        e = _snap(beats.to_beats(n.t1), grid)
        if e <= 0:
            continue  # sung during the count-in
        s = max(s, 0.0)
        e = max(e, s + grid)
        out.append({"pitch": n.pitch, "start": s, "duration": e - s, "t0": round(n.t0, 3), "t1": round(n.t1, 3)})
    return out


def transcribe(samples: np.ndarray, sr: int, bpm: float | None = None, offset: float = 0.0,
               grid: float = 0.25, align_first_note: bool = False,
               beat_grid: BeatGrid | None = None) -> Transcription:
    """samples: mono float audio (ideally an isolated voice).

    Timing, one of:
      beat_grid          beats tracked from the song (sung timing kept as-is)
      bpm + offset       a click-track recording; offset = seconds where beat 0 is.
                         Constant lateness is measured and removed.
      align_first_note   with bpm: beat 0 = the first sung note (no count-in)
      neither            tempo and beats detected from the sung notes themselves
    """
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 0:
        x = x / peak

    times, f0, aper, rms = yin(x, sr)
    loud = rms > max(1e-4, rms.max(initial=0) * 10 ** (GATE_DB / 20)) if rms.size else rms
    f0 = np.where(loud & (aper < 0.35), f0, np.nan)
    midi = 69 + 12 * np.log2(f0 / 440.0)
    midi = _median_filter_nan(midi, 5)

    off = _tuning_offset(midi)
    midi = midi - off

    raw = absorb_ornaments(_segment(times, midi, _short_rms(x, sr, times)))
    raw = split_level_changes(raw, times, midi)
    # Name the notes with drift + key awareness instead of plain rounding.
    names, _key, drift = name_notes([n.midi for n in raw], [n.t1 - n.t0 for n in raw])
    raw = [RawNote(n.t0, n.t1, q, n.midi) for n, q in zip(raw, names)]
    lag_ms = 0.0
    if beat_grid is None and bpm is None:
        # No click, no band: find the tempo from the sung notes themselves.
        from backend.harmony.beats import beats_from_onsets

        beat_grid = beats_from_onsets(np.array([n.t0 for n in raw]),
                                      np.sqrt([max(n.t1 - n.t0, 0.05) for n in raw]),
                                      end=float(len(x)) / sr) if raw else None
        if beat_grid is None:
            beat_grid = BeatGrid.constant(90.0, 0.0)
    if beat_grid is None:
        if align_first_note and raw:
            offset = raw[0].t0
        beats = BeatGrid.constant(bpm, offset)
        lag = estimate_lag(raw, beats) * 60.0 / bpm
        beats = beats.shifted(lag)
        lag_ms = lag * 1000
    else:
        beats = beat_grid
    notes = quantize(raw, beats, grid)
    sung = (min(n["pitch"] for n in notes), max(n["pitch"] for n in notes)) if notes else None
    n_beats = int(np.ceil(max((n["start"] + n["duration"] for n in notes), default=0))) + 2
    return Transcription(notes, raw, off * 100, times, midi, sung, {
        "bpm": round(beats.bpm, 2),
        "beat0": round(float(beats.times[0]), 4),
        "beats": beats.trimmed(n_beats),
        "lag_ms": round(lag_ms, 1),
        "grid": grid,
    })
