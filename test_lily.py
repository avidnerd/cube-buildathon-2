"""Tests for the LilyPond parser/writer (lily.py)."""
from __future__ import annotations

import glob

import pytest

import lily
from lily import KeySig, Meter

SAMPLES = sorted(glob.glob("samples/*.ly"))
SPEC_EXAMPLES = [
    r"\relative c' { \key g \major \time 4/4 d4 d8 e8 d4 g4 | fis2 d4 d8 e8 | d4 a'4 g2 }",
    "c'4 c' g' g' | a' a' g'2 | f'4 f' e' e' | d' d' c'2",
]


def midis(text: str) -> list:
    return [n.midi for n in lily.parse(text).notes]


def durs(text: str) -> list:
    return [n.dur for n in lily.parse(text).notes]


# --- octaves ---------------------------------------------------------------

def test_absolute_octaves():
    assert midis("c c' c'' c, c,,") == [48, 60, 72, 36, 24]
    assert midis("b' g''") == [71, 79]


def test_relative_mode_nearest_octave():
    assert midis(r"\relative c' { c d e f g a b c }") == [60, 62, 64, 65, 67, 69, 71, 72]
    # g' : nearest G to C4 is G3, raised an octave; c, : nearest C to G4 is C5, lowered
    assert midis(r"\relative c' { c g' c, }") == [60, 67, 60]
    # a fourth is the turning point: c -> f goes up, c -> g goes down
    assert midis(r"\relative c'' { c f c g }") == [72, 77, 72, 67]


def test_relative_without_start_pitch_is_absolute_first_note():
    assert midis(r"\relative { c' d e }") == [60, 62, 64]


def test_relative_uses_letters_not_semitones():
    # From B4, 'eis' (E#) is a 4th up by letter name even though it is 6 semitones.
    assert midis(r"\relative c'' { b eis }") == [71, 77]


def test_relative_ends_with_block():
    assert midis(r"\relative c'' { c } c") == [72, 48]


# --- durations ------------------------------------------------------------

def test_sticky_durations_default_quarter():
    assert durs("c d8 e f2 g") == [1.0, 0.5, 0.5, 2.0, 2.0]


def test_dotted_durations_are_sticky():
    assert durs("c4. d8 e8. f16 g2. a") == [1.5, 0.5, 0.75, 0.25, 3.0, 3.0]


def test_ties_merge_notes():
    s = lily.parse("c'2~ c'8 d'4. | e'1~ | e'2 r2")
    assert [(n.midi, n.start, n.dur) for n in s.notes] == [
        (60, 0.0, 2.5), (62, 2.5, 1.5), (64, 4.0, 6.0), (None, 10.0, 2.0)]


def test_tie_between_different_pitches_warns():
    s = lily.parse("c'4~ d'4")
    assert midis("c'4~ d'4") == [60, 62]
    assert any("tie" in w for w in s.warnings)


def test_rests_with_durations():
    s = lily.parse("r4 c'8 r8 r2")
    assert [(n.midi, n.start, n.dur) for n in s.notes] == [
        (None, 0.0, 1.0), (60, 1.0, 0.5), (None, 1.5, 2.5)]


# --- accidentals ------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("fis'", 66), ("bes'", 70), ("ees'", 63), ("es'", 63), ("aes'", 68), ("as'", 68),
    ("cisis'", 62), ("eses'", 62), ("ases'", 67), ("beses'", 69), ("ces'", 59), ("bis", 60),
])
def test_accidentals(name, expected):
    assert midis(name) == [expected]


# --- headers --------------------------------------------------------------------

def test_key_time_tempo_headers():
    s = lily.parse(r"\key g \major \time 3/4 \tempo 4 = 92 g'4")
    assert s.key == KeySig(4, 0, "major")
    assert (s.meter.num, s.meter.den) == (3, 4)
    assert (s.tempo_bpm, s.tempo_unit) == (92, "4")


def test_minor_and_flat_keys():
    assert lily.parse(r"\key d \minor d'4").key == KeySig(1, 0, "minor")
    assert lily.parse(r"\key bes \major d'4").key == KeySig(6, -1, "major")
    assert lily.parse(r"\key fis \minor d'4").key == KeySig(3, 1, "minor")


def test_defaults_when_headers_missing():
    s = lily.parse("c'4 d'")
    assert s.key is None
    assert (s.meter.num, s.meter.den) == (4, 4)
    assert s.tempo_bpm == 100


