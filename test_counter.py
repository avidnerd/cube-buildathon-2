"""Tests for the counter-melody generator (counter.py)."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time

import pytest

import counter as C
import lily

SAMPLES = sorted(glob.glob("samples/*.ly"))
VOICES = sorted(C.VOICES)
_cache: dict = {}


def load(path: str) -> lily.Score:
    with open(path, encoding="utf-8") as fh:
        return lily.parse(fh.read())


def gen(path: str, voice: str = "alto", **kw) -> C.Result:
    key = (path, voice, tuple(sorted(kw.items())))
    if key not in _cache:
        _cache[key] = C.generate(load(path), voice, **kw)
    return _cache[key]


def bar_warnings(music: str, meter: lily.Meter) -> list[str]:
    head = f"\\time {meter.num}/{meter.den} "
    if meter.pickup:
        head += f"\\partial {lily.duration_string(meter.pickup)} "
    s = lily.parse(head + music)
    total = sum(n.dur for n in s.notes)
    warns = [w for w in s.warnings if w.startswith("bar")]
    if abs((total - meter.pickup) / meter.bar_len - round((total - meter.pickup) / meter.bar_len)) > 1e-6:
        warns.append(f"total length {total} is not a whole number of bars")
    return warns


# --- hard rules, range, determinism ------------------------------------------

@pytest.mark.parametrize("voice", VOICES)
@pytest.mark.parametrize("path", SAMPLES)
def test_no_hard_rule_violations(path, voice):
    r = gen(path, voice)
    assert C.hard_violations(r.ctx, r.counter) == []
    assert any(n.midi is not None for n in r.counter)


@pytest.mark.parametrize("voice", VOICES)
@pytest.mark.parametrize("path", SAMPLES)
def test_within_voice_range(path, voice):
    r = gen(path, voice)
    v = C.VOICES[voice]
    assert all(v.low <= n.midi <= v.high for n in r.counter if n.midi is not None)


@pytest.mark.parametrize("path", SAMPLES)
def test_good_quality_without_fallback(path):
    r = gen(path)
    assert not r.fallback
    assert r.quality >= C.WEIGHTS["quality_min"]


@pytest.mark.parametrize("path", SAMPLES)
def test_deterministic(path):
    score = load(path)
    a, b = C.generate(score), C.generate(load(path))
    assert [(n.midi, n.start, n.dur) for n in a.counter] == [(n.midi, n.start, n.dur) for n in b.counter]
    assert C.render(a, score, "x") == C.render(b, score, "x")


# --- rhythm independence --------------------------------------------------------

@pytest.mark.parametrize("path", SAMPLES)
def test_independent_onsets_active_style(path):
    """At least 30% of counter onsets fall where the melody has no onset (active style)."""
    r = gen(path)
    if r.style == "active":
        assert C.independence(r.melody, r.counter) >= 0.3
    forced = gen(path, style="active")
    assert C.independence(forced.melody, forced.counter) >= 0.3


def test_style_choice():
    assert gen("samples/twinkle.ly").style == "calm"            # busy quarter notes
    assert gen("samples/amazing_grace.ly").style == "active"    # long notes


def test_motif_echo_is_used_and_safe():
    r = gen("samples/amazing_grace.ly")
    assert r.echo and not C.hard_violations(r.ctx, r.counter)


# --- output bars ------------------------------------------------------------------

@pytest.mark.parametrize("path", SAMPLES)
def test_output_bars_complete(path):
    score = load(path)
    r = gen(path)
    ly, bare = C.render(r, score, "x")
    assert bar_warnings(bare, r.meter) == []
    for name in ("melody", "counter"):
        block = re.search(name + r" = \{(.*?)\n\}", ly, re.S).group(1)
        assert bar_warnings(block, r.meter) == []


@pytest.mark.parametrize("path", SAMPLES)
def test_output_file_contents(path):
    score = load(path)
    r = gen(path)
    ly, _ = C.render(r, score, "x")
    assert ly.startswith('\\version "2.24.0"')
    assert "% meta: key=" in ly and "style=" in ly and "quality=" in ly and "fallback=" in ly
    assert "\\new ChordNames \\chordmode" in ly
    assert ly.count("\\new Staff") == 2
    assert f"\\key {r.key.lily()}" in ly
    assert f"\\time {r.meter.num}/{r.meter.den}" in ly
    assert f"\\tempo {score.tempo_unit} = {score.tempo_bpm}" in ly
    # counter part parses back to exactly the generated notes
    block = re.search(r"counter = \{(.*?)\n\}", ly, re.S).group(1)
    back = lily.parse(block).notes
    got = [(n.midi, n.start, n.dur) for n in back if n.midi is not None]
    assert got == [(n.midi, n.start, n.dur) for n in r.counter if n.midi is not None]


def test_clefs_per_voice():
    score = load("samples/twinkle.ly")
    for voice, clef in (("tenor", '\\clef "treble_8"'), ("bass", "\\clef bass"), ("alto", "\\clef treble")):
        ly, _ = C.render(gen("samples/twinkle.ly", voice), score, "x")
        assert clef in ly.split("counter = {")[1]


def test_flat_and_minor_spelling():
    ly, bare = C.render(gen("samples/scarborough_fair.ly"), load("samples/scarborough_fair.ly"), "x")
    assert "cis" in bare and "des" not in bare          # leading tone of D minor
    r = gen("samples/frere_jacques_nokey.ly")
    _, bare = C.render(r, load("samples/frere_jacques_nokey.ly"), "x")
    assert "ais" not in bare                             # flats in a flat key


# --- ranking, key detection, fallback ---------------------------------------------

@pytest.mark.parametrize("path", SAMPLES)
def test_rank_two_differs(path):
    r1, r2 = gen(path), gen(path, rank=2)
    assert [(n.midi, n.start) for n in r1.counter] != [(n.midi, n.start) for n in r2.counter]
    assert C.hard_violations(r2.ctx, r2.counter) == []


def test_key_detection():
    r = gen("samples/frere_jacques_nokey.ly")
    assert r.key.name() == "F major" and r.key_conf >= C.WEIGHTS["key_conf_min"]
    for path in SAMPLES:
        s = load(path)
        if s.key is not None:
            key, _ = C.detect_key(C.clean(s.notes))
            assert key.tonic_pc == s.key.tonic_pc or key.scale_pcs == s.key.scale_pcs, path


@pytest.mark.parametrize("voice", VOICES)
@pytest.mark.parametrize("path", SAMPLES)
def test_fallback_always_passes_hard_rules(path, voice):
    r = C.generate(load(path), voice, force_fallback=True)
    assert r.fallback
    assert C.hard_violations(r.ctx, r.counter) == []


def test_low_key_confidence_uses_fallback():
    # an even chromatic scale has no tonal centre at all
    r = C.generate(lily.parse("c'4 cis' d' dis' | e' f' fis' g' | gis' a' ais' b'"))
    assert r.key_conf < C.WEIGHTS["key_conf_min"] and r.fallback
    assert C.hard_violations(r.ctx, r.counter) == []


def test_clean_quantizes_and_merges():
    notes = [lily.Note(60, 0.0, 0.98), lily.Note(60, 1.02, 0.98), lily.Note(62, 2.0, 0.1),
             lily.Note(64, 2.1, 1.9)]
    out = C.clean(notes)
    assert [(n.midi, n.start, n.dur) for n in out] == [(60, 0.0, 2.0), (64, 2.0, 2.0)]


# --- speed ----------------------------------------------------------------------

@pytest.mark.parametrize("path", SAMPLES)
def test_runtime_under_one_second(path):
    score = load(path)
    t = time.perf_counter()
    C.generate(score)
    assert time.perf_counter() - t < 1.0


@pytest.mark.parametrize("style", ["calm", "active"])
def test_runtime_32_bars(style):
    bars = "d'2 d'4 | a'2 a'4 | e'4. f'8 e'4 | d'2. | r4 a' c'' | d''2 c''4 | a'4 bes' g' | a'2. | "
    text = "\\key d \\minor \\time 3/4 " + bars * 4
    score = lily.parse(text)
    assert len(score.notes) > 0
    t = time.perf_counter()
    r = C.generate(score, style=style)
    assert time.perf_counter() - t < 1.0
    assert C.hard_violations(r.ctx, r.counter) == []


# --- CLI and MIDI -----------------------------------------------------------------

def test_cli_writes_ly_and_midi(tmp_path, capsys):
    pytest.importorskip("mido")
    out = tmp_path / "out"
    assert C.main(["samples/twinkle.ly", "--out", str(out), "--midi"]) == 0
    for suffix in ("_counter.ly", "_original.mid", "_counter.mid", "_both.mid"):
        assert (out / f"twinkle{suffix}").exists()
    import mido
    both = mido.MidiFile(str(out / "twinkle_both.mid"))
    assert len(both.tracks) == 3
    assert "% counter-melody alone:" in capsys.readouterr().out


def test_cli_text_input(tmp_path, capsys):
    assert C.main(["--text", r"\relative c' { c4 d e f | g1 }", "--voice", "tenor"]) == 0
    assert "\\version" in capsys.readouterr().out


# --- optional: real LilyPond compile ----------------------------------------------

@pytest.mark.skipif(shutil.which("lilypond") is None, reason="lilypond binary not installed")
@pytest.mark.parametrize("path", SAMPLES)
def test_lilypond_compiles(path, tmp_path):
    score = load(path)
    ly, _ = C.render(gen(path), score, os.path.basename(path))
    src = tmp_path / "x.ly"
    src.write_text(ly, encoding="utf-8")
    res = subprocess.run(["lilypond", "-s", "-o", str(tmp_path / "x"), str(src)],
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    assert "error" not in res.stderr.lower()
