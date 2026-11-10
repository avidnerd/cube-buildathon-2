"""Clean-up and finishing for the re-pitched harmony voices.

    denoise(x, sr)   spectral noise gate: learns the room hiss from the quietest
                     moments and removes it (smoothed, so no "watery" artifacts)
    polish(x, sr)    backing-vocal finishing chain: low-cut, gentle high-cut
                     (softens grainy top end), light compression, short reverb

Applied to the voice *before* pitch shifting (denoise: so the shifter doesn't
warble the hiss) and to each harmony part *after* (polish).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, fftconvolve, istft, sosfiltfilt, stft


def denoise(x: np.ndarray, sr: int, strength: float = 1.6, floor: float = 0.12) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if len(x) < sr // 4:
        return x
    nper, hop = 1024, 256
    _, _, Z = stft(x, sr, nperseg=nper, noverlap=nper - hop)
    mag = np.abs(Z)
    energy = mag.sum(axis=0)
    quiet = energy <= np.percentile(energy, 12)          # the room between phrases
    noise = np.median(mag[:, quiet], axis=1, keepdims=True) if quiet.any() else np.percentile(mag, 10, axis=1, keepdims=True)
    snr = mag / (strength * noise + 1e-12)
    gain = np.clip(1.0 - 1.0 / np.maximum(snr, 1e-6) ** 2, 0.0, 1.0) ** 0.5   # Wiener-style
    gain = np.maximum(gain, floor)
    # Smooth across time (≈30 ms) and frequency (3 bins): avoids musical noise.
    k_t = np.ones(5) / 5
    gain = np.apply_along_axis(lambda g: np.convolve(g, k_t, mode="same"), 1, gain)
    gain = np.apply_along_axis(lambda g: np.convolve(g, np.ones(3) / 3, mode="same"), 0, gain)
    _, y = istft(Z * gain, sr, nperseg=nper, noverlap=nper - hop)
    y = y[: len(x)]
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    return y


def _reverb_ir(sr: int, rt60: float = 0.9, predelay: float = 0.012, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(rt60 * sr)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-6.9 * t / rt60)          # -60 dB at rt60
    ir = sosfiltfilt(butter(2, 5000, fs=sr, output="sos"), ir)      # darker tail
    ir = np.concatenate([np.zeros(int(predelay * sr)), ir])
    return ir / np.sqrt(np.sum(ir ** 2))


def polish(x: np.ndarray, sr: int, wet: float = 0.14, hi_cut: float = 7500.0, lo_cut: float = 110.0) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if not np.any(x):
        return x
    y = sosfiltfilt(butter(2, [lo_cut, min(hi_cut, sr / 2 - 200)], btype="band", fs=sr, output="sos"), x)
    # Light compression (2.5:1 above -18 dB re: peak) with a smooth envelope.
    env = np.sqrt(np.convolve(y ** 2, np.ones(int(0.02 * sr)) / int(0.02 * sr), mode="same")) + 1e-9
    thr = 10 ** (-18 / 20) * np.max(np.abs(y))
    gain = np.where(env > thr, (thr / env) ** (1 - 1 / 2.5), 1.0)
    y = y * gain
    rev = fftconvolve(y, _reverb_ir(sr))[: len(y)]
    out = (1 - wet) * y + wet * rev
    peak = np.max(np.abs(out))
    return out / peak * np.max(np.abs(x)) if peak > 0 else out
