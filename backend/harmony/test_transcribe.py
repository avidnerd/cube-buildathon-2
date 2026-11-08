import numpy as np
import pytest

from backend.harmony.transcribe import transcribe, yin

SR = 16000


def synth_voice(notes, bpm, sr=SR, count_in_beats=4, detune_cents=-30.0, vibrato_cents=35.0,
                noise=0.01, click=True, legato=0.9, scoop=True, seed=0):
    """Fake singer: harmonic tone with vibrato, detuning, scoops, breath noise, metronome bleed."""
    rng = np.random.default_rng(seed)
    spb = 60.0 / bpm
    total_beats = count_in_beats + max(s + d for _, s, d in notes) + 1
    n = int(total_beats * spb * sr)
    t = np.arange(n) / sr
    y = np.zeros(n)
    for k, (pitch, start, dur) in enumerate(notes):
        a = int((count_in_beats + start) * spb * sr)
        b = min(n, a + int(dur * legato * spb * sr))
        if k + 1 < len(notes):  # one voice can't overlap itself: leave a breath
            b = min(b, int((count_in_beats + notes[k + 1][1]) * spb * sr) - int(0.04 * sr))
        tt = t[a:b] - t[a]
        cents = detune_cents + vibrato_cents * np.sin(2 * np.pi * 5.5 * tt) * np.clip(tt / 0.25, 0, 1)
        if scoop:
            cents = cents - 80 * np.exp(-tt / 0.03)  # slide up into the note
        f = 440 * 2 ** ((pitch - 69 + cents / 100) / 12)
        phase = 2 * np.pi * np.cumsum(f) / sr
        tone = sum(amp * np.sin(k * phase) for k, amp in zip(range(1, 8), (1, .6, .45, .3, .2, .12, .08)))
        env = np.minimum(1, tt / 0.03) * np.minimum(1, (tt[-1] - tt) / 0.04 + 1e-9)
        y[a:b] += 0.3 * tone * env
    y += noise * rng.standard_normal(n)
    if click:
        for k in range(int(total_beats)):
            a = int(k * spb * sr)
            m = min(n - a, int(0.03 * sr))
            if m > 0:
                y[a:a + m] += 0.25 * np.sin(2 * np.pi * 2000 * t[:m]) * np.exp(-t[:m] / 0.008)
    return y, count_in_beats * spb


TWINKLE = [(p, i, 1) for i, p in enumerate([60, 60, 67, 67, 69, 69])] + [(67, 6, 2)] + \
          [(p, 8 + i, 1) for i, p in enumerate([65, 65, 64, 64, 62, 62])] + [(60, 14, 2)]


def test_yin_pure_tone():
    t = np.arange(SR) / SR
    for hz in (110.0, 220.0, 440.0, 880.0):
        _, f0, _, _ = yin(np.sin(2 * np.pi * hz * t), SR)
        assert np.nanmedian(f0) == pytest.approx(hz, rel=0.005)


@pytest.mark.parametrize("bpm", [80, 110])
def test_transcribes_sung_melody_to_beats(bpm):
    y, offset = synth_voice(TWINKLE, bpm)
    tr = transcribe(y, SR, bpm, offset)
    got = [(n["pitch"], n["start"]) for n in tr.notes]
    want = [(p, float(s)) for p, s, _ in TWINKLE]
    assert got == want
    assert tr.tuning_cents == pytest.approx(-30, abs=8)
    assert tr.sung_range == (60, 69)


def test_repeated_notes_are_split():
    notes = [(64, 0, 1), (64, 1, 1), (64, 2, 1), (64, 3, 1)]
    y, offset = synth_voice(notes, 90, legato=0.85)
    tr = transcribe(y, SR, 90, offset)
    assert [n["start"] for n in tr.notes] == [0, 1, 2, 3]


def test_low_voice_and_wide_leaps():
    notes = [(43, 0, 1), (55, 1, 1), (48, 2, 2), (62, 4, 1), (50, 5, 1)]
    y, offset = synth_voice(notes, 100)
    tr = transcribe(y, SR, 100, offset)
    assert [n["pitch"] for n in tr.notes] == [43, 55, 48, 62, 50]


