"""Measured dissonance: how a candidate harmony note would actually sound
against what is really playing (the band, measured from audio) and the lead.

Two complementary measures:

  sensory roughness  Plomp & Levelt (1965) in Sethares' (1993) form. Partials
                     close in frequency beat against each other; summing
                     a1*a2*(exp(-b1*s*df) - exp(-b2*s*df)) over every pair of
                     partials gives a roughness score in physical terms.
  tonal dissonance   -||TIS|| of the measured pitch-class content plus the
                     candidate (see tis.py). Roughness misses clashes between
                     notes in different octaves (a B above a low C is barely
                     "rough" but sounds wrong); TIS catches those.

Both are computed from the accompaniment's *measured* spectrum, so they're
right even when chord detection, key or time signature is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.harmony.beats import resample, stft_mag
from backend.harmony.tis import consonance

SR = 22050
N_FFT = 4096
HOP = 1024
N_PARTIALS = 6
PARTIAL_DECAY = 0.6
MAX_PEAKS = 24

# Sethares (1993) constants.
_DSTAR, _S1, _S2, _B1, _B2 = 0.24, 0.0207, 18.96, 3.51, 5.75


@dataclass
class Scene:
    """What's sounding during one sung note."""
    freqs: np.ndarray    # accompaniment spectral peaks + lead partials (Hz)
    amps: np.ndarray
    chroma: np.ndarray   # (12,) measured pitch-class energy (accompaniment + lead)
    lead_hz: float       # the lead's actual sung pitch (Hz)


