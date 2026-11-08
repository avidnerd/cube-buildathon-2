"""Vocal harmony that sings *with* the lead: same words, same moment.

Two halves:

1. plan_parts(): choose a harmony pitch for every note the lead actually
   sang. Each harmony note keeps the lead note's real start/end time (t0/t1,
   seconds), never a grid-snapped version, so the parts line up syllable for
   syllable. Pitches come from a Viterbi over candidates scored by
     - TIS consonance of {chord, melody note, harmony note}   (the main ear test)
     - being a chord tone / in the key
     - the arrangement's target interval (3rd above, 6th below, ...)
     - smooth, parallel motion: keeping the same interval as the last note is
       what makes a harmony sound glued to the lead instead of jumping around.

2. render_part(): the harmony *in the lead's own voice*. TD-PSOLA re-pitches
   the isolated vocal one glottal cycle at a time, using the measured pitch
   track, so duration, consonants, vibrato and timbre are kept and only the
   pitch moves. The shift glides between notes rather than cutting.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable, Sequence

import numpy as np

from backend.harmony.dissonance import Scene, candidate_dissonance, chord_scene
from backend.harmony.reharmonize import Chord
from backend.harmony.tis import scale

# ---------------------------------------------------------------------------
# Arrangements
# ---------------------------------------------------------------------------

# id -> label, parts: (part id, part label, side +1 above / -1 below, target interval in semitones)
ARRANGEMENTS = {
    "classic": {"label": "3rd above + 6th below",
                "parts": (("high", "Harmony above", +1, 3.5), ("low", "Harmony below", -1, 8.5))},
    "close": {"label": "3rds above and below (tight)",
              "parts": (("high", "Harmony above", +1, 3.5), ("low", "Harmony below", -1, 3.5))},
    "stack": {"label": "3rd + 5th above (stacked)",
              "parts": (("high", "Top harmony", +1, 7.0), ("low", "Middle harmony", +1, 3.5))},
}

# The main criterion is *measured* dissonance (dissonance.py): roughness + TIS
# tonal dissonance of each candidate against what is actually sounding. The
# rest are gentle preferences that only break ties between consonant choices.
W_DISSONANCE = 3.0   # x (0..2.5 per note, relative): the dominant term
CONSONANT_BAND = 0.45  # notes this close to the least dissonant count as equally good
W_CHORD_TONE = 0.3   # chord label: weak, labels can be wrong
W_IN_KEY = 0.3
W_OUT_OF_KEY = 0.6
W_INTERVAL = 0.15    # per semitone away from the arrangement's target interval
W_DOUBLING = 1.2     # same pitch class as the lead: that's doubling, not harmony
W_SWEET = 0.5        # 3rds/6ths with the lead: what makes a harmony sound sweet rather than hollow
W_STEP = 3.0         # a 2nd/7th against the lead itself grates, even on a chord tone...
W_TRITONE = 2.5      # ...and so does a tritone
CLASH_FULL_S = 0.25  # clashes count fully once held this long (shorter ones pass by)
W_PART_DOUBLE = 2.0  # two harmony parts on the same note name: thin, not a chord
W_WRONG_SIDE = 4.0
W_COMFORT = 1.0      # per semitone outside the comfortable range
W_MOTION = 0.15      # per semitone the harmony line moves
W_SAME_INTERVAL = 0.5  # keep the same (diatonic) interval as the previous note
W_PARALLEL_PERFECT = 0.6
PHRASE_GAP_S = 0.35  # notes further apart than this are in different phrases


def _diatonic_steps(a: int, b: int, sc: frozenset[int]) -> int:
    """Signed scale steps from a to b (chromatic notes round toward a)."""
    lo, hi = sorted((a, b))
    steps = sum(1 for p in range(lo + 1, hi + 1) if p % 12 in sc)
    return steps if b >= a else -steps


def plan_part(
    melody: Sequence[dict],
    chord_at: Callable[[float], Chord | None],
    key: tuple[int, str],
    voice: tuple[int, int, int, int],
    side: int,
    target: float,
    scene_for: Callable[[dict], Scene] | None = None,
    others: Sequence[Sequence[int]] = (),
) -> list[dict]:
    """melody: notes with pitch, t0, t1 (seconds). Returns harmony notes with the same timing.

    scene_for(note) -> what's sounding under that note (measured from the real
    accompaniment). Without it, the chord at that time is used as a soft pad.
    others: pitches (one per melody note) of harmony parts already planned;
    this part avoids doubling them so the voices spell out a full chord.
    """
    if not melody:
        return []
    tonic, mode = key
    sc = scale(tonic, mode)
    sc_ext = sc | ({(tonic + 11) % 12} if mode == "minor" else set())  # harmonic-minor leading tone
    low, high, s_low, s_high = voice

    cands: list[np.ndarray] = []
    node: list[np.ndarray] = []
    for n in melody:
        m = int(n["pitch"])
        ch = chord_at(0.5 * (n["t0"] + n["t1"]))
        base = list(ch.tones) if ch is not None else [tonic, (tonic + (4 if mode == "major" else 3)) % 12, (tonic + 7) % 12]
        opts = np.array([p for p in range(low, high + 1) if p != m] or [m], dtype=int)
        pcs = opts % 12
        scene = scene_for(n) if scene_for is not None else chord_scene(base, m)
        d = candidate_dissonance(scene, opts, m)
        # Clash vs. no clash is what matters; ranking among notes that already
        # sound fine is left to smoothness and 3rd/6th sweetness.
        cost = W_DISSONANCE * np.maximum(0.0, d - d.min() - CONSONANT_BAND)
        cost += W_DOUBLING * (pcs == m % 12)
        ic = np.abs(opts - m) % 12
        held = min(1.0, (n["t1"] - n["t0"]) / CLASH_FULL_S)
        cost -= W_SWEET * np.isin(ic, (3, 4, 8, 9))
        cost += W_STEP * (0.4 + 0.6 * held) * np.isin(ic, (1, 2, 10, 11))
        cost += W_TRITONE * (0.4 + 0.6 * held) * (ic == 6)
        for other in others:
            o = int(other[len(cands)])
            cost += W_PART_DOUBLE * (pcs == o % 12)
            cost += W_STEP * 0.5 * held * np.isin(np.abs(opts - o) % 12, (1, 2, 10, 11))  # parts rubbing
        tones = ch.tones if ch is not None else frozenset()
        cost -= W_CHORD_TONE * np.isin(pcs, list(tones))
        cost -= W_IN_KEY * np.isin(pcs, list(sc_ext))
        cost += W_OUT_OF_KEY * ~np.isin(pcs, list(sc_ext | tones))
        iv = (opts - m) * side
        cost += W_INTERVAL * np.abs(iv - target)
        cost += W_WRONG_SIDE * (iv <= 0)
        cost += W_COMFORT * (np.maximum(0, opts - s_high) + np.maximum(0, s_low - opts))
        cands.append(opts)
        node.append(cost)

    # Signed scale steps from each melody note to each of its candidates.
    steps = [np.array([_diatonic_steps(int(n["pitch"]), int(p), sc) for p in opts])
             for n, opts in zip(melody, cands)]

    acc = node[0].copy()
    back: list[np.ndarray] = []
    for i in range(1, len(melody)):
        prev, cur = melody[i - 1], melody[i]
        pm, cm = int(prev["pitch"]), int(cur["pitch"])
        P, C = cands[i - 1][:, None], cands[i][None, :]
        joined = cur["t0"] - prev["t1"] < PHRASE_GAP_S
        short = (cur["t1"] - cur["t0"]) < 0.15
        k = (1.5 if short else 1.0) if joined else 0.25
        edge = W_MOTION * k * np.abs(C - P)
        # Same interval to the melody as before (diatonically): parallel motion.
        edge = edge - W_SAME_INTERVAL * k * (steps[i - 1][:, None] == steps[i][None, :])
        # Hollow parallel unisons/fifths/octaves.
        moved = (C != P) & (cm != pm)
        perfect = np.isin(np.abs(P - pm) % 12, (0, 7)) & np.isin(np.abs(C - cm) % 12, (0, 7))
        edge = edge + W_PARALLEL_PERFECT * (moved & perfect)
        total = acc[:, None] + edge
        back.append(np.argmin(total, axis=0))
        acc = total.min(axis=0) + node[i]

    j = int(np.argmin(acc))
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    path.reverse()
    out = []
    for n, opts, j in zip(melody, cands, path):
        out.append({
            "pitch": int(opts[j]), "melody_pitch": int(n["pitch"]),
            "t0": n["t0"], "t1": n["t1"],
            "start": n.get("start"), "duration": n.get("duration"),
            "lyric": n.get("lyric", ""), "word_start": n.get("word_start", False),
        })
    return out


def plan_parts(melody, chord_at, key, voice, arrangement: str = "classic",
               scene_for: Callable[[dict], Scene] | None = None) -> dict[str, list[dict]]:
    arr = ARRANGEMENTS[arrangement]
    if scene_for is not None:  # measure each note's scene once for all parts
        cache = {id(n): scene_for(n) for n in melody}
        scene_for = lambda n, _c=cache: _c[id(n)]  # noqa: E731
    out: dict[str, list[dict]] = {}
    for pid, _, side, target in arr["parts"]:  # later parts fill in around earlier ones
        others = [[h["pitch"] for h in part] for part in out.values()]
        out[pid] = plan_part(melody, chord_at, key, voice, side, target, scene_for, others)
    return out


# ---------------------------------------------------------------------------
# Rendering in the lead's voice: TD-PSOLA
# ---------------------------------------------------------------------------

GLIDE_S = 0.04
UNVOICED_STEP_S = 0.008


def shift_curve(melody: Sequence[dict], part: Sequence[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Piecewise-linear semitone shift over time: held through each note,
    gliding (~GLIDE_S) across note boundaries, held flat past the ends."""
    kt: list[float] = []
    ks: list[float] = []
    for m, h in zip(melody, part):
        s = float(h["pitch"] - m["pitch"])
        t0, t1 = float(m["t0"]), float(m["t1"])
        g = min(GLIDE_S / 2, (t1 - t0) / 4)
        a, b = t0 + g, t1 - g
        if kt and a <= kt[-1]:
            a = kt[-1] + 1e-4
            b = max(b, a)
        kt += [a, b]
        ks += [s, s]
    return np.array(kt), np.array(ks)


