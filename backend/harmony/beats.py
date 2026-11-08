"""Tempo and beat tracking for full songs, plus a beat grid shared by every stage.

    track_beats(samples, sr) -> BeatGrid
    BeatGrid.constant(bpm, beat0)   # for click-track recordings

Beat tracking is the classic onset-envelope + dynamic-programming method
(Ellis 2007): find where the music "hits" (spectral flux), pick the tempo whose
period best explains the hits (autocorrelation with a prior around 110 bpm),
then choose beat times that land on hits while keeping the spacing steady.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SR = 22050
N_FFT = 2048
HOP = 512
FPS = SR / HOP  # onset-envelope frames per second (~43)
# Frame k's window starts at k*HOP, so the flux peak for an attack shows up
# half a window plus one hop (the diff) before the attack itself.
ONSET_LATENCY = (N_FFT / 2 + HOP) / SR


@dataclass
class BeatGrid:
    """Monotonic map between seconds and beats. Extrapolates linearly at the ends."""

    times: np.ndarray  # beat times in seconds, strictly increasing, len >= 2
    beats_per_bar: int = 4

    @classmethod
    def constant(cls, bpm: float, beat0: float, n_beats: int = 2000, beats_per_bar: int = 4) -> "BeatGrid":
        spb = 60.0 / bpm
        return cls(beat0 + spb * np.arange(n_beats), beats_per_bar)

    @property
    def bpm(self) -> float:
        return float(60.0 / np.median(np.diff(self.times)))

    def to_beats(self, t):
        t = np.asarray(t, dtype=float)
        x, y = self.times, np.arange(len(self.times), dtype=float)
        b = np.interp(t, x, y)
        lo_slope = 1.0 / (x[1] - x[0])
        hi_slope = 1.0 / (x[-1] - x[-2])
        b = np.where(t < x[0], (t - x[0]) * lo_slope, b)
        b = np.where(t > x[-1], y[-1] + (t - x[-1]) * hi_slope, b)
        return b if b.ndim else float(b)

    def to_time(self, b):
        b = np.asarray(b, dtype=float)
        x, y = np.arange(len(self.times), dtype=float), self.times
        t = np.interp(b, x, y)
        t = np.where(b < 0, y[0] + b * (y[1] - y[0]), t)
        t = np.where(b > x[-1], y[-1] + (b - x[-1]) * (y[-1] - y[-2]), t)
        return t if t.ndim else float(t)

    def shifted(self, seconds: float) -> "BeatGrid":
        return BeatGrid(self.times + seconds, self.beats_per_bar)

    def trimmed(self, n: int) -> list[float]:
        return [round(float(t), 4) for t in self.times[:n]]


def resample(x: np.ndarray, sr: int, target: int) -> np.ndarray:
    """Band-limited resampling via FFT (fine for analysis; not for playback)."""
    if sr == target:
        return np.asarray(x, dtype=np.float64)
    n = int(round(len(x) * target / sr))
    X = np.fft.rfft(x)
    keep = n // 2 + 1
    Y = np.zeros(keep, dtype=complex)
    m = min(keep, len(X))
    Y[:m] = X[:m]
    return np.fft.irfft(Y, n) * (n / len(x))


def stft_mag(x: np.ndarray, n_fft: int = N_FFT, hop: int = HOP) -> np.ndarray:
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop]
    return np.abs(np.fft.rfft(frames * np.hanning(n_fft), axis=1))


def onset_envelope(x: np.ndarray, sr: int) -> np.ndarray:
    """Spectral flux on a log-magnitude spectrogram, smoothed and normalized."""
    y = resample(x, sr, SR)
    S = np.log1p(100 * stft_mag(y))
    flux = np.maximum(np.diff(S, axis=0), 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # remove slow loudness trend
    flux = np.maximum(flux, 0)
    sd = flux.std()
    return flux / sd if sd > 0 else flux


def estimate_tempo(env: np.ndarray, lo: float = 60, hi: float = 180, prior_bpm: float = 110) -> float:
    env = env - env.mean()
    n = len(env)
    ac = np.fft.irfft(np.abs(np.fft.rfft(env, 2 * n)) ** 2)[:n]
    lags = np.arange(int(FPS * 60 / hi), min(n - 1, int(FPS * 60 / lo)) + 1)
    if len(lags) == 0:
        return prior_bpm
    bpms = 60 * FPS / lags
    prior = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / 0.9) ** 2)
    score = ac[lags] * prior
    i = int(np.argmax(score))
    # Parabolic refinement of the lag.
    if 0 < i < len(lags) - 1:
        a, b, c = score[i - 1], score[i], score[i + 1]
        den = a - 2 * b + c
        lag = lags[i] + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0)
    else:
        lag = lags[i]
    return float(60 * FPS / lag)


def _dp_beats(env: np.ndarray, period: float, tightness: float = 100.0) -> np.ndarray:
    n = len(env)
    score = env.astype(float).copy()
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    for t in range(n):
        a, b = max(0, t - hi), t - lo
        if b <= a:
            continue
        prev = np.arange(a, b)
        penalty = -tightness * np.log((t - prev) / period) ** 2
        cand = score[prev] + penalty
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[t] = env[t] + cand[j]
            back[t] = prev[j]
    # End on the best-scoring frame in the last period.
    tail = np.arange(max(0, n - int(period)), n)
    t = int(tail[np.argmax(score[tail])])
    beats = [t]
    while back[t] >= 0:
        t = int(back[t])
        beats.append(t)
    return np.array(beats[::-1])


def track_beats(samples: np.ndarray, sr: int, bpm_hint: float | None = None, beats_per_bar: int = 4) -> BeatGrid:
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    env = onset_envelope(x, sr)
    bpm = bpm_hint or estimate_tempo(env)
    period = 60 * FPS / bpm
    frames = _dp_beats(env, period)
    times = frames / FPS + ONSET_LATENCY
    if len(times) < 2:
        return BeatGrid.constant(bpm, float(times[0]) if len(times) else 0.0, beats_per_bar=beats_per_bar)
    # Extend the grid to cover the whole song (DP may stop short at quiet ends).
    spb = float(np.median(np.diff(times)))
    head = np.arange(times[0] - spb, -spb, -spb)[::-1]
    head = head[head >= 0]
    end = len(x) / sr
    tail = np.arange(times[-1] + spb, end + spb, spb)
    return BeatGrid(np.concatenate([head, times, tail]), beats_per_bar)


ONSET_SIGMA = 0.05      # seconds: how tightly sung notes sit on the beat
TEMPO_PRIOR_OCTAVES = 0.9


def fit_tempo(onsets: np.ndarray, weights: np.ndarray, lo: float = 50.0, hi: float = 170.0,
              prior_bpm: float = 95.0) -> tuple[float, float]:
    """(bpm, phase in seconds): the beat grid that best fits the exact note onsets.

    Works on continuous times, so the result doesn't depend on analysis-frame
    rounding, where the recording starts, or its sample rate. Each grid's
    score is its onset hits minus the hits a grid that dense would get by
    chance (otherwise the fastest tempo always wins), times a tempo prior.
    """
    t = onsets - onsets.min()
    w = weights / weights.sum()
    bpms = np.arange(lo, hi + 1e-9, 0.25)
    best = (-np.inf, prior_bpm, 0.0)
    for bpm in bpms:
        period = 60.0 / bpm
        phases = np.arange(0.0, period, min(ONSET_SIGMA / 2, period / 8))
        d = (t[None, :] - phases[:, None] + period / 2) % period - period / 2
        d2 = (t[None, :] - phases[:, None] + period / 4) % (period / 2) - period / 4  # half beats count a little
        hit = np.exp(-0.5 * (d / ONSET_SIGMA) ** 2) + 0.3 * np.exp(-0.5 * (d2 / ONSET_SIGMA) ** 2)
        chance = ONSET_SIGMA * np.sqrt(2 * np.pi) / period * 1.6
        score = (hit @ w) - chance
        prior = np.exp(-0.5 * (np.log2(bpm / prior_bpm) / TEMPO_PRIOR_OCTAVES) ** 2)
        j = int(np.argmax(score))
        if score[j] * prior > best[0]:
            best = (float(score[j] * prior), float(bpm), float(phases[j]))
    return best[1], best[2] + float(onsets.min())


def beats_from_onsets(onsets: np.ndarray, weights: np.ndarray | None = None, end: float | None = None,
                      beats_per_bar: int = 4, prior_bpm: float = 95.0) -> BeatGrid:
    """Tempo and beats from note onsets alone (a voice with no click or band).

    The grid is fitted to the exact onset times (longer notes weigh more), then
    follows the singer: each beat is nudged toward a nearby onset, so gradual
    speeding up or slowing down is tracked without jumping.
    """
    onsets = np.sort(np.asarray(onsets, dtype=float))
    if len(onsets) < 4:
        return BeatGrid.constant(prior_bpm, float(onsets[0]) if len(onsets) else 0.0, beats_per_bar=beats_per_bar)
    w = np.ones_like(onsets) if weights is None else np.asarray(weights, dtype=float)
    end = float(end if end is not None else onsets.max() + 1.0)
    bpm, phase = fit_tempo(onsets, w, prior_bpm=prior_bpm)
    period = 60.0 / bpm
    first = phase - np.ceil((phase - onsets.min()) / period) * period   # the last grid beat at or before the first note
    times, t, p = [], first, period
    while t < end + 2 * period:
        times.append(t)
        k = int(np.searchsorted(onsets, t))
        near = [onsets[j] for j in (k - 1, k) if 0 <= j < len(onsets) and abs(onsets[j] - t) < 0.12]
        if near:
            err = min(near, key=lambda o: abs(o - t)) - t
            t += 0.25 * err               # phase correction
            p += 0.04 * err               # slow tempo correction
            p = float(np.clip(p, 0.9 * period, 1.1 * period))
        t += p
    return BeatGrid(np.array(times), beats_per_bar)