def test_partial_and_pickup_meter():
    s = lily.parse(r"\time 3/4 \partial 4 d'4 | g'2 b'4 |")
    assert s.meter.pickup == 1.0
    assert s.meter.bar_index(0.0) == 0 and s.meter.bar_index(1.0) == 1
    assert s.meter.is_strong(1.0) and not s.meter.is_strong(0.0)
    assert not s.warnings


# --- robustness / warnings --------------------------------------------------------

def test_bar_check_warns_on_wrong_length():
    s = lily.parse("c'4 d' e' f' | g' a' b' | c''1")
    assert any("bar 2" in w for w in s.warnings)


def test_unknown_things_are_ignored_with_warnings():
    s = lily.parse(r"""\clef treble c'4-. d'( e') \p f'-> % comment
                       %{ block comment %} g'4 \fermata [a'8] b'""")
    assert midis(r"""\clef treble c'4-. d'( e') \p f'-> g'4 \fermata [a'8] b'""") == \
        [60, 62, 64, 65, 67, 69, 71]
    assert len(s.warnings) >= 6


def test_header_block_is_skipped():
    s = lily.parse('\\header { title = "x { y }" } c\'4')
    assert [n.midi for n in s.notes] == [60]


def test_spec_examples_parse():
    s = lily.parse(SPEC_EXAMPLES[0])
    assert [n.midi for n in s.notes][:6] == [62, 62, 64, 62, 67, 66]
    assert sum(n.dur for n in s.notes) == 12.0 and not s.warnings
    s = lily.parse(SPEC_EXAMPLES[1])
    assert len(s.notes) == 14 and sum(n.dur for n in s.notes) == 16.0 and not s.warnings


@pytest.mark.parametrize("path", SAMPLES)
def test_samples_parse_cleanly(path):
    s = lily.parse(open(path, encoding="utf-8").read())
    assert s.notes and not s.warnings


# --- writer ----------------------------------------------------------------------

def test_spelling_follows_key():
    d_major, f_major, d_minor = KeySig(1, 0, "major"), KeySig(3, 0, "major"), KeySig(1, 0, "minor")
    assert lily.midi_to_lily(66, d_major) == "fis'"
    assert lily.midi_to_lily(70, f_major) == "bes'"
    assert lily.midi_to_lily(61, d_minor) == "cis'"       # leading tone in D minor
    assert lily.midi_to_lily(63, KeySig(5, -1, "major")) == "es'"
    assert lily.midi_to_lily(48, d_major) == "c"
    assert lily.midi_to_lily(36, d_major) == "c,"


def test_writer_splits_and_ties_across_barlines():
    notes = [lily.Note(60, 0.0, 3.0), lily.Note(62, 3.0, 3.0)]
    text = lily.format_notes(notes, KeySig(0, 0, "major"), Meter(4, 4))
    assert text == "c'2. d'4~ | d'2 r"      # durations are sticky


def round_trip(text: str) -> None:
    s1 = lily.parse(text)
    key = s1.key or KeySig(0, 0, "major")
    out = lily.format_music(s1.notes, key, s1.meter, s1.tempo_bpm, s1.tempo_unit)
    s2 = lily.parse(out)
    pad = s2.notes[len(s1.notes):]
    assert all(n.midi is None for n in pad), "only bar-padding rests may be added"
    core = s2.notes[:len(s1.notes)]
    if s1.notes[-1].midi is None:       # a final rest may be extended by padding
        core[-1] = lily.Note(None, core[-1].start, s1.notes[-1].dur)
    assert [(n.midi, n.start, n.dur) for n in core] == [(n.midi, n.start, n.dur) for n in s1.notes]
    assert s2.meter == s1.meter
    assert (s2.tempo_bpm, s2.tempo_unit) == (s1.tempo_bpm, s1.tempo_unit)
    assert not [w for w in s2.warnings if w.startswith("bar")]


@pytest.mark.parametrize("path", SAMPLES)
def test_round_trip_samples(path):
    round_trip(open(path, encoding="utf-8").read())


@pytest.mark.parametrize("text", SPEC_EXAMPLES + [
    r"\time 6/8 c'4. d'8 e' f' | g'2. ~ | g'4. r4.",
    r"\key bes \major \time 2/4 bes8. c'16 d'4 | ees'2 |",
    r"\key e \minor \time 3/4 \partial 8 b8 | e'4. fis'8 g'4 | dis'2. |",
])
def test_round_trip_examples(text):
    round_trip(text)
