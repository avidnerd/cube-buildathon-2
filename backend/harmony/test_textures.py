import numpy as np

from backend.harmony.reharmonize import Chord
from backend.harmony.textures import diatonic, overlap_stats, phrases, place, plan_textures

SPB = 0.5
KEY = (0, "major")
VOICE = (48, 79, 50, 76)
BEATS = [i * SPB for i in range(80)]


def mel(spec, start=0.0):
    out, b = [], start
    for p, d in spec:
        if p is not None:
            out.append({"pitch": p, "start": b, "duration": d, "t0": b * SPB, "t1": (b + d) * SPB - 0.02, "lyric": ""})
        b += d
    return out


# Reference only (to check the scoring): a tune known to work as a round, 2 bars apart.
FRERE = [(60, 1), (62, 1), (64, 1), (60, 1)] * 2 + [(64, 1), (65, 1), (67, 2)] * 2 + \
        [(67, .5), (69, .5), (67, .5), (65, .5), (64, 1), (60, 1)] * 2 + [(60, 1), (55, 1), (60, 2)] * 2
C = lambda t: Chord(0, "maj")  # noqa: E731


def test_diatonic_moves_by_scale_steps():
    assert diatonic(60, 2, KEY) == 64 and diatonic(64, 2, KEY) == 67 and diatonic(60, -2, KEY) == 57
    assert diatonic(60, 7, KEY) == 72 and diatonic(61, 2, KEY) == 65   # C# keeps its sharp


def test_round_finds_the_two_bar_entry():
    tex = plan_textures(mel(FRERE), C, KEY, VOICE, BEATS, 4, 0)
    second = [n for n in tex["round"]["second"] if not n.get("rest")]
    assert abs(second[0]["delay"] - 8 * SPB) < 1e-6
    assert second[0]["start"] == 8 and second[0]["pitch"] == 60


def test_canon_is_consonant_with_the_lead():
    m = mel(FRERE)
    tex = plan_textures(m, C, KEY, VOICE, BEATS, 4, 0)
    canon = tex["canon"]["canon"]
    s = overlap_stats([(n["t0"], n["t1"], n["pitch"]) for n in m], [(n["t0"], n["t1"], n["pitch"]) for n in canon])
    assert s["clash"] / s["overlap"] < 0.2 and canon[0]["delay"] > 0


def test_echo_answers_in_the_rests():
    m = mel([(60, 1), (62, 1), (64, 2), (None, 4), (67, 1), (65, 1), (64, 2), (None, 4)])
    assert len(phrases(m, SPB)) == 2
    echo = plan_textures(m, C, KEY, VOICE, BEATS, 4, 0)["echo"]["echo"]
    sung = [n for n in echo if not n.get("rest")]
    assert sung
    lead = [(n["t0"], n["t1"]) for n in m]
    for n in sung:   # never on top of the lead
        assert all(n["t0"] >= b - 1e-6 or n["t1"] <= a + 1e-6 for a, b in lead)