def test_align_first_note_without_count_in():
    y, _ = synth_voice(TWINKLE[:4], 90, count_in_beats=0, click=False)
    y = np.concatenate([np.zeros(int(0.7 * SR)), y])  # leading silence
    tr = transcribe(y, SR, 90, align_first_note=True)
    assert [n["start"] for n in tr.notes] == [0, 1, 2, 3]


def test_silence_gives_no_notes():
    tr = transcribe(np.zeros(SR * 2), SR, 100)
    assert tr.notes == [] and tr.sung_range is None


def test_human_timing_and_tuning():
    """Random tempo, +-60 ms timing slop, +-45 cent detune, louder noise."""
    for seed in range(12):
        rng = np.random.default_rng(seed)
        bpm = int(rng.integers(70, 130))
        sloppy = [(p, s + rng.uniform(-0.06, 0.06) * bpm / 60, d) for p, s, d in TWINKLE]
        y, offset = synth_voice(sloppy, bpm, noise=0.03, seed=seed, detune_cents=rng.uniform(-45, 45))
        tr = transcribe(y, SR, bpm, offset)
        assert [(n["pitch"], n["start"]) for n in tr.notes] == [(p, float(s)) for p, s, _ in TWINKLE], (seed, bpm)


def test_syncopation_survives_snapping():
    notes = [(64, 0, 1.5), (67, 1.5, 0.5), (69, 2, 0.5), (67, 2.5, 1.25), (64, 3.75, 0.25), (62, 4, 2)]
    y, offset = synth_voice(notes, 84)
    tr = transcribe(y, SR, 84, offset)
    assert [(n["pitch"], n["start"]) for n in tr.notes] == [(p, float(s)) for p, s, _ in notes]


def test_scoops_and_slides_fold_into_their_note():
    from backend.harmony.transcribe import RawNote, absorb_ornaments
    raw = [RawNote(0.00, 0.09, 52, 52.0), RawNote(0.09, 0.19, 53, 53.0), RawNote(0.19, 0.28, 52, 52.0),
           RawNote(0.28, 0.80, 53, 53.0),                                   # scoop E-F-E into a held F
           RawNote(1.00, 1.50, 62, 62.0), RawNote(1.50, 1.58, 59, 59.0),     # slide D -> B -> G
           RawNote(1.58, 1.66, 55, 55.0), RawNote(1.66, 2.10, 57, 57.0)]
    out = absorb_ornaments(raw)
    assert [n.pitch for n in out] == [53, 62, 57]
    assert out[0].t0 == 0.0 and out[0].t1 == 0.80


def test_real_notes_are_not_absorbed():
    from backend.harmony.transcribe import RawNote, absorb_ornaments
    raw = [RawNote(0.0, 0.2, 60, 60.0), RawNote(0.2, 0.4, 62, 62.0), RawNote(0.4, 0.6, 64, 64.0)]
    assert absorb_ornaments(raw) == raw


@pytest.mark.parametrize("bpm", [72, 96, 120])
def test_tempo_detected_from_singing_alone(bpm):
    """No count-in, no click: the tempo comes from the sung rhythm."""
    melody = TWINKLE * 2
    melody = [(p, s + (16 if k >= len(TWINKLE) else 0), d) for k, (p, s, d) in enumerate(melody)]
    y, _ = synth_voice(melody, bpm, count_in_beats=0, click=False)
    y = np.concatenate([np.zeros(int(0.8 * SR)), y])
    tr = transcribe(y, SR)
    got = tr.meta["bpm"]
    assert got == pytest.approx(bpm, rel=0.05) or got == pytest.approx(2 * bpm, rel=0.05) or got == pytest.approx(bpm / 2, rel=0.05), got
    assert [n["pitch"] for n in tr.notes][:7] == [60, 60, 67, 67, 69, 69, 67]
