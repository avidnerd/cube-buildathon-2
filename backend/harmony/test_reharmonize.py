import random

import pytest

from backend.harmony.reharmonize import (
    CANDIDATES,
    Chord,
    harmony_parts,
    parse_chord,
    phase_distance,
    reharmonize,
    voice_leading_distance,
)

# "Twinkle"-shaped melody in C, one note per beat.
TWINKLE = [
    {"pitch": p, "start": i, "duration": 1}
    for i, p in enumerate([60, 60, 67, 67, 69, 69, 67, 67, 65, 65, 64, 64, 62, 62, 60, 60])
]
TWINKLE_CHORDS = ["C"] * 4 + ["F", "F", "C", "C", "F", "F", "C", "C", "G", "G", "C", "C"]

# Minor melody with mixed rhythms and timed chords.
MINOR = [
    (69, 0, 1), (72, 1, 0.5), (71, 1.5, 0.5), (69, 2, 2), (65, 4, 1), (64, 5, 1), (62, 6, 2),
    (64, 8, 1), (65, 9, 1), (64, 10, 1), (62, 11, 1), (60, 12, 1), (59, 13, 1), (57, 14, 2),
]
MINOR_CHORDS = [{"symbol": s, "start": a, "end": a + 4} for s, a in [("Am", 0), ("Dm", 4), ("E7", 8), ("Am", 12)]]

SONGS = [(TWINKLE, TWINKLE_CHORDS), (MINOR, MINOR_CHORDS)]


def _original_per_beat(chords, n):
    if isinstance(chords[0], dict):
        return [parse_chord(next(c for c in chords if c["start"] <= t < c["end"])) for t in range(n)]
    return [parse_chord(c) for c in chords]


def _longest_note_per_beat(melody, n):
    from backend.harmony.reharmonize import _parse_notes, _windows

    notes = _parse_notes(melody)
    _, longest = _windows(notes, n, 1.0)
    return [notes[l[1]].pitch % 12 if l else None for l in longest]


# --- building blocks -------------------------------------------------------

def test_candidate_set():
    assert len(CANDIDATES) == 84
    assert len({c.tones for c in CANDIDATES}) == 84


def test_parse_chord():
    assert parse_chord("Am7") == Chord(9, "min7")
    assert parse_chord("Bbmaj7") == Chord(10, "maj7")
    assert parse_chord("F#dim") == Chord(6, "dim")
    assert parse_chord("Bm7b5") == Chord(11, "dim")
    assert parse_chord("G7/B") == Chord(7, "7")
    assert parse_chord("Dsus4") == Chord(2, "sus4")
    assert parse_chord("N.C.") is None


def test_voice_leading_distance():
    C, Am, G, F = (parse_chord(s) for s in ("C", "Am", "G", "F"))
    assert voice_leading_distance(C, C) == 0
    assert voice_leading_distance(C, Am) == 2       # G -> A
    assert voice_leading_distance(C, F) == 3        # E->F, G->A
    assert voice_leading_distance(C, parse_chord("Cmaj7")) == 1  # doubled C -> B
    assert voice_leading_distance(C, parse_chord("F#")) > voice_leading_distance(C, G)


def test_phase_distance_symmetric_and_zero_on_self():
    for a in CANDIDATES[::7]:
        assert phase_distance(a, a) == pytest.approx(0.0, abs=1e-9)
        for b in CANDIDATES[::11]:
            assert phase_distance(a, b) == pytest.approx(phase_distance(b, a))


# --- acceptance ------------------------------------------------------------

@pytest.mark.parametrize("melody,chords", SONGS)
def test_novelty_zero_reproduces_detected_chords(melody, chords):
    best = reharmonize(melody, chords, novelty=0.0)[0]
    orig = _original_per_beat(chords, len(best.chords))
    same = sum(a == b for a, b in zip(best.chords, orig))
    assert same / len(orig) >= 0.9, best.symbols