def test_riff_repeats_each_bar_on_chord_tones():
    m = mel(FRERE)
    tex = plan_textures(m, lambda t: Chord(0, "maj") if (t // 2) % 2 == 0 else Chord(7, "maj"), KEY, VOICE, BEATS, 4, 0)
    riff, bass = tex["riff"]["riff"], tex["riff"]["bass"]
    assert all(n["synth"] for n in riff + bass)
    downbeats = [n for n in riff if n["start"] % 4 == 0]
    assert len(downbeats) == 8
    for n in downbeats:
        ch = Chord(0, "maj") if (n["t0"] // 2) % 2 == 0 else Chord(7, "maj")
        assert n["pitch"] % 12 in ch.tones
    assert [n["pitch"] % 12 for n in bass if n["start"] % 4 == 0][:2] == [0, 7]


def test_place_moves_and_drops_notes():
    sr = 1000
    y = np.ones(2000, dtype=np.float32)
    m = [{"t0": 0.1, "t1": 0.3}, {"t0": 0.5, "t1": 0.7}]
    out = place(y, sr, m, [{"delay": 1.0}, {"rest": True, "delay": 0.0}])
    assert out[:1000].max() == 0 and out[1150:1300].min() > 0.99 and out[1500:].max() == 0
    assert place(y, sr, m, [{}, {}]) is y


def test_riff_never_starts_before_the_recording():
    m = mel(FRERE, start=2.0)          # pickup: the first bar starts before the take
    tex = plan_textures(m, C, KEY, VOICE, [0.25 + i * SPB for i in range(80)], 4, 3)
    assert all(n["t0"] >= 0 for p in tex["riff"].values() for n in p)


def test_riff_and_bass_are_the_joint_optimum():
    """No other choice of notes for the two lines scores better: the solver's
    answer beats thousands of random alternatives and every single-note change."""
    from backend.harmony.optimal import two_voice
    from backend.harmony.textures import riff_objective, riff_problem
    m = mel(FRERE)
    ch = lambda t: Chord(0, "maj") if (t // 2) % 2 == 0 else Chord(7, "maj")  # noqa: E731
    prob = riff_problem(m, ch, KEY, VOICE, BEATS, 4, 0)
    voices, events, edge, pair = prob
    choice, cost = two_voice(events, [[r["node"] for r in v] for v in voices], edge, pair)
    assert np.isclose(riff_objective(prob, choice), cost)
    for v in (0, 1):
        for k, r in enumerate(voices[v]):
            for x in range(len(r["cands"])):
                alt = [list(choice[0]), list(choice[1])]
                alt[v][k] = x
                assert riff_objective(prob, alt) >= cost - 1e-9
    rng = np.random.default_rng(0)
    for _ in range(300):
        alt = [[int(rng.integers(len(r["cands"]))) for r in voices[v]] for v in (0, 1)]
        assert riff_objective(prob, alt) >= cost - 1e-9


def test_round_and_canon_are_the_best_of_every_option():
    from backend.harmony.textures import CANON_STEPS, MAX_CLASH_SHARE, OCTAVES, _moved, canon_objective
    m = mel(FRERE)
    canon = plan_textures(m, C, KEY, VOICE, BEATS, 4, 0)["canon"]["canon"]
    chosen, _ = canon_objective(canon, m, C, VOICE)
    rng = np.random.default_rng(0)
    for steps in CANON_STEPS:
        for db in range(1, 9):
            for o in OCTAVES:
                part = _moved(m, steps, db * SPB, db, KEY, o)
                for _ in range(4):      # every way of leaving notes out is no better
                    drop = rng.random(len(part)) < 0.2
                    alt = [{**n, "rest": True} if d else n for n, d in zip(part, drop)]
                    c, share = canon_objective(alt, m, C, VOICE)
                    if share <= MAX_CLASH_SHARE:
                        assert chosen <= c + 1e-9


def test_canon_breathes_over_a_rub():
    """A canon note that would sit a semitone against a held lead note is left out;
    consonant notes are all kept."""
    from backend.harmony.textures import _prune_canon
    m = mel([(60, 2), (64, 2), (67, 2), (65, 2)])
    part = [{**n, "pitch": p, "t0": n["t0"], "t1": n["t1"]} for n, p in zip(m, (64, 65, 71, 69))]   # 65 vs 64: a rub
    pruned = _prune_canon(part, m, C, VOICE)
    assert [bool(n.get("rest")) for n in pruned] == [False, True, False, False]


def test_echo_takes_the_best_answer_for_each_phrase():
    from backend.harmony.textures import _echo_options
    m = mel([(60, 1), (62, 1), (64, 2), (None, 4), (67, 1), (65, 1), (64, 2), (None, 4)])
    echo = plan_textures(m, C, KEY, VOICE, BEATS, 4, 0)["echo"]["echo"]
    ps = phrases(m, SPB)
    for k, ph in enumerate(ps):
        end = m[ph[-1]]["t1"]
        nxt = m[ps[k + 1][0]]["t0"] if k + 1 < len(ps) else end + 8 * SPB
        best = min(_echo_options(m, ph, nxt, SPB, BEATS, KEY, VOICE, C), key=lambda o: o[0])
        sung = [i for i in ph if not echo[i].get("rest")]
        assert sung == list(best[1]) and abs(echo[sung[0]]["delay"] - best[2]) < 1e-6


def test_no_voice_below_e2_for_a_low_singer():
    from backend.harmony.harmonizer import LOWEST_VOICE, plan_parts
    low = [(p - 19, d) for p, d in FRERE]           # a bass singing around F2
    m = mel(low)
    tex = plan_textures(m, C, KEY, (34, 60, 36, 58), BEATS, 4, 0)
    for name in ("round", "canon", "echo"):
        for part in tex.get(name, {}).values():
            assert all(n["pitch"] >= LOWEST_VOICE for n in part if not n.get("rest")), name
    parts = plan_parts(m, C, KEY, (34, 60, 36, 58), "classic")
    assert all(h["pitch"] >= LOWEST_VOICE or h["pitch"] == n["pitch"] for p in parts.values() for h, n in zip(p, m))


def test_tones_avoid_what_was_really_sung_and_follow_its_tuning():
    from backend.harmony.textures import follow_singer
    m = mel(FRERE)
    sharp = [{**n, "heard": n["pitch"] + 1.2} for n in m]    # sung a semitone (and 20 cents) above the notes
    riff = plan_textures(sharp, C, KEY, VOICE, BEATS, 4, 0)["riff"]["riff"]
    for r in riff:
        for n in sharp:
            if min(r["t1"], n["t1"]) - max(r["t0"], n["t0"]) > 0.05:
                assert abs(r["pitch"] - round(n["heard"])) % 12 not in (1, 11, 6)
    tuned = follow_singer(riff, sharp, tuning_cents=-10)
    assert all(abs(n["cents"] - 10) < 1e-6 for n in tuned)   # -10 cents tuning + 20 cents sharp
