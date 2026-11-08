import numpy as np
import pytest

from backend.harmony.harmonizer import ARRANGEMENTS, plan_part, plan_parts, psola, render_part, shift_curve
from backend.harmony.reharmonize import parse_chord
from backend.harmony.tis import consonance, chroma_of, progression_tension
from backend.harmony.transcribe import yin

SR = 22050


def tone(f0, dur, sr=SR, vib=0.0):
    t = np.arange(int(dur * sr)) / sr
    f = f0 * 2 ** (vib * np.sin(2 * np.pi * 5.5 * t) / 1200)
    ph = 2 * np.pi * np.cumsum(f) / sr
    return sum((0.6 ** k) * np.sin((k + 1) * ph) for k in range(6)) * 0.3


def melody_notes(pitches, dur=0.5, gap=0.02, start=0.2):
    out, t = [], start
    for p in pitches:
        out.append({"pitch": p, "t0": t, "t1": t + dur - gap, "lyric": f"la{p}"})
        t += dur
    return out


# --- TIS --------------------------------------------------------------------

def test_tis_consonance_orders_intervals_like_ears():
    c = lambda iv: float(consonance(chroma_of([0, iv])))
    assert c(7) > c(4) > c(1)      # fifth > third > semitone
    assert c(3) > c(6)             # minor third > tritone


def test_progression_tension_ii_v_i_calmer_than_chromatic():
    C = lambda s: [parse_chord(x) for x in s]
    calm = progression_tension(C(["C", "F", "G", "C"]), 0, "major")
    tense = progression_tension(C(["C", "F#", "Db7", "B"]), 0, "major")
    assert calm < tense


# --- planning ---------------------------------------------------------------

VOICE = (48, 79, 50, 76)
C_CHORD = lambda t: parse_chord("C")


def test_parts_keep_the_leads_exact_timing_and_words():
    mel = melody_notes([60, 62, 64, 65, 67, 65, 64, 62, 60])
    chords = lambda t: parse_chord("C") if t < 2.0 else parse_chord("G7") if t < 3.5 else parse_chord("C")
    for arr in ARRANGEMENTS:
        parts = plan_parts(mel, chords, (0, "major"), VOICE, arr)
        for part in parts.values():
            assert [(h["t0"], h["t1"], h["lyric"]) for h in part] == [(m["t0"], m["t1"], m["lyric"]) for m in mel]


I_IV_V_I = lambda t: parse_chord(["C", "C", "F", "F", "G", "G", "C", "C"][min(7, int((t - 0.2) / 0.5))])


@pytest.mark.parametrize("side,target", [(+1, 3.5), (-1, 8.5)])
def test_scale_melody_gets_a_smooth_consonant_line(side, target):
    mel = melody_notes([60, 62, 64, 65, 67, 69, 71, 72])
    part = plan_part(mel, I_IV_V_I, (0, "major"), VOICE, side, target)
    ics = [abs(h["pitch"] - m["pitch"]) % 12 for h, m in zip(part, mel)]
    assert not set(ics) & {0, 1, 2, 10, 11}, ics                        # never doubles or rubs against the lead
    assert all(h["pitch"] % 12 in (0, 2, 4, 5, 7, 9, 11) for h in part)  # in key
    leaps = [abs(b["pitch"] - a["pitch"]) for a, b in zip(part, part[1:])]
    assert max(leaps) <= 5, leaps                                        # a singable line (a 4th at most)
    chords = [I_IV_V_I(0.5 * (m["t0"] + m["t1"])) for m in mel]
    on_tones = sum(h["pitch"] % 12 in c.tones for h, c in zip(part, chords))
    assert on_tones >= 6, [h["pitch"] for h in part]                     # consonant with the harmony