@pytest.mark.parametrize("melody,chords", SONGS)
def test_novelty_one_differs_but_fits_melody(melody, chords):
    best = reharmonize(melody, chords, novelty=1.0)[0]
    n = len(best.chords)
    orig = _original_per_beat(chords, n)
    changed = sum(a != b for a, b in zip(best.chords, orig))
    assert changed / n >= 0.5, best.symbols

    # The longest note in every beat is a chord tone or an acceptable tension.
    for pc, chord in zip(_longest_note_per_beat(melody, n), best.chords):
        if pc is not None:
            assert pc in chord.tones or pc in chord.tensions, (chord, pc, best.symbols)


def test_novelty_ramps():
    changed = [len(reharmonize(TWINKLE, TWINKLE_CHORDS, novelty=x)[0].changed_beats) for x in (0, 0.5, 1)]
    assert changed[0] < changed[1] <= changed[2]


def test_returns_three_distinct_alternatives():
    paths = reharmonize(TWINKLE, TWINKLE_CHORDS, novelty=0.5)
    assert len(paths) == 3
    assert len({tuple(p.symbols) for p in paths}) == 3
    assert paths[0].score >= paths[1].score >= paths[2].score


def test_to_dict_timeline_merges_beats():
    d = reharmonize(TWINKLE, TWINKLE_CHORDS, novelty=0.0)[0].to_dict()
    assert d["timeline"][0] == {"symbol": "C", "start": 0, "end": 4}


# --- harmony parts ---------------------------------------------------------

VOICES = [
    {"low": 48, "high": 67, "strongLow": 50, "strongHigh": 64},     # baritone-ish
    {"low": "A3", "high": "C5"},                                    # narrow
    {"low": 60, "high": 66, "strongHigh": 64},                      # < an octave
    {"low": 55, "high": 79, "strongLow": 57, "strongHigh": 76},
]


@pytest.mark.parametrize("vp", VOICES)
def test_harmony_parts_stay_in_range(vp):
    rng = random.Random(0)
    from backend.harmony.reharmonize import _parse_voice_profile

    low, high, _, strong_high = _parse_voice_profile(vp)
    for _ in range(20):
        melody = [{"pitch": rng.randint(45, 84), "start": i * 0.5, "duration": 0.5} for i in range(32)]
        chords = [rng.choice(CANDIDATES).name for _ in range(16)]
        parts = harmony_parts(melody, chords, vp)
        for track in parts.values():
            assert len(track) == len(melody)
            for note in track:
                assert low <= note["pitch"] <= high


def test_harmony_parts_snap_to_chord_tones():
    vp = {"low": 36, "high": 84, "strongHigh": 84}
    parts = harmony_parts(TWINKLE, TWINKLE_CHORDS, vp)
    chords = [parse_chord(c) for c in TWINKLE_CHORDS]
    for m, u, l in zip(TWINKLE, parts["third_above"], parts["sixth_below"]):
        chord = chords[int(m["start"])]
        assert u["pitch"] % 12 in chord.tones and l["pitch"] % 12 in chord.tones
        assert 2 <= u["pitch"] - m["pitch"] <= 5     # roughly a third above
        assert 7 <= m["pitch"] - l["pitch"] <= 10    # roughly a sixth below
    # The interval bends with the harmony: C over C major gets E (M3); A over F gets C (m3).
    assert parts["third_above"][0]["pitch"] == 64
    assert parts["third_above"][4]["pitch"] == 72


def test_harmony_parts_invert_above_strong_high():
    vp = {"low": 48, "high": 76, "strongHigh": 70}
    melody = [{"pitch": 69, "start": 0, "duration": 1}]  # A4 over F: third above is C5 (72)
    up = harmony_parts(melody, ["F"], vp)["third_above"][0]["pitch"]
    assert up == 60  # inverted down an octave


def test_harmony_parts_accepts_reharmonization():
    best = reharmonize(TWINKLE, TWINKLE_CHORDS, novelty=1.0)[0]
    parts = harmony_parts(TWINKLE, best, {"low": 48, "high": 72})
    for m, u in zip(TWINKLE, parts["third_above"]):
        assert u["pitch"] % 12 in best.chords[int(m["start"])].tones
