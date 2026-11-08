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

import numpy as np

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


def estimate_lag(raw: list[RawNote], bpm: float, offset: float) -> float:
    """Constant lateness (s) of onsets vs. the beat: input latency plus habit.

    Median residual to the nearest beat, using only onsets that are close to
    a beat (others are off-beat notes and say nothing about lag).
    """
    spb = 60.0 / bpm
    res = []
    for n in raw:
        b = (n.t0 - offset) / spb
        r = b - round(b)
        if abs(r) < 0.2:
            res.append(r)
    if len(res) < 3:
        return 0.0
    return float(np.median(res)) * spb


def quantize(raw: list[RawNote], bpm: float, offset: float, grid: float = 0.25,
             legato_gap: float = 0.25, compensate_lag: bool = True) -> list[dict]:
    spb = 60.0 / bpm
    if compensate_lag:
        offset = offset + estimate_lag(raw, bpm, offset)
    out: list[dict] = []
    for n in raw:
        s = _snap((n.t0 - offset) / spb, grid)
        e = _snap((n.t1 - offset) / spb, grid)
        if e <= 0:
            continue  # sung during the count-in
        s = max(s, 0.0)
        e = max(e, s + grid)
        if out and s < out[-1]["start"] + out[-1]["duration"]:
            prev = out[-1]
            if s <= prev["start"]:          # collided on the grid: keep the longer note
                if e - s > prev["duration"]:
                    out[-1] = {"pitch": n.pitch, "start": prev["start"], "duration": e - prev["start"],
                               "t0": round(n.t0, 3), "t1": round(n.t1, 3)}
                continue
            prev["duration"] = s - prev["start"]
        out.append({"pitch": n.pitch, "start": s, "duration": e - s, "t0": round(n.t0, 3), "t1": round(n.t1, 3)})
    # Close small gaps so harmony parts sound legato rather than clipped.
    for a, b in zip(out, out[1:]):
        gap = b["start"] - (a["start"] + a["duration"])
        if 0 < gap <= legato_gap:
            a["duration"] += gap
    return out


def transcribe(samples: np.ndarray, sr: int, bpm: float, offset: float = 0.0,
               grid: float = 0.25, align_first_note: bool = False) -> Transcription:
    """samples: mono float audio. offset: seconds into the audio where beat 0 is.

    align_first_note: ignore `offset` and put beat 0 at the first sung note
    (for uploaded audio recorded without a count-in).
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

    raw = _segment(times, midi, _short_rms(x, sr, times))
    if align_first_note and raw:
        offset = raw[0].t0
    lag = estimate_lag(raw, bpm, offset)
    beat0 = offset + lag  # where beat 0 actually is in this audio
    notes = quantize(raw, bpm, beat0, grid, compensate_lag=False)
    sung = (min(n["pitch"] for n in notes), max(n["pitch"] for n in notes)) if notes else None
    return Transcription(notes, raw, off * 100, times, midi, sung,
                         {"bpm": bpm, "beat0": round(beat0, 4), "lag_ms": round(lag * 1000, 1), "grid": grid})