@lru_cache(maxsize=64)
def _hann(n: int) -> np.ndarray:
    return np.hanning(max(n, 3))


def psola(x: np.ndarray, sr: int, f0_times: np.ndarray, f0_hz: np.ndarray,
          shift_t: np.ndarray, shift_s: np.ndarray) -> np.ndarray:
    """Pitch-shift x by the semitone curve (shift_t, shift_s), keeping timing.

    f0_hz: the lead's pitch track (nan where unvoiced). Unvoiced sound
    (consonants, breaths) is passed through unshifted.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    voiced_t = ~np.isnan(f0_hz)
    if not voiced_t.any():
        return x.copy()

    def f0_at(sample: float) -> float:
        t = sample / sr
        i = int(np.searchsorted(f0_times, t))
        lo, hi = max(0, i - 1), min(len(f0_times) - 1, i)
        near = lo if abs(f0_times[lo] - t) <= abs(f0_times[hi] - t) else hi
        if abs(f0_times[near] - t) > 0.03 or np.isnan(f0_hz[near]):
            return 0.0
        a, b = f0_hz[lo], f0_hz[hi]
        if np.isnan(a) or np.isnan(b) or hi == lo:
            return float(f0_hz[near])
        w = (t - f0_times[lo]) / (f0_times[hi] - f0_times[lo])
        return float(a + w * (b - a))

    # 1. Analysis marks: one per glottal cycle in voiced regions (snapped to
    #    waveform peaks so grains stay pitch-synchronous), fixed steps elsewhere.
    marks, periods, voiced = [], [], []
    pos = 0.0
    unv = UNVOICED_STEP_S * sr
    while pos < n:
        f = f0_at(pos)
        if f > 0:
            T = sr / f
            a, b = int(pos), int(min(n, pos + T))
            if not marks or not voiced[-1]:
                p = a + int(np.argmax(x[a:b])) if b > a else a
            else:
                c = marks[-1] + T
                lo, hi = int(max(0, c - T / 4)), int(min(n, c + T / 4 + 1))
                p = lo + int(np.argmax(x[lo:hi])) if hi > lo else int(c)
            if marks and p <= marks[-1]:
                p = int(marks[-1] + max(1, T / 2))
            marks.append(p); periods.append(T); voiced.append(True)
            pos = p + T
        else:
            p = int(pos)
            marks.append(p); periods.append(unv); voiced.append(False)
            pos += unv
    marks_a = np.array(marks, dtype=np.float64)

    # 2. Synthesis: walk the same timeline, placing grains at the new period.
    y = np.zeros(n)
    wsum = np.zeros(n)
    ts = marks_a[0]
    while ts < n:
        j = int(np.clip(np.searchsorted(marks_a, ts), 0, len(marks_a) - 1))
        if j > 0 and abs(marks_a[j - 1] - ts) < abs(marks_a[j] - ts):
            j -= 1
        ta, T, v = int(marks_a[j]), periods[j], voiced[j]
        if v:
            r = 2.0 ** (float(np.interp(ts / sr, shift_t, shift_s)) / 12.0)
            L = int(T)
            step = T / r
        else:
            L = int(unv)
            step = unv
        a0, a1 = ta - L, ta + L
        s0 = int(round(ts)) - L
        lo = max(0, -a0, -s0)
        hi = min(2 * L, n - a0, n - s0)
        if hi > lo:
            w = _hann(2 * L)[lo:hi]
            y[s0 + lo: s0 + hi] += x[a0 + lo: a0 + hi] * w
            wsum[s0 + lo: s0 + hi] += w
        ts += max(step, 1.0)
    ok = wsum > 0.05
    y[ok] /= wsum[ok]
    y[~ok] = 0.0
    return y


def render_part(vocals: np.ndarray, sr: int, f0_times: np.ndarray, f0_hz: np.ndarray,
                melody: Sequence[dict], part: Sequence[dict]) -> np.ndarray:
    """The lead's own voice, re-pitched to sing `part`. Silent where the lead is silent."""
    t, s = shift_curve(melody, part)
    if len(t) == 0:
        return np.zeros_like(vocals)
    return psola(vocals, sr, f0_times, f0_hz, t, s)
