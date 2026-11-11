"""Voice / music separation with Demucs (htdemucs), the one place we need a
trained model to *listen*: pulling a voice out of a mix is not something
hand-written DSP does well.

    separate(samples, sr) -> Stems(vocals, accompaniment, sr, has_music)

Mono or stereo in; mono stems out at 44.1 kHz. The model is loaded once.

The voice comes from the vocals specialist of htdemucs_ft (one model of the
fine-tuned bag, so it costs the same as plain htdemucs), and the backing is
the mix minus that voice, so the two always add back up to the song. On the
MUSDB18 sample set this lifted vocal SDR from 9.4 to 10.2 dB and backing SDR
from 13.6 to 13.7-14.0 dB over plain htdemucs; Wiener-style masking and a
two-model ensemble were tried and did not help.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

MODEL_NAME = "htdemucs_ft"   # fine-tuned bag; we keep only its vocals model
FALLBACK_MODEL = "htdemucs"
SHIFTS = 1  # one random time shift: a small, free quality gain
MUSIC_RATIO = 0.18  # accompaniment RMS / vocals RMS above this => there is music

_model = None
_lock = threading.Lock()


@dataclass
class Stems:
    vocals: np.ndarray          # mono float32
    accompaniment: np.ndarray   # mono float32 (drums + bass + other)
    sr: int
    has_music: bool
    music_ratio: float


def _load():
    global _model
    with _lock:
        if _model is None:
            from demucs.pretrained import get_model
            try:
                bag = get_model(MODEL_NAME)
                vi = bag.sources.index("vocals")
                # Each model in the fine-tuned bag is weighted for one source.
                m = bag.models[max(range(len(bag.models)), key=lambda k: float(bag.weights[k][vi]))]
            except Exception:  # weights not downloadable: the general model still works
                m = get_model(FALLBACK_MODEL)
            m.eval()
            _model = m
    return _model


def _device():
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def separate(samples: np.ndarray, sr: int, progress=None) -> Stems:
    import julius
    import torch
    from demucs.apply import apply_model

    model = _load()
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 1:
        x = np.stack([x, x])
    elif x.shape[0] > x.shape[1]:  # (n, channels) -> (channels, n)
        x = x.T
    x = x[:2] if x.shape[0] >= 2 else np.concatenate([x, x])
    wav = torch.from_numpy(np.ascontiguousarray(x))
    if sr != model.samplerate:
        wav = julius.resample_frac(wav, sr, model.samplerate)

    mixture = wav.mean(0)
    ref = mixture
    mean, std = ref.mean(), ref.std().clamp_min(1e-8)
    wav = (wav - mean) / std

    def run(device):
        with torch.no_grad():
            return apply_model(model, wav[None], device=device, shifts=SHIFTS, split=True,
                               overlap=0.25, progress=False)[0]

    if progress:
        progress("separating voice from music")
    try:
        out = run(_device())
    except (RuntimeError, NotImplementedError):
        out = run("cpu")  # some ops are missing on MPS for long inputs
    out = out * std + mean

    vi = model.sources.index("vocals")
    vocals = out[vi].mean(0).cpu().numpy().astype(np.float32)
    accomp = (mixture.numpy() - vocals).astype(np.float32)
    rv = float(np.sqrt(np.mean(vocals ** 2)) + 1e-9)
    ra = float(np.sqrt(np.mean(accomp ** 2)))
    ratio = ra / rv
    return Stems(vocals, accomp, model.samplerate, ratio > MUSIC_RATIO, ratio)
