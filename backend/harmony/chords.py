"""Chord detection from the accompaniment: decompose the music into its 12
pitch-class energies (chroma), beat by beat, and match chord templates.

    detect_chords(samples, sr, grid, n_beats) -> list[Chord | None]   # one per beat

Why it works on the *accompaniment*: with the voice removed, what's left is
mostly the harmony itself (pads, guitar, piano, bass). Each beat's chroma is a
12-vector "fingerprint" of which notes are sounding; the chord whose template
best matches it (plus who's in the bass) wins, with Viterbi smoothing so a
passing note doesn't flip the chord for one beat.
"""

from __future__ import annotations

import numpy as np

from backend.harmony.beats import BeatGrid, resample, stft_mag
from backend.harmony.reharmonize import CANDIDATES, N_CAND, Chord

SR = 22050
N_FFT = 4096
HOP = 1024
FPS = SR / HOP

# Templates include the strongest overtones of each chord tone (3rd harmonic =
# a fifth up, 5th harmonic = a major third up), since real instruments put
# energy there too.
_OVERTONES = ((0, 1.0), (7, 0.33), (4, 0.2))
QUALITY_PRIOR = {"maj": 0.0, "min": 0.0, "7": -0.02, "maj7": -0.03, "min7": -0.02, "dim": -0.08, "sus4": -0.07, "m7b5": -0.05}
W_EMISSION = 6.0
W_BASS = 0.6
CHANGE_COST = 0.7
SILENCE_RATIO = 0.08


def _templates() -> np.ndarray:
    T = np.zeros((N_CAND, 12))
    for i, c in enumerate(CANDIDATES):
        for pc in c.tones:
            for iv, w in _OVERTONES:
                T[i, (pc + iv) % 12] += w
    return T / np.linalg.norm(T, axis=1, keepdims=True)


TEMPLATES = _templates()
ROOTS = np.array([c.root for c in CANDIDATES])
PRIOR = np.array([QUALITY_PRIOR[c.quality] for c in CANDIDATES])


def _pc_matrix(fmin: float, fmax: float) -> np.ndarray:
    freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
    P = np.zeros((len(freqs), 12))
    ok = (freqs >= fmin) & (freqs <= fmax)
    midi = 69 + 12 * np.log2(np.where(ok, freqs, 440.0) / 440.0)
    nearest = np.round(midi)
    w = np.clip(1 - 2 * np.abs(midi - nearest), 0, 1) * ok
    P[np.arange(len(freqs)), nearest.astype(int) % 12] = w
    return P


P_FULL = _pc_matrix(55.0, 2100.0)
P_BASS = _pc_matrix(40.0, 260.0)


def chroma(samples: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """(chroma, bass_chroma), each (frames, 12), at FPS frames per second."""
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    S = stft_mag(resample(x, sr, SR), N_FFT, HOP) ** 0.6  # compress so loud bass doesn't drown the rest
    return S @ P_FULL, S @ P_BASS


def beat_chroma(ch: np.ndarray, grid: BeatGrid, n_beats: int) -> np.ndarray:
    """Median chroma per beat (median ignores drum hits and passing notes)."""
    out = np.zeros((n_beats, 12))
    centers = (np.arange(len(ch)) + N_FFT / HOP / 2) / FPS
    for b in range(n_beats):
        t0, t1 = grid.to_time(b), grid.to_time(b + 1)
        idx = np.flatnonzero((centers >= t0) & (centers < t1))
        if idx.size:
            out[b] = np.median(ch[idx], axis=0)
    return out


def detect_chords(samples: np.ndarray, sr: int, grid: BeatGrid, n_beats: int) -> list[Chord | None]:
    full, bass = chroma(samples, sr)
    C = beat_chroma(full, grid, n_beats)
    B = beat_chroma(bass, grid, n_beats)
    energy = C.sum(axis=1)
    silent = energy < SILENCE_RATIO * (np.median(energy[energy > 0]) if (energy > 0).any() else 1.0)

    Cn = C / np.maximum(np.linalg.norm(C, axis=1, keepdims=True), 1e-9)
    Bn = B / np.maximum(B.max(axis=1, keepdims=True), 1e-9)
    E = W_EMISSION * (Cn @ TEMPLATES.T + PRIOR[None, :]) + W_BASS * Bn[:, ROOTS]
    E[silent] = 0.0

    # One-best Viterbi with a flat cost for changing chord.
    trans = np.where(np.eye(N_CAND, dtype=bool), 0.0, -CHANGE_COST)
    score = E[0].copy()
    back = np.zeros((n_beats, N_CAND), dtype=int)
    for t in range(1, n_beats):
        cand = score[:, None] + trans
        back[t] = np.argmax(cand, axis=0)
        score = cand[back[t], np.arange(N_CAND)] + E[t]
    s = int(np.argmax(score))
    path = [s]
    for t in range(n_beats - 1, 0, -1):
        s = int(back[t, s])
        path.append(s)
    path.reverse()
    return [None if silent[t] else CANDIDATES[i] for t, i in enumerate(path)]