def partials(f0: np.ndarray | float, amp: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Harmonic series of a voice-like tone. f0 (C,) -> freqs (C, N), amps (N,)."""
    k = np.arange(1, N_PARTIALS + 1)
    return np.asarray(f0, dtype=float)[..., None] * k, amp * PARTIAL_DECAY ** (k - 1)


def roughness(cand_hz: np.ndarray, scene_f: np.ndarray, scene_a: np.ndarray, amp: float = 0.8) -> np.ndarray:
    """Total roughness of each candidate tone (C,) against the scene."""
    cf, ca = partials(cand_hz, amp)                    # (C, N), (N,)
    F1 = cf[:, :, None]                                # (C, N, 1)
    F2 = scene_f[None, None, :]                        # (1, 1, P)
    fmin = np.minimum(F1, F2)
    df = np.abs(F1 - F2)
    s = _DSTAR / (_S1 * fmin + _S2)
    d = np.exp(-_B1 * s * df) - np.exp(-_B2 * s * df)
    return np.sum(ca[None, :, None] * scene_a[None, None, :] * d, axis=(1, 2))


def tonal_consonance(cand_pcs: np.ndarray, chroma: np.ndarray, weight: float = 1.5) -> np.ndarray:
    """TIS consonance of the measured chroma plus each candidate pitch class."""
    C = np.tile(chroma, (len(cand_pcs), 1))
    C[np.arange(len(cand_pcs)), cand_pcs % 12] += weight * max(chroma.max(), 1e-9)
    return consonance(C)


def candidate_dissonance(scene: Scene, cand_midi: np.ndarray, melody_midi: int,
                         w_rough: float = 1.0, w_tonal: float = 1.5) -> np.ndarray:
    """0 (best) .. w_rough + w_tonal (worst) per candidate, relative within this note.

    Candidates are placed relative to the lead's *sung* pitch, exactly as the
    re-pitched voice will sound (so a slightly flat singer is judged flat).
    """
    cand_hz = scene.lead_hz * 2.0 ** ((np.asarray(cand_midi) - melody_midi) / 12.0)
    r = roughness(cand_hz, scene.freqs, scene.amps)
    t = tonal_consonance(np.asarray(cand_midi), scene.chroma)
    rn = (r - r.min()) / (np.ptp(r) + 1e-9)
    tn = (t.max() - t) / (np.ptp(t) + 1e-9)
    return w_rough * rn + w_tonal * tn


# ---------------------------------------------------------------------------
# Scenes from real audio, or from chord symbols when there's no band
# ---------------------------------------------------------------------------

def _pc_weights(freqs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = (freqs >= 55) & (freqs <= 2100)
    midi = 69 + 12 * np.log2(np.where(ok, freqs, 440.0) / 440.0)
    near = np.round(midi)
    return (near.astype(int) % 12), np.clip(1 - 2 * np.abs(midi - near), 0, 1) * ok


class Listener:
    """Measures the accompaniment once; answers 'what's sounding during t0..t1'."""

    def __init__(self, accompaniment: np.ndarray, sr: int, lead_times: np.ndarray, lead_hz: np.ndarray):
        y = resample(np.asarray(accompaniment, dtype=np.float64), sr, SR)
        self.S = stft_mag(y, N_FFT, HOP)                          # (frames, bins)
        self.freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
        self.times = (np.arange(len(self.S)) * HOP + N_FFT / 2) / SR
        self.pc, self.pcw = _pc_weights(self.freqs)
        self.lead_times, self.lead_hz = lead_times, lead_hz
        self.level = float(np.percentile(self.S.max(axis=1), 90)) if len(self.S) else 1.0

    def lead_pitch(self, t0: float, t1: float, fallback_midi: int) -> float:
        sel = (self.lead_times >= t0) & (self.lead_times <= t1) & ~np.isnan(self.lead_hz)
        return float(np.median(self.lead_hz[sel])) if sel.any() else 440.0 * 2 ** ((fallback_midi - 69) / 12)

    def scene(self, t0: float, t1: float, melody_midi: int) -> Scene:
        lead = self.lead_pitch(t0, t1, melody_midi)
        idx = np.flatnonzero((self.times >= t0) & (self.times <= max(t1, t0 + HOP / SR)))
        if idx.size == 0:
            idx = np.array([int(np.clip(np.searchsorted(self.times, t0), 0, len(self.times) - 1))])
        spec = np.median(self.S[idx], axis=0)
        # Spectral peaks of the band.
        band = (self.freqs >= 50) & (self.freqs <= 5000)
        peaks = np.flatnonzero(band[1:-1] & (spec[1:-1] > spec[:-2]) & (spec[1:-1] >= spec[2:])) + 1
        peaks = peaks[spec[peaks] > 0.05 * max(spec.max(), 1e-12)]
        peaks = peaks[np.argsort(-spec[peaks])][:MAX_PEAKS]
        loud = min(1.0, float(spec.max()) / max(self.level, 1e-12))  # quiet band -> lead dominates
        bf = self.freqs[peaks]
        ba = 0.6 * loud * spec[peaks] / max(spec[peaks].max(), 1e-12) if peaks.size else np.zeros(0)
        lf, la = partials(lead, 1.0)
        chroma = np.zeros(12)
        np.add.at(chroma, self.pc, self.pcw * spec ** 0.6)
        if chroma.max() > 0:
            chroma = chroma / chroma.max() * loud
        chroma[int(round(69 + 12 * np.log2(lead / 440))) % 12] += 1.0
        return Scene(np.concatenate([bf, lf]), np.concatenate([ba, la]), chroma, lead)


def chord_scene(chord_tones, melody_midi: int, lead_hz: float | None = None) -> Scene:
    """A scene for when there's no band: the chord as a soft pad plus the lead."""
    lead = lead_hz or 440.0 * 2 ** ((melody_midi - 69) / 12)
    fs, as_ = [], []
    chroma = np.zeros(12)
    for pc in chord_tones:
        m = 48 + (pc - 48) % 12  # chord tones around C3..B3
        f, a = partials(440.0 * 2 ** ((m - 69) / 12), 0.5)
        fs.append(f)
        as_.append(a)
        chroma[pc % 12] += 1.0
    lf, la = partials(lead, 1.0)
    fs.append(lf)
    as_.append(la)
    chroma[melody_midi % 12] += 1.0
    return Scene(np.concatenate(fs), np.concatenate(as_), chroma, lead)
