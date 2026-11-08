"""Chords for a bare sung melody, learned from real songs.

    infer(notes, key) -> list[Chord]       # one per note
    chord_at_fn(notes, chords) -> t -> Chord

A hidden Markov model over key-relative chords. Chords may change on any melody
note, so the changes land where the singer moves instead of on a fixed bar.
Probabilities (which notes sit over which chord at which length, which chord
follows which, how often a note of a given length brings a change) are counted
from the Lakh and Bach corpora; see training/train_chords.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from backend.harmony.reharmonize import Chord

QUALITY = {"maj": 0, "maj7": 0, "sus4": 0, "min": 1, "min7": 1, "7": 2, "dim": 3, "m7b5": 3}
QUALITY_NAMES = ("maj", "min", "7", "dim")
N_STATES = 48
CHANGE_BONUS = 1.0      # log-odds toward changing; set on held-out songs (corpus labels undercount changes)
MODEL_PATH = Path(__file__).with_name("chord_hmm.npz")
_model: dict | None = None


def state_of(ch: Chord, tonic: int) -> int:
    return ((ch.root - tonic) % 12) * 4 + QUALITY[ch.quality]


def length_class(seconds: float) -> int:
    return 0 if seconds < 0.25 else 1 if seconds < 0.75 else 2


def _load() -> dict:
    global _model
    if _model is None:
        with np.load(MODEL_PATH) as z:
            _model = {k: z[k] for k in z.files}
    return _model


def infer(notes: Sequence[dict], key: tuple[int, str]) -> list[Chord]:
    if not notes:
        return []
    tonic, mode = key
    m = _load()
    E, T, X, R = (m[f"{mode}_{k}"] for k in "ETXR")
    pitch = np.array([int(n["pitch"]) for n in notes])
    length = np.array([length_class(n["t1"] - n["t0"]) for n in notes])
    idx = np.arange(N_STATES)
    em = E[idx % 4, length[:, None], (pitch[:, None] - tonic - idx // 4) % 12]
    acc = em[0] + R.reshape(-1)
    back = []
    for i in range(1, len(notes)):
        tr = X[:, length[i], 1][:, None] + CHANGE_BONUS + T
        tr[idx, idx] = X[idx, length[i], 0]
        total = acc[:, None] + tr
        back.append(total.argmax(axis=0))
        acc = total.max(axis=0) + em[i]
    j = int(acc.argmax())
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    path.reverse()
    return [Chord((tonic + s // 4) % 12, QUALITY_NAMES[s % 4]) for s in path]


def chord_at_fn(notes: Sequence[dict], chords: Sequence[Chord]):
    """time (s) -> the chord of the note sounding then (or the last one begun)."""
    starts = np.array([float(n["t0"]) for n in notes])

    def at(t: float) -> Chord | None:
        if not len(starts):
            return None
        return chords[max(int(np.searchsorted(starts, t, side="right")) - 1, 0)]
    return at


def per_beat(at, beats: Sequence[float], n_beats: int) -> list[Chord | None]:
    """The chord at the middle of each beat, for the on-screen timeline."""
    b = np.asarray(beats, dtype=float)
    step = float(np.median(np.diff(b))) if len(b) > 1 else 1.0
    time = lambda i: b[i] if i < len(b) else b[-1] + (i - len(b) + 1) * step  # noqa: E731
    return [at(0.5 * (time(i) + time(i + 1))) for i in range(n_beats)]
