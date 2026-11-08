from types import SimpleNamespace as NS

from backend.harmony.melody_chords import chord_at_fn, infer
from backend.harmony.transcribe import fold_scoops


def _mel(pitches, dur=1.0):
    return [{"pitch": p, "t0": i * dur, "t1": (i + 1) * dur} for i, p in enumerate(pitches)]


def test_one_chord_per_note_and_chord_holds_its_melody_notes():
    mel = _mel([60, 64, 67, 65, 69, 72, 67, 71, 74, 72, 67, 60])
    chords = infer(mel, (0, "major"))
    assert len(chords) == len(mel)
    fit = sum(n["pitch"] % 12 in c.tones for n, c in zip(mel, chords))
    assert fit >= 0.7 * len(mel)


def test_chord_at_follows_note_times():
    mel = _mel([60, 65])
    chords = infer(mel, (0, "major"))
    at = chord_at_fn(mel, chords)
    assert at(0.5) == chords[0] and at(1.5) == chords[1] and at(-1) == chords[0]


def test_scoop_outside_the_key_lands_on_the_note_it_leads_to():
    raw = [NS(t0=0.0, t1=0.17), NS(t0=0.18, t1=1.0), NS(t0=1.0, t1=1.1), NS(t0=1.4, t1=2.0)]
    assert fold_scoops([51, 52, 51, 50], raw, (9, "major")) == [52, 52, 51, 50]