def test_follows_the_real_band_even_with_wrong_chord_labels():
    """The band plays C G Am F; the harmonizer is told it's C the whole time."""
    from backend.harmony.dissonance import Listener
    from backend.harmony.test_listen import synth_band

    band, start = synth_band(["C", "G", "Am", "F"], 60, sr=SR, beats_per_chord=2, drums=False)
    # lead sings chord tones/tensions, two notes per chord, on the real timing
    lead = [64, 67, 62, 67, 64, 69, 65, 69]
    mel = [{"pitch": p, "t0": start + i + 0.05, "t1": start + i + 0.9} for i, p in enumerate(lead)]
    hz = np.array([440 * 2 ** ((lead[min(7, max(0, int(t - start)))] - 69) / 12) for t in np.arange(0, 10, 0.01)])
    lis = Listener(band, SR, np.arange(0, 10, 0.01), hz)
    wrong = lambda t: parse_chord("C")
    real = [parse_chord(c) for c in ("C", "C", "G", "G", "Am", "Am", "F", "F")]
    for side, target in ((+1, 3.5), (-1, 8.5)):
        part = plan_part(mel, wrong, (0, "major"), VOICE, side, target,
                         scene_for=lambda n: lis.scene(n["t0"], n["t1"], n["pitch"]))
        fits = [h["pitch"] % 12 in c.tones for h, c in zip(part, real)]
        assert sum(fits) >= 7, ([h["pitch"] for h in part], fits)


def test_harmony_lands_on_chord_tones_on_long_notes():
    mel = melody_notes([64, 67, 72], dur=1.0)  # E G C over C major
    part = plan_part(mel, C_CHORD, (0, "major"), VOICE, +1, 3.5)
    assert all(h["pitch"] % 12 in (0, 4, 7) for h in part), [h["pitch"] for h in part]
    low = plan_part(mel, C_CHORD, (0, "major"), VOICE, -1, 8.5)
    assert all(h["pitch"] % 12 in (0, 4, 7) for h in low) and all(h["pitch"] < m["pitch"] for h, m in zip(low, mel))


def test_parts_stay_in_range():
    rng = np.random.default_rng(0)
    mel = melody_notes(list(rng.integers(55, 80, 40)), dur=0.3)
    for arr in ARRANGEMENTS:
        if arr.startswith("satb"):
            continue  # four separate singers, each with a standard voice range (test_satb.py)
        for part in plan_parts(mel, C_CHORD, (0, "major"), VOICE, arr).values():
            assert all(VOICE[0] <= h["pitch"] <= VOICE[1] for h in part)


# --- rendering --------------------------------------------------------------

def _f0_track(x, sr):
    times, f0, _, _ = yin(x, sr)
    return times, f0


@pytest.mark.parametrize("semis", [-9, -4, 3, 4, 7])
def test_psola_shifts_pitch_and_keeps_timing(semis):
    x = np.concatenate([np.zeros(int(0.3 * SR)), tone(220.0, 1.2, vib=30), np.zeros(int(0.3 * SR))])
    times, f0 = _f0_track(x, SR)
    y = psola(x, SR, times, f0, np.array([0.0, 2.0]), np.array([float(semis), float(semis)]))
    assert len(y) == len(x)
    _, f_out, _, _ = yin(y, SR)
    assert np.nanmedian(f_out) == pytest.approx(220.0 * 2 ** (semis / 12), rel=0.02)
    # Same on/off times: energy envelope lines up.
    env = lambda s: np.convolve(s ** 2, np.ones(441) / 441, mode="same") > 1e-3
    assert np.mean(env(x) == env(y)) > 0.97


