import random

import pytest

from backend.harmony.reharmonize import (
    CANDIDATES,
    HARMONY_STYLES,
    Chord,
    _parse_voice_profile,
    harmony_parts,
    harmony_variations,
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
    assert d["timeline"][0] == {"symbol": "C", "roman": "I", "start": 0, "end": 4}
    assert d["key"] == {"tonic": "C", "mode": "major"}


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


# --- creative controls: lenses, locks, explanations ------------------------

# ii-V-I melody: F/D over Dm7, F/B over G7, E/C over C.
II_V_I = [{"pitch": p, "start": i, "duration": 1}
          for i, p in enumerate([65, 62, 65, 71, 64, 64, 64, 64, 65, 69, 65, 71, 72, 72, 72, 72])]
II_V_I_CHORDS = ["Dm7", "Dm7", "G7", "G7", "C", "C", "C", "C", "Dm7", "Dm7", "G7", "G7", "C", "C", "C", "C"]


def _best(melody, chords, **kw):
    return reharmonize(melody, chords, **kw)[0]


def test_lenses_change_output_even_at_novelty_zero():
    base = _best(TWINKLE, TWINKLE_CHORDS).symbols
    for lens in ("borrowed", "color", "suspense", "passing"):
        assert _best(TWINKLE, TWINKLE_CHORDS, palette={lens: 1.0}).symbols != base, lens


def test_borrowed_lens_uses_parallel_minor():
    r = _best(TWINKLE, TWINKLE_CHORDS, palette={"borrowed": 1.0})
    assert {"Cm", "Fm"} & set(r.symbols)
    assert any("borrowed from C minor" in tag for e in r.explain() for tag in e["tags"])


def test_tritone_lens_substitutes_the_dominant():
    r = _best(II_V_I, II_V_I_CHORDS, palette={"tritone": 1.0})
    assert "C#7" in r.symbols  # bII7 -> I instead of G7 -> C
    assert any("tritone substitution" in tag for e in r.explain() for tag in e["tags"])


def test_color_lens_prefers_diatonic_sevenths():
    r = _best(II_V_I, II_V_I_CHORDS, palette={"color": 1.0})
    assert "Cmaj7" in r.symbols and "C7" not in r.symbols


def test_density_lens_controls_harmonic_rhythm():
    def changes(d):
        s = _best(TWINKLE, TWINKLE_CHORDS, novelty=0.5, palette={"density": d}).symbols
        return sum(a != b for a, b in zip(s, s[1:]))
    assert changes(0.0) < changes(1.0)


def test_unknown_lens_rejected():
    with pytest.raises(ValueError):
        reharmonize(TWINKLE, TWINKLE_CHORDS, palette={"vibes": 1})


def test_locks_are_respected():
    locks = {0: "Am", 4: "Dm7", 15: "C"}
    for r in reharmonize(TWINKLE, TWINKLE_CHORDS, novelty=1.0, locks=locks):
        assert r.symbols[0] == "Am" and r.symbols[4] == "Dm7" and r.symbols[15] == "C"
    # A plain list of beats keeps the detected chord there.
    r = _best(TWINKLE, TWINKLE_CHORDS, novelty=1.0, locks=[12, 13])
    assert r.symbols[12:14] == ["G", "G"]


def test_explanations_cover_every_changed_segment():
    r = _best(TWINKLE, TWINKLE_CHORDS, novelty=1.0)
    expl = r.explain()
    covered = {t for e in expl for t in range(int(e["start"]), int(e["end"]))}
    assert set(r.changed_beats) <= covered
    assert all(e["tags"] and e["roman"] for e in expl)


# --- harmony styles ----------------------------------------------------------

@pytest.mark.parametrize("style", sorted(HARMONY_STYLES))
@pytest.mark.parametrize("vp", VOICES)
def test_every_style_stays_in_range_on_chord_tones(style, vp):
    rng = random.Random(1)
    low, high, _, _ = _parse_voice_profile(vp)
    for _ in range(10):
        melody = [{"pitch": rng.randint(50, 80), "start": i * 0.5, "duration": 0.5} for i in range(24)]
        chords = [rng.choice(CANDIDATES).name for _ in range(12)]
        parts = harmony_parts(melody, chords, vp, style=style)
        for track in parts.values():
            for note in track:
                assert low <= note["pitch"] <= high
                chord = parse_chord(chords[int(note["start"])])
                # Wide ranges always allow a chord tone.
                if high - low >= 12:
                    assert note["pitch"] % 12 in chord.tones


def test_pad_style_holds_notes_across_the_chord():
    vp = {"low": 45, "high": 74, "strongLow": 48, "strongHigh": 70}
    pad = harmony_parts(TWINKLE, TWINKLE_CHORDS, vp, style="pad")
    par = harmony_parts(TWINKLE, TWINKLE_CHORDS, vp, style="parallel")
    assert len(pad["sixth_below"]) < len(par["sixth_below"])
    total = sum(n["duration"] for n in pad["sixth_below"])
    assert total == pytest.approx(sum(n["duration"] for n in TWINKLE))


def test_contrary_style_moves_against_the_melody():
    vp = {"low": 45, "high": 74, "strongLow": 48, "strongHigh": 70}

    def contrary_moves(style):
        part = harmony_parts(TWINKLE, TWINKLE_CHORDS, vp, style=style)["sixth_below"]
        m = [n["pitch"] for n in TWINKLE]
        p = [n["pitch"] for n in part]
        return sum((m[i] - m[i - 1]) * (p[i] - p[i - 1]) < 0 for i in range(1, len(m)))

    assert contrary_moves("contrary") > contrary_moves("voice_led")


def test_harmony_variations_returns_every_style():
    v = harmony_variations(TWINKLE, TWINKLE_CHORDS, {"low": 48, "high": 72})
    assert set(v) == set(HARMONY_STYLES)
    assert all(v[s]["description"] and v[s]["third_above"] for s in v)
