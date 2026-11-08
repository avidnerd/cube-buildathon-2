"""Tests for the PLACEHOLDER test UI's API layer (placeholder_ui/server.py). Testing only."""
import pytest

from placeholder_ui import server as app


def test_api_returns_counter_for_piano_style_input():
    text = "\\key c \\major \\time 4/4 \\tempo 4 = 100\nc'4 c'4 g'4 g'4 | a'4 a'4 g'2 |"
    r = app.api_counter({"lily": text, "voice": "alto"})
    assert r["counter"] and r["melody"] and r["chords"]
    assert r["ly"].startswith('\\version') and "|" in r["bare"]
    assert r["key"] == "C major" and not r["key_detected"]


def test_api_detects_key_when_auto():
    r = app.api_counter({"lily": "\\time 3/4 \\tempo 4 = 90\nf'4 g'4 a'4 | bes'2 a'4 | g'4 f'2 |"})
    assert r["key_detected"]


@pytest.mark.parametrize("payload", [{"lily": ""}, {"lily": "r1 r1"}, {"lily": "c'4", "voice": "kazoo"}])
def test_api_rejects_bad_input(payload):
    with pytest.raises(ValueError):
        app.api_counter(payload)
