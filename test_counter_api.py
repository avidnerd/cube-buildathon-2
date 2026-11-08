"""Tests for counter_api.py, the JSON bridge used by the web app (src/counterMelody.js)."""
import pytest

import counter_api as api
from lily import KeySig

TWINKLE = [{"midi": m, "start": float(i), "duration": 1.0}
           for i, m in enumerate([60, 60, 67, 67, 69, 69])] + [{"midi": 67, "start": 6.0, "duration": 2.0}]


@pytest.mark.parametrize("name,expected", [
    ("C", KeySig(0, 0, "major")), ("F#", KeySig(3, 1, "major")), ("Db", KeySig(1, -1, "major")),
    ("Am", KeySig(5, 0, "minor")), ("Ebm", KeySig(2, -1, "minor")), ("C#m", KeySig(0, 1, "minor")),
])
def test_key_names_match_the_web_app(name, expected):
    assert api.key_from_name(name) == expected


def test_counter_from_json_melody():
    r = api.api_counter({"notes": TWINKLE, "key": "C", "meter": "4/4", "bpm": 100, "voice": "tenor"})
    assert r["counter"] and r["key"] == "C major" and r["clef"] == "treble-8"
    assert all(set(n) == {"midi", "start", "duration"} for n in r["counter"])
    ends = [n["start"] + n["duration"] for n in r["counter"]]
    assert all(b["start"] >= a - 1e-9 for a, b in zip(ends, r["counter"][1:]))   # monophonic
    assert all(48 <= n["midi"] <= 69 for n in r["counter"])                        # tenor range


def test_detects_key_when_missing_and_supports_other_meters():
    r = api.api_counter({"notes": TWINKLE[:6], "meter": "3/4", "bpm": 90})
    assert r["counter"] and r["voice"] == "alto"


@pytest.mark.parametrize("payload", [
    {}, {"notes": []}, {"notes": [{"midi": 60.5, "start": 0, "duration": 1}]},
    {"notes": [{"midi": 60, "start": -1, "duration": 1}]}, {"notes": TWINKLE, "meter": "7/8"},
    {"notes": TWINKLE, "voice": "kazoo"}, {"notes": TWINKLE, "key": "H"}, {"notes": TWINKLE, "bpm": 0},
])
def test_rejects_bad_input(payload):
    with pytest.raises(ValueError):
        api.api_counter(payload)
