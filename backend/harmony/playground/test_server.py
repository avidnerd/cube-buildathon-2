import numpy as np
import pytest

from backend.harmony.playground.server import api_options, api_transcribe
from backend.harmony.test_reharmonize import TWINKLE
from backend.harmony.test_transcribe import SR, synth_voice
from backend.harmony.test_transcribe import TWINKLE as SUNG

VOICE = {"low": 52, "high": 76, "strongLow": 55, "strongHigh": 72}


def test_record_to_options_end_to_end():
    y, offset = synth_voice(SUNG, 96)
    tr = api_transcribe({"sr": [str(SR)], "bpm": ["96"], "offset": [str(offset)]}, y.astype("<f4").tobytes())
    assert [n["pitch"] for n in tr["notes"]] == [p for p, _, _ in SUNG]
    melody = [{k: n[k] for k in ("pitch", "start", "duration")} for n in tr["notes"]]
    out = api_options({"melody": melody, "voice": VOICE})
    assert out["base"][:4] == ["C", "C", "C", "C"] and out["base"][-1] == "C"
    assert [p["name"] for p in out["paths"]] == ["Plain", "Lush", "Twist"]
    assert len({tuple(p["chords"]) for p in out["paths"]}) == 3
    for p in out["paths"]:
        for style in p["harmony"].values():
            for track in (style["third_above"], style["sixth_below"]):
                assert all(VOICE["low"] <= n["pitch"] <= VOICE["high"] for n in track)


def test_options_respect_locks_in_every_option():
    out = api_options({"melody": TWINKLE, "voice": VOICE, "locks": {"4": "Dm7", "5": "Dm7"}})
    assert all(p["chords"][4:6] == ["Dm7", "Dm7"] for p in out["paths"])


def test_transcribe_rejects_silence_and_short_audio():
    with pytest.raises(ValueError, match="didn't hear"):
        api_transcribe({"sr": [str(SR)], "bpm": ["90"]}, np.zeros(SR * 2, "<f4").tobytes())
    with pytest.raises(ValueError, match="too short"):
        api_transcribe({"sr": [str(SR)], "bpm": ["90"]}, np.zeros(100, "<f4").tobytes())
