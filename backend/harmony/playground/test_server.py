import os

import numpy as np
import pytest

import io
import wave

from backend.harmony.playground.server import api_analyze, api_job, api_lyrics, api_options, api_render
from backend.harmony.transcribe import yin
from backend.harmony.test_listen import POP, synth_band
from backend.harmony.test_reharmonize import TWINKLE
from backend.harmony.test_transcribe import TWINKLE as SUNG
from backend.harmony.test_transcribe import synth_voice

VOICE = {"low": 52, "high": 76, "strongLow": 55, "strongHigh": 72}
SLOW = pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="runs Demucs + Whisper; set RUN_SLOW=1")


def _pcm(x):
    x = np.asarray(x, dtype=np.float64)
    return (np.clip(x / max(1.0, np.abs(x).max()), -1, 1) * 32767).astype("<i2").tobytes()


def _analyze(query, audio):
    job = api_analyze({k: [str(v)] for k, v in query.items()}, _pcm(audio), background=False)
    out = api_job(job["job"])
    assert out["done"] and out["error"] is None, out["error"]
    return out["result"]


def test_mic_recording_to_options():
    y, offset = synth_voice(SUNG, 96, sr=44100)
    res = _analyze({"sr": 44100, "channels": 1, "source": "mic", "bpm": 96, "offset": offset, "lyrics": 0}, y)
    assert [n["pitch"] for n in res["notes"]] == [p for p, _, _ in SUNG]
    assert res["has_music"] is False and res["chords"] is None
    out = api_options({"melody": res["notes"], "voice": VOICE, "beats": res["beats"]})
    assert out["base"][:4] == ["C", "C", "C", "C"] and out["base"][-1] == "C"
    assert [p["name"] for p in out["paths"]] == ["Plain", "Lush", "Twist"]
    assert len({tuple(p["chords"]) for p in out["paths"]}) == 3
    assert all(0 <= p["tension"] <= 1 for p in out["paths"])
    for p in out["paths"]:
        for parts in p["parts"].values():
            for part in parts.values():
                assert all(VOICE["low"] <= n["pitch"] <= VOICE["high"] for n in part)
                # Same notes, same real timing as the lead: they sing together.
                assert [(n["t0"], n["t1"]) for n in part] == [(n["t0"], n["t1"]) for n in res["notes"]]


def test_render_is_the_lead_singing_the_harmony():
    y, offset = synth_voice(SUNG, 96, sr=44100)
    job = api_analyze({"sr": ["44100"], "channels": ["1"], "source": ["mic"], "bpm": ["96"],
                       "offset": [str(offset)], "lyrics": ["0"]}, _pcm(y), background=False)
    res = api_job(job["job"])["result"]
    out = api_options({"melody": res["notes"], "voice": VOICE, "beats": res["beats"]})
    part = out["paths"][0]["parts"]["classic"]["high"]
    wav = api_render({"job": job["job"], "melody": res["notes"], "part": part})
    with wave.open(io.BytesIO(wav)) as w:
        sr = w.getframerate()
        h = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    assert abs(len(h) - len(y)) < sr * 0.01                     # same length = same timeline
    times, f0, _, _ = yin(h, sr)
    for n, hp in zip(res["notes"], part):                        # each note at its harmony pitch, on time
        mid = (times > n["t0"] + 0.08) & (times < n["t1"] - 0.08)
        if mid.sum() < 3:
            continue
        got = 69 + 12 * np.log2(np.nanmedian(f0[mid]) / 440) - res["tuning_cents"] / 100
        assert abs(got - hp["pitch"]) < 0.5, (n, hp["pitch"], got)


def test_detected_chords_are_the_plain_option():
    detected = ["C"] * 4 + ["F", "F", "C", "C", "F", "F", "C", "C", "G", "G", "C", "C"]
    out = api_options({"melody": TWINKLE, "chords": detected, "voice": VOICE})
    assert out["paths"][0]["chords"] == detected
    # Even when the melody would rather have something else there.
    odd = ["Am"] * 4 + detected[4:]
    out = api_options({"melody": TWINKLE, "chords": odd, "voice": VOICE, "novelty": 0.8})
    assert out["paths"][0]["name"] == "Plain" and out["paths"][0]["chords"] == odd


def test_options_respect_locks_in_every_option():
    out = api_options({"melody": TWINKLE, "voice": VOICE, "locks": {"4": "Dm7", "5": "Dm7"}})
    assert all(p["chords"][4:6] == ["Dm7", "Dm7"] for p in out["paths"])


def test_harmony_parts_carry_the_lyrics():
    melody = api_lyrics({"notes": [dict(n, t0=n["start"] / 2, t1=(n["start"] + 1) / 2) for n in TWINKLE],
                         "text": "Twinkle twinkle little star how I wonder what you are"})["notes"]
    out = api_options({"melody": melody, "voice": VOICE, "beats": [i * 0.5 for i in range(40)]})
    for parts in out["paths"][1]["parts"].values():
        for part in parts.values():
            assert [n["lyric"] for n in part] == [n["lyric"] for n in melody]


def test_lyrics_endpoint_builds_lines():
    notes = [dict(n, t0=0, t1=0) for n in TWINKLE]
    out = api_lyrics({"notes": notes, "text": "Twinkle twinkle little star, how I wonder what you are"})
    assert out["lines"][0]["text"].startswith("Twinkle twinkle little star,")


def test_rejects_silence():
    job = api_analyze({"sr": ["16000"], "channels": ["1"], "source": ["mic"], "bpm": ["90"], "lyrics": ["0"]},
                      np.zeros(32000, "<i2").tobytes(), background=False)
    assert "didn't hear" in api_job(job["job"])["error"]


@SLOW
def test_song_upload_full_pipeline(tmp_path):
    """Real voice (macOS speech) over a synthetic band, through Demucs + Whisper.

    A synthetic 'singer' won't do here: Demucs is trained on human voices and
    files a buzzy synth tone under 'other'. Pitch accuracy is covered by the
    transcriber's own tests; this checks separation, beats, chords and lyrics.
    """
    import shutil
    import subprocess
    import wave

    if not shutil.which("say") or not shutil.which("afconvert"):
        pytest.skip("needs macOS say/afconvert")
    sr = 44100
    aiff, wav = tmp_path / "v.aiff", tmp_path / "v.wav"
    subprocess.run(["say", "-o", str(aiff), "Twinkle twinkle little star, how I wonder what you are. "
                    "Up above the world so high, like a diamond in the sky."], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{sr}", "-c", "1", str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        voice = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    band, start = synth_band(POP, 100, sr=sr)
    mix = np.zeros(max(len(band), len(voice) + sr))
    mix[: len(band)] += 0.5 * band
    mix[sr // 2: sr // 2 + len(voice)] += 1.2 * voice

    res = _analyze({"sr": sr, "channels": 1, "source": "upload", "lyrics": 1}, mix)
    assert res["has_music"] is True
    assert res["bpm"] == pytest.approx(100, rel=0.03)
    assert {"C", "G", "Am", "F"} <= set(res["chords"])
    heard = " ".join(w["text"].lower() for w in res["words"])
    for word in ("twinkle", "star", "wonder", "diamond", "sky"):
        assert word in heard
    assert any(n["lyric"] for n in res["notes"])

    # A voice on its own is recognized as having no music.
    solo = _analyze({"sr": sr, "channels": 1, "source": "upload", "bpm": 100, "lyrics": 0}, voice)
    assert solo["has_music"] is False and solo["chords"] is None
