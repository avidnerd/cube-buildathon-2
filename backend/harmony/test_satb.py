import numpy as np
import pytest

from backend.harmony.reharmonize import parse_chord
from backend.harmony.satb import RANGES, VOICES, plan_satb


def _song():
    pitches = [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60, 64, 67, 72, 71, 67]
    mel = [{"pitch": p, "t0": 0.5 * i, "t1": 0.5 * i + 0.45, "start": i, "duration": 1, "lyric": f"s{i}"} for i, p in enumerate(pitches)]
    prog = ["C", "F", "G", "C"]
    return mel, lambda t: parse_chord(prog[min(3, int(t / 2.0))])


@pytest.mark.parametrize("where", ["soprano", "tenor"])
def test_four_ordered_voices_in_range_on_the_leads_timing(where):
    mel, chords = _song()
    out = plan_satb(mel, chords, (0, "major"), where)
    for k, n in enumerate(mel):
        row = [out[v][k]["pitch"] for v in VOICES]
        assert row[0] >= row[1] >= row[2] >= row[3], row
        for v in VOICES:
            assert (out[v][k]["t0"], out[v][k]["t1"], out[v][k]["lyric"]) == (n["t0"], n["t1"], n["lyric"])
    for v in VOICES:
        if v != where:
            lo, hi = RANGES[v]
            assert all(lo <= h["pitch"] <= hi for h in out[v]), v
    # the melody voice sings the tune, in an octave
    assert len({out[where][k]["pitch"] - n["pitch"] for k, n in enumerate(mel)}) == 1


def test_chords_are_complete_and_bass_is_on_the_root():
    mel, chords = _song()
    out = plan_satb(mel, chords, (0, "major"))
    complete = roots = 0
    for k, n in enumerate(mel):
        ch = chords(0.5 * (n["t0"] + n["t1"]))
        pcs = {out[v][k]["pitch"] % 12 for v in VOICES}
        third = (ch.root + ch.intervals[1]) % 12
        complete += ch.root in pcs and third in pcs
        roots += out["bass"][k]["pitch"] % 12 == ch.root
    assert complete >= 0.75 * len(mel) and roots >= 0.8 * len(mel)  # passing notes may thin a chord briefly


def test_no_parallel_octaves_and_fifths_and_inner_voices_move():
    mel, chords = _song()
    out = plan_satb(mel, chords, (0, "major"))
    bad = 0
    for k in range(1, len(mel)):
        for a in range(4):
            for b in range(a + 1, 4):
                x0, x1 = out[VOICES[a]][k - 1]["pitch"], out[VOICES[a]][k]["pitch"]
                y0, y1 = out[VOICES[b]][k - 1]["pitch"], out[VOICES[b]][k]["pitch"]
                if x1 != x0 and np.sign(x1 - x0) == np.sign(y1 - y0) and abs(x0 - y0) % 12 == abs(x1 - y1) % 12 and abs(x1 - y1) % 12 in (0, 7):
                    bad += 1
    assert bad <= 1
    for v in ("alto", "tenor"):
        holds = sum(a["pitch"] == b["pitch"] for a, b in zip(out[v], out[v][1:]))
        assert holds <= 6, (v, [h["pitch"] for h in out[v]])
