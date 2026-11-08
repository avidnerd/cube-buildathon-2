"""Tonal Interval Space (TIS) and tonal tension.

TIS (Bernardes et al., 2016): the weighted DFT (coefficients 1..6) of a
normalized pitch-class vector. Weights [2, 11, 17, 16, 19, 7] were fit to
perceptual consonance data, so

  * ||T(x)||          is a consonance score: longer = more consonant;
  * distances/angles  between vectors are tonal relatedness.

Tonal tension (Navarro-Caceres et al., 2020), as used in the team's JASS app:
for a chord following a previous chord in a key,
  d1  distance from the previous chord       (motion)
  d2  angle from the key                     (how far from home)
  d3  angle from the tonic/subdominant/dominant prototypes (function)
  c   dissonance = -||T||
each min-max normalized over all candidates, then weighted (paper Table 1).
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

from backend.harmony.reharmonize import CANDIDATES, MASKS, N_CAND, Chord

WEIGHTS = np.array([2.0, 11.0, 17.0, 16.0, 19.0, 7.0])
_K = np.arange(1, 7)[:, None]
_N = np.arange(12)[None, :]
_E = np.exp(-2j * np.pi * _K * _N / 12)  # (6, 12)

TENSION_WEIGHTS = {"d1": 0.78, "d2": 2.4, "d3": 1.4, "c": 3.7}
FUNCTION_WEIGHTS = {"tonic": 1.3, "subdominant": 1.0, "dominant": 1.2}
MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)


def tis(chroma: np.ndarray) -> np.ndarray:
    """(..., 12) non-negative weights -> (..., 6) complex TIS vectors."""
    c = np.asarray(chroma, dtype=np.float64)
    s = c.sum(axis=-1, keepdims=True)
    return (c / np.where(s > 0, s, 1.0)) @ _E.T * WEIGHTS


def chroma_of(pcs: Iterable[int], weights: Sequence[float] | None = None) -> np.ndarray:
    c = np.zeros(12)
    for i, p in enumerate(pcs):
        c[int(p) % 12] += 1.0 if weights is None else weights[i]
    return c


def consonance(chroma: np.ndarray) -> np.ndarray:
    """||T||: higher = more consonant. Works on (..., 12)."""
    return np.linalg.norm(tis(chroma), axis=-1)


def angle(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Angle between TIS vectors (rows of a vs. vector b), using |<a,b>|."""
    dots = np.abs(np.sum(a * np.conj(b), axis=-1))
    den = np.linalg.norm(a, axis=-1) * np.linalg.norm(b)
    return np.arccos(np.clip(dots / np.where(den > 0, den, 1.0), 0.0, 1.0))


def scale(tonic: int, mode: str) -> frozenset[int]:
    return frozenset((tonic + i) % 12 for i in (MAJOR if mode == "major" else MINOR))


def key_tis(tonic: int, mode: str) -> np.ndarray:
    return tis(chroma_of(scale(tonic, mode)))


# ---------------------------------------------------------------------------
# Tension
# ---------------------------------------------------------------------------

CAND_TIS = tis(MASKS)  # (84, 6)


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = np.nanmin(x), np.nanmax(x)
    return np.zeros_like(x) if hi - lo <= 0 else (x - lo) / (hi - lo)


def _prototypes(tonic: int, mode: str) -> dict[str, np.ndarray]:
    q = {"major": {0: "maj", 5: "maj", 7: "maj"}, "minor": {0: "min", 5: "min", 7: "min"}}[mode]
    names = {"tonic": 0, "subdominant": 5, "dominant": 7}
    return {f: CAND_TIS[Chord((tonic + d) % 12, q[d]).index] for f, d in names.items()}


def tension_after(prev: Chord | None, tonic: int, mode: str) -> np.ndarray:
    """Normalized tension (0..1) of every candidate chord following `prev`."""
    k = key_tis(tonic, mode)
    prev_t = CAND_TIS[prev.index] if prev is not None else CAND_TIS[Chord(tonic, "maj" if mode == "major" else "min").index]
    d1 = np.linalg.norm(CAND_TIS - prev_t[None, :], axis=1)
    d2 = angle(CAND_TIS, k)
    off = CAND_TIS - k[None, :]
    d3 = np.zeros(N_CAND)
    for f, proto in _prototypes(tonic, mode).items():
        d3 += FUNCTION_WEIGHTS[f] * angle(off, proto - k)
    d3 /= sum(FUNCTION_WEIGHTS.values())
    c = -np.linalg.norm(CAND_TIS, axis=1)
    raw = sum(TENSION_WEIGHTS[n] * _minmax(v) for n, v in (("d1", d1), ("d2", d2), ("d3", d3), ("c", c)))
    return _minmax(raw)


def progression_tension(chords: Sequence[Chord | None], tonic: int, mode: str) -> float:
    """Mean tension over the chord changes of a progression (0 calm .. 1 tense)."""
    seq = [c for c in chords if c is not None]
    changes = [(a, b) for a, b in zip(seq, seq[1:]) if a != b]
    if not changes:
        return float(tension_after(None, tonic, mode)[seq[0].index]) if seq else 0.0
    return float(np.mean([tension_after(a, tonic, mode)[b.index] for a, b in changes]))