def test_render_follows_each_notes_interval_with_glides():
    sr = SR
    x = np.concatenate([tone(220.0, 0.6), tone(246.94, 0.6)])  # A3 then B3, legato
    mel = [{"pitch": 57, "t0": 0.0, "t1": 0.6}, {"pitch": 59, "t0": 0.6, "t1": 1.2}]
    part = [{"pitch": 60}, {"pitch": 62}]                       # 3 semitones up both times
    times, f0 = _f0_track(x, sr)
    y = render_part(x, sr, times, f0, mel, part)
    t_out, f_out, _, _ = yin(y, sr)
    first = np.nanmedian(f_out[(t_out > 0.15) & (t_out < 0.45)])
    second = np.nanmedian(f_out[(t_out > 0.75) & (t_out < 1.05)])
    assert first == pytest.approx(261.63, rel=0.02) and second == pytest.approx(293.66, rel=0.02)
    # No dropouts at the note boundary (the "chopped" problem).
    seg = y[int(0.55 * sr): int(0.65 * sr)]
    frames = np.sqrt(np.mean(seg[: len(seg) // 100 * 100].reshape(-1, 100) ** 2, axis=1))
    assert frames.min() > 0.3 * frames.max()


def test_shift_curve_glides_between_notes():
    t, s = shift_curve([{"pitch": 60, "t0": 0, "t1": 1}, {"pitch": 60, "t0": 1, "t1": 2}],
                       [{"pitch": 64}, {"pitch": 63}])
    assert np.interp(0.5, t, s) == 4 and np.interp(1.5, t, s) == 3
    assert 3 < np.interp(1.0, t, s) < 4


def test_key_of_a_melody_that_dwells_on_the_third():
    """'Until I Found You' (B-flat major) hangs on D: correlation alone said D minor."""
    from backend.harmony.reharmonize import estimate_key
    prof = np.zeros(12)
    for pc, secs in {0: 2.2, 2: 4.9, 3: 4.0, 4: 0.26, 5: 3.8, 7: 2.5, 9: 2.5, 10: 1.0, 11: 0.07}.items():
        prof[pc] = secs
    assert estimate_key(prof) in ((10, "major"), (7, "minor"))  # B-flat major or its relative


def test_never_a_tritone_against_a_held_lead_note():
    mel = melody_notes([63, 62, 65, 63, 62], dur=0.6)  # E-flat neighbour tones, B-flat major
    for side, target in ((+1, 3.5), (-1, 8.5)):
        part = plan_part(mel, lambda t: parse_chord("Eb"), (10, "major"), VOICE, side, target)
        assert all(abs(h["pitch"] - m["pitch"]) % 12 not in (1, 2, 6, 10, 11) for h, m in zip(part, mel))


def test_style_learns_from_corrections_and_generalizes():
    """Teach 'join the melody on low pickups, then diatonic 3rds' on two phrases;
    it should then do that on a phrase it hasn't seen."""
    from backend.harmony.harmonizer import DEFAULT_WEIGHTS, agreement, fit_style, make_example

    sc = (0, 2, 4, 5, 7, 9, 11)
    def third_above(p):
        up = [q for q in range(p + 1, p + 6) if q % 12 in sc]
        return up[1]
    def phrase(pitches, start):
        mel = [{"pitch": p, "t0": start + 0.5 * i, "t1": start + 0.5 * i + 0.45} for i, p in enumerate(pitches)]
        gold = [p if i < 2 else third_above(p) for i, p in enumerate(pitches)]  # unison pickup, then 3rds
        return mel, gold
    chord = lambda t: parse_chord("C")
    exs = [make_example(*(lambda m, g: (m, chord, (0, "major"), VOICE, +1, 3.5, g))(*phrase(ps, s)))
           for ps, s in (([55, 57, 60, 62, 64, 62, 60], 0), ([55, 57, 64, 65, 67, 65, 64], 5))]
    test = make_example(*(lambda m, g: (m, chord, (0, "major"), VOICE, +1, 3.5, g))(*phrase([55, 57, 62, 64, 65, 64, 62], 10)))
    w = fit_style(exs)
    assert agreement([test], w) > agreement([test], DEFAULT_WEIGHTS)
    assert agreement([test], w) >= 0.7  # from just two short phrases


def test_classic_arrangement_spells_chords_not_octaves():
    mel = melody_notes([64, 65, 67, 69, 67, 65, 64], dur=0.6)
    parts = plan_parts(mel, C_CHORD, (0, "major"), VOICE, "classic")
    doubled = sum(h["pitch"] % 12 == l["pitch"] % 12 for h, l in zip(parts["high"], parts["low"]))
    assert doubled <= 1


def test_runs_hold_the_note_they_decorate():
    from backend.harmony.harmonizer import mirror_runs
    # held E, a quick run D-C-D, held E: the harmony holds its note through the run
    mel = [{"pitch": 64, "t0": 0.0, "t1": 0.6}, {"pitch": 62, "t0": 0.6, "t1": 0.7},
           {"pitch": 60, "t0": 0.7, "t1": 0.8}, {"pitch": 62, "t0": 0.8, "t1": 0.9}, {"pitch": 64, "t0": 0.9, "t1": 1.6}]
    part = [{"pitch": p} for p in (67, 65, 64, 65, 67)]
    assert [h["pitch"] for h in mirror_runs(mel, part)] == [67, 67, 67, 67, 67]


def test_harmony_sings_steady_notes_not_the_leads_slides():
    """The lead scoops into a note and wobbles; the harmony stays on its note."""
    sr = SR
    t = np.arange(int(1.2 * sr)) / sr
    cents = -150 * np.exp(-t / 0.12) + 40 * np.sin(2 * np.pi * 5.5 * t)     # scoop up + wide vibrato
    f = 220.0 * 2 ** (cents / 1200)
    ph = 2 * np.pi * np.cumsum(f) / sr
    x = sum((0.6 ** k) * np.sin((k + 1) * ph) for k in range(6)) * 0.3
    times, f0 = _f0_track(x, sr)
    mel = [{"pitch": 57, "t0": 0.0, "t1": 1.2}]
    y = render_part(x, sr, times, f0, mel, [{"pitch": 61}])                  # target C#4
    t_out, f_out, _, _ = yin(y, sr)
    sel = (t_out > 0.1) & (t_out < 1.1) & ~np.isnan(f_out)
    c = 1200 * np.log2(f_out[sel] / (440 * 2 ** ((61 - 69) / 12)))
    assert abs(np.median(c)) < 15                                             # on the note
    assert np.percentile(np.abs(c), 90) < 25                                  # the scoop and wobble are gone
    follow = render_part(x, sr, times, f0, mel, [{"pitch": 61}], follow_slides=True)
    _, f2, _, _ = yin(follow, sr)
    c2 = 1200 * np.log2(f2[sel] / (440 * 2 ** ((61 - 69) / 12)))
    assert np.percentile(np.abs(c2), 90) > 2 * np.percentile(np.abs(c), 90)  # (the old way copied them)


def test_lowering_pitch_has_no_gaps_between_cycles():
    """Shifting down used to leave dips between grains (buzz); grains now overlap by half."""
    x = tone(220.0, 1.0)
    times, f0 = _f0_track(x, SR)
    y = psola(x, SR, times, f0, np.array([0.0, 2.0]), np.array([-9.0, -9.0]))
    seg = y[int(0.3 * SR): int(0.7 * SR)]
    env = np.sqrt(np.convolve(seg ** 2, np.ones(64) / 64, mode="valid"))
    assert env.min() > 0.25 * env.max()


def test_denoise_and_polish_keep_the_voice():
    from backend.harmony.audio_fx import denoise, polish
    rng = np.random.default_rng(0)
    clean = np.concatenate([np.zeros(SR // 2), tone(220.0, 1.0), np.zeros(SR // 2)])
    noisy = clean + 0.02 * rng.standard_normal(len(clean))
    d = denoise(noisy, SR)
    quiet = slice(0, SR // 3)
    assert np.std(d[quiet]) < 0.5 * np.std(noisy[quiet])                  # hiss removed between phrases
    mid = slice(int(0.8 * SR), int(1.2 * SR))
    assert np.corrcoef(d[mid], clean[mid])[0, 1] > 0.95                  # the voice is untouched
    p = polish(d, SR)
    assert len(p) == len(d) and np.max(np.abs(p)) <= np.max(np.abs(d)) + 1e-9
