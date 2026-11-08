"""Beat tracking and chord detection on a synthetic band."""

import numpy as np
import pytest

from backend.harmony.beats import BeatGrid, track_beats
from backend.harmony.chords import detect_chords
from backend.harmony.reharmonize import parse_chord

SR = 22050


def synth_band(progression, bpm, sr=SR, beats_per_chord=2, start=0.5, seed=0, drums=True, detune_cents=0.0):
    """Piano-ish chords on every beat, bass on the root, kick/snare/hats."""
    rng = np.random.default_rng(seed)
    spb = 60 / bpm
    n_beats = len(progression) * beats_per_chord
    n = int((start + n_beats * spb + 1.0) * sr)
    y = np.zeros(n)
    t = np.arange(n) / sr
    tune = 2 ** (detune_cents / 1200)

    def note(midi, t0, dur, amp, partials=6, decay=1.2):
        a, b = int(t0 * sr), min(n, int((t0 + dur) * sr))
        tt = t[a:b] - t[a]
        f = 440 * 2 ** ((midi - 69) / 12) * tune
        tone = sum((0.6 ** k) * np.sin(2 * np.pi * f * (k + 1) * tt) for k in range(partials))
        y[a:b] += amp * tone * np.exp(-tt / decay) * np.minimum(1, tt / 0.005)

    for i, sym in enumerate(progression):
        c = parse_chord(sym)
        for k in range(beats_per_chord):
            bt = start + (i * beats_per_chord + k) * spb
            for pc in sorted(c.tones):
                note(60 + ((pc - 60) % 12), bt, spb, 0.12)
            note(36 + c.root, bt, spb, 0.25, partials=3, decay=0.6)
    if drums:
        for b in range(n_beats):
            bt = start + b * spb
            a = int(bt * sr)
            m = min(n - a, int(0.15 * sr))
            tt = t[:m]
            if b % 2 == 0:  # kick
                y[a:a + m] += 0.8 * np.sin(2 * np.pi * (50 + 80 * np.exp(-tt / 0.02)) * tt) * np.exp(-tt / 0.06)
            else:           # snare
                y[a:a + m] += 0.3 * rng.standard_normal(m) * np.exp(-tt / 0.05)
            for h in (0, 0.5):  # hats
                a2 = int((bt + h * spb) * sr)
                m2 = min(n - a2, int(0.03 * sr))
                y[a2:a2 + m2] += 0.08 * rng.standard_normal(m2) * np.exp(-t[:m2] / 0.01)
    return y, start


POP = ["C", "G", "Am", "F"] * 4
JAZZ = ["Dm7", "G7", "Cmaj7", "Cmaj7", "Em7", "A7", "Dm7", "G7"] * 2


def test_beat_grid_round_trip():
    g = BeatGrid(np.array([0.5, 1.0, 1.6, 2.1]))
    for b in (-1.0, 0.0, 1.5, 3.0, 4.5):
        assert g.to_beats(g.to_time(b)) == pytest.approx(b)


@pytest.mark.parametrize("bpm", [84, 100, 128])
def test_tempo_and_beats(bpm):
    y, start = synth_band(POP, bpm)
    grid = track_beats(y, SR)
    assert grid.bpm == pytest.approx(bpm, rel=0.03)
    # Every true beat has a tracked beat within 40 ms.
    true = start + np.arange(len(POP) * 2) * 60 / bpm
    nearest = np.min(np.abs(grid.times[None, :] - true[:, None]), axis=1)
    assert np.percentile(nearest, 90) < 0.04


@pytest.mark.parametrize("prog", [POP, JAZZ], ids=["pop", "jazz"])
def test_chords_from_accompaniment(prog):
    bpm = 100
    y, start = synth_band(prog, bpm, detune_cents=-20)
    grid = BeatGrid.constant(bpm, start)
    got = detect_chords(y, SR, grid, len(prog) * 2)
    want = [parse_chord(s) for s in prog for _ in range(2)]
    acc = np.mean([a == b for a, b in zip(got, want)])
    assert acc >= 0.9, [c.name if c else None for c in got]


def test_chords_with_tracked_beats():
    """Full listening path: track beats, then detect chords on that grid."""
    y, _ = synth_band(POP, 112)
    grid = track_beats(y, SR)
    first = int(round(grid.to_beats(0.5)))
    got = detect_chords(y, SR, grid, first + len(POP) * 2)[first:]
    names = [c.name if c else None for c in got]
    want = [s for s in POP for _ in range(2)]
    assert np.mean([a == b for a, b in zip(names, want)]) >= 0.85, names
