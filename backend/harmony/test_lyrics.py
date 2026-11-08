import pytest

from backend.harmony.lyrics import (
    HOLD,
    Word,
    attach_lyrics,
    join_lyrics,
    lines_from_notes,
    lyric_for_harmony,
    lyrics_from_text,
    syllables,
)
from backend.harmony.reharmonize import harmony_parts


@pytest.mark.parametrize("word,expected", [
    ("star", ["star"]),
    ("twinkle", ["twin", "kle"]),
    ("little", ["lit", "tle"]),
    ("wonder", ["won", "der"]),
    ("make", ["make"]),
    ("diamond", ["dia", "mond"]),  # vowel hiatus needs a dictionary; close enough for note spreading
    ("above,", ["a", "bove,"]),
])
def test_syllables(word, expected):
    assert syllables(word) == expected


def _notes(spec, spb=0.5):
    """spec: list of (pitch, start_beat, dur_beats) -> notes with seconds."""
    return [{"pitch": p, "start": s, "duration": d, "t0": s * spb, "t1": (s + d) * spb - 0.05} for p, s, d in spec]


TWINKLE = _notes([(60, 0, 1), (60, 1, 1), (67, 2, 1), (67, 3, 1), (69, 4, 1), (69, 5, 1), (67, 6, 2)])
WORDS = [Word("Twinkle", 0.0, 0.95), Word("twinkle", 1.0, 1.95), Word("little", 2.0, 2.95), Word("star,", 3.0, 3.9)]


def test_attach_spreads_syllables_over_notes():
    out = attach_lyrics(TWINKLE, WORDS)
    assert [n["lyric"] for n in out] == ["Twin-", "kle", "twin-", "kle", "lit-", "tle", "star,"]
    assert [n["word_start"] for n in out] == [True, False, True, False, True, False, True]


def test_melisma_holds_and_crowded_word_merges():
    notes = _notes([(60, 0, 1), (62, 1, 1), (64, 2, 1), (65, 3, 1)])
    out = attach_lyrics(notes, [Word("oh", 0.0, 1.45), Word("everybody", 1.5, 1.95)])
    assert [n["lyric"] for n in out][:3] == ["oh", HOLD, HOLD]
    assert out[3]["lyric"] == "everybody"  # 4 syllables, 1 note: merged


def test_word_between_notes_takes_nearest_free_note():
    notes = _notes([(60, 0, 1), (62, 2, 1)])
    out = attach_lyrics(notes, [Word("hey", 0.05, 0.4), Word("you", 0.6, 0.8)])
    assert [n["lyric"] for n in out] == ["hey", "you"]


def test_typed_lyrics_one_syllable_per_note():
    out = lyrics_from_text(TWINKLE, "Twinkle twinkle little star _")
    assert [n["lyric"] for n in out] == ["Twin-", "kle", "twin-", "kle", "lit-", "tle", "star"]
    out = lyrics_from_text(TWINKLE, "Twinkle twinkle lit _ tle")  # "_" holds a note
    assert [n["lyric"] for n in out][4:] == ["lit", HOLD, "tle"]
    out = lyrics_from_text(TWINKLE[:3], "how I wonder what")
    assert out[-1]["lyric"].startswith("won-")


def test_lines_and_join():
    notes = attach_lyrics(TWINKLE, WORDS)
    lines = lines_from_notes(notes)
    assert lines[0]["text"] == "Twinkle twinkle little star,"
    assert join_lyrics(["how", "I", "won-", "der", HOLD]) == "how I wonder"


def test_harmony_parts_inherit_syllables():
    melody = attach_lyrics(TWINKLE, WORDS)
    chords = ["C", "C", "C", "C", "F", "F", "C", "C"]
    for style in ("parallel", "voice_led", "contrary"):
        part = harmony_parts(melody, chords, {"low": 48, "high": 76}, style=style)["third_above"]
        sung = lyric_for_harmony(part, melody)
        assert [n["lyric"] for n in sung] == [n["lyric"] for n in melody]
    pad = harmony_parts(melody, chords, {"low": 48, "high": 76}, style="pad")["sixth_below"]
    assert any(n["lyric"] == "ooh" for n in lyric_for_harmony(pad, melody))


def test_whisper_style_timing_errors_are_corrected():
    # Song starts 1 s in; Whisper stamps the first word at 0.0 and the rest 0.4 s early.
    late = [dict(n, t0=n["t0"] + 1.0, t1=n["t1"] + 1.0) for n in TWINKLE]
    words = [Word("Twinkle", 0.0, 0.55), Word("twinkle", 1.6, 2.5), Word("little", 2.6, 3.5), Word("star,", 3.6, 4.5)]
    out = attach_lyrics(late, words)
    assert [n["lyric"] for n in out] == ["Twin-", "kle", "twin-", "kle", "lit-", "tle", "star,"]


def test_more_words_than_notes_keeps_word_order():
    # Fast speech-like delivery: 6 words, 3 notes.
    notes = _notes([(60, 0, 1), (62, 1, 1), (64, 2, 1)])
    words = [Word("how", 0.0, 0.15), Word("I", 0.2, 0.3), Word("wonder", 0.32, 0.5),
             Word("what", 0.55, 0.7), Word("you", 0.75, 0.9), Word("are", 1.0, 1.4)]
    out = attach_lyrics(notes, words)
    sung = " ".join(n["lyric"].replace("-", "") for n in out if n["lyric"] != HOLD)
    assert sung.replace("  ", " ").split() == ["how", "I", "wonder", "what", "you", "are"][: len(sung.split())]
    assert "how" in sung and "are" in sung
