"""counter.py — rule-based (species-counterpoint style) counter-melody generator.

Pipeline: clean -> key -> chords -> rhythm plan -> style -> motif echo ->
beam search over a cost function -> quality check / fallback.
Deterministic: no randomness, all ties broken by stable ordering.

Usage:
    python counter.py melody.ly [--voice alto] [--out out/]
    python counter.py --text "\\relative c' { c4 d e f | g1 }" --voice tenor

TESTING ONLY flags (not part of the app): --rank N, --style calm|active, --midi.
"""
from __future__ import annotations

import argparse
import bisect
import dataclasses
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import lily
from lily import EPS, KeySig, Meter, Note, Score

# ---------------------------------------------------------------------------
# All tunable weights (see TUNING.md). Negative = bonus, positive = cost.
# ---------------------------------------------------------------------------
WEIGHTS: dict[str, float] = {
    # hard rules
    "hard": 100000.0,            # any hard-rule violation
    # motion against the melody (scored at each counter onset)
    "contrary": -3.0,            # counter and melody move in opposite directions
    "oblique": -1.5,             # one voice moves, the other holds
    "similar": 2.0,              # both move the same direction
    "hidden_perfect": 6.0,       # similar motion into a 5th/8ve with a counter leap
    "parallel_imperfect": 6.0,   # 3rd parallel 3rd/6th in a row (and every one after)
    # harmony
    "nct_strong": 14.0,          # non-chord tone on a strong beat
    "nct_weak": 2.0,             # non-chord tone / dissonance attacked on a weak beat
    "nct_unresolved": 16.0,      # ...that is not a passing or neighbour tone
    "weak_dissonance": 4.0,      # counter attacks a dissonance on a weak beat
    "melody_dissonance": 2.0,    # melody moves to a dissonance against a held counter note
    "doubling": 5.0,             # counter doubles melody pitch class on a strong beat
    "unison_weak": 30.0,         # unison with the melody (not final)
    "crossing": 25.0,            # per beat on the wrong side of the melody
    # melodic shape
    "step": -1.5,                # stepwise motion (1-2 semitones) bonus
    "repeat": 1.0,               # repeated pitch
    "repeat3": 10.0,             # same pitch 3+ times in a row
    "leap": 3.0,                 # leap larger than a 4th
    "leap_size": 0.6,            # extra per semitone above a 4th
    "leap_no_recovery": 6.0,     # leap (>= 4th) not followed by a step back
    "seventh_leap": 30.0,        # leap of a 7th
    "drift": 1.2,                # (distance from comfortable centre / 6 st)^2 per note
    "range_edge": 3.0,           # per beat spent in the outer 2 semitones of the range
    "oscillation": 3.0,          # jumping straight back to the note before (A-B-A zigzag)
    # cadence (final note)
    "cadence_root": -12.0,
    "cadence_third": -7.0,
    "cadence_other": 12.0,
    "rest": 150.0,               # a resting slot (last-resort escape hatch)
    # chord inference
    "chord_nonchord": 0.35,      # melody non-chord-tone penalty (fraction of coverage)
    "chord_strong_mult": 2.0,    # strong-beat melody notes count this much more
    "chord_split_gain": 0.25,    # min. fit gain to split a bar into two chords
    "chord_progression": 0.08,   # bonus for common moves (I-IV, IV-V, ii-V, vi-IV...)
    "chord_authentic": 0.15,     # bonus for V(7) -> I
    "chord_same_empty": 0.1,     # keep the chord through an empty (rest) segment
    "chord_final_tonic": 0.4,    # last chord is I
    "chord_first_tonic": 0.15,   # first chord is I
    "chord_root": 0.07,          # the chord root appears in the melody
    "chord_v7": 0.1,             # V7 penalty (needs the 7th in the melody to win over V)
    "chord_phrase_end": 0.1,     # phrase end (every 4 bars) on I or V
    # style / quality thresholds
    "style_busy_density": 0.85,  # melody onsets per beat at/above which style = calm
    "quality_min": 0.7,          # below this, use the fallback
    "key_conf_min": 0.6,         # Krumhansl correlation below this -> fallback
    "beam_width": 50,
}
HARD = WEIGHTS["hard"]


@dataclass(frozen=True)
class Voice:
    name: str
    low: int
    high: int
    clef: str


VOICES = {
    "soprano": Voice("soprano", 60, 81, "treble"),   # C4-A5
    "alto": Voice("alto", 55, 76, "treble"),         # G3-E5
    "tenor": Voice("tenor", 48, 69, "treble_8"),     # C3-A4
    "bass": Voice("bass", 40, 64, "bass"),           # E2-E4
}


# ---------------------------------------------------------------------------
# 1. Clean
# ---------------------------------------------------------------------------

def clean(notes: list[Note]) -> list[Note]:
    """Merge same-pitch notes split by tiny gaps, drop notes < 1/16, quantize to a
    16th grid, and return a contiguous list (gaps become rests, rests merged)."""
    src = sorted((Note(n.midi, n.start, n.dur) for n in notes), key=lambda n: n.start)
    merged: list[Note] = []
    for n in src:
        if (merged and n.midi is not None and merged[-1].midi == n.midi
                and 0 < n.start - merged[-1].end < 0.125):
            merged[-1].dur = n.end - merged[-1].start
        else:
            merged.append(n)
    q = lambda x: round(x * 4) / 4
    out: list[Note] = []
    for n in merged:
        if n.dur < 0.25 - EPS and n.midi is not None:
            continue
        s, e = q(n.start), q(n.end)
        if out:
            s = max(s, out[-1].end)
        if e - s < 0.25 - EPS:
            continue
        if out and s > out[-1].end + EPS:
            gap = s - out[-1].end
            if gap < 0.25 + EPS and out[-1].midi is not None:
                out[-1].dur += gap          # absorb a dropped grace note
            else:
                out.append(Note(None, out[-1].end, gap))
        out.append(Note(n.midi, s, e - s))
    res: list[Note] = []
    for n in out:
        if res and n.midi is None and res[-1].midi is None:
            res[-1].dur += n.dur
        else:
            res.append(n)
    return res


class MelodyIndex:
    """Fast lookups on a contiguous, sorted melody."""

    def __init__(self, notes: list[Note]) -> None:
        self.notes = notes
        self.starts = [n.start for n in notes]
        self.pitched = [n for n in notes if n.midi is not None]
        self.onset_times = [n.start for n in self.pitched]

    def note_at(self, t: float) -> Optional[Note]:
        i = bisect.bisect_right(self.starts, t + EPS) - 1
        if i >= 0 and self.notes[i].start - EPS <= t < self.notes[i].end - EPS:
            return self.notes[i]
        return None

    def pitch_at(self, t: float) -> Optional[int]:
        n = self.note_at(t)
        return n.midi if n else None

    def pitch_before(self, t: float) -> Optional[int]:
        return self.pitch_at(t - 0.01) if t > 0.01 else None

    def onsets_in(self, a: float, b: float) -> list[float]:
        i = bisect.bisect_left(self.onset_times, a - EPS)
        j = bisect.bisect_left(self.onset_times, b - EPS)
        return self.onset_times[i:j]

    def starts_in(self, a: float, b: float) -> list[float]:
        """All note/rest starts strictly inside (a, b)."""
        i = bisect.bisect_right(self.starts, a + EPS)
        j = bisect.bisect_left(self.starts, b - EPS)
        return self.starts[i:j]


# ---------------------------------------------------------------------------
# 2. Key (Krumhansl-Schmuckler)
# ---------------------------------------------------------------------------

KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
# conventional spelling of each tonic pc: (step, alter)
MAJOR_NAMES = {0: (0, 0), 1: (1, -1), 2: (1, 0), 3: (2, -1), 4: (2, 0), 5: (3, 0),
               6: (3, 1), 7: (4, 0), 8: (5, -1), 9: (5, 0), 10: (6, -1), 11: (6, 0)}
MINOR_NAMES = {0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (2, -1), 4: (2, 0), 5: (3, 0),
               6: (3, 1), 7: (4, 0), 8: (4, 1), 9: (5, 0), 10: (6, -1), 11: (6, 0)}


def _pearson(x: list[float], y: tuple[float, ...]) -> float:
    mx, my = sum(x) / len(x), sum(y) / len(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


def detect_key(notes: list[Note]) -> tuple[KeySig, float]:
    """Duration-weighted pitch-class histogram vs. major/minor profiles.
    Returns (key, confidence = best correlation)."""
    hist = [0.0] * 12
    for n in notes:
        if n.midi is not None:
            hist[n.midi % 12] += n.dur
    best = None
    for mode, prof, names in (("major", KK_MAJOR, MAJOR_NAMES), ("minor", KK_MINOR, MINOR_NAMES)):
        for tonic in range(12):
            rot = tuple(prof[(pc - tonic) % 12] for pc in range(12))
            r = _pearson(hist, rot)
            if best is None or r > best[0] + 1e-12:
                best = (r, KeySig(*names[tonic], mode))
    return best[1], max(0.0, best[0])


# ---------------------------------------------------------------------------
# 3. Chords
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chord:
    degree: int                 # 0-based scale degree of the root
    root: int                   # pitch class
    pcs: tuple[int, ...]
    quality: str                # '' | 'm' | 'dim' | 'aug' | '7'
    roman: str


@dataclass
class Segment:
    start: float
    end: float
    chord: Optional[Chord] = None


def build_chords(key: KeySig) -> list[Chord]:
    """Diatonic triads plus V7. Minor uses the raised 7th for V, V7 and vii°."""
    t = key.tonic_pc
    sc = [(t + i) % 12 for i in key.intervals]
    raised = (t + 11) % 12
    out = []
    numerals = ["I", "II", "III", "IV", "V", "VI", "VII"]
    for d in range(7):
        r, th, fi = sc[d], sc[(d + 2) % 7], sc[(d + 4) % 7]
        if key.mode == "minor" and d == 4:
            th = raised
        if key.mode == "minor" and d == 6:
            r = raised
            th, fi = sc[1], sc[3]
        i3, i5 = (th - r) % 12, (fi - r) % 12
        q = {(4, 7): "", (3, 7): "m", (3, 6): "dim", (4, 8): "aug"}.get((i3, i5), "")
        rn = numerals[d] if q in ("", "aug") else numerals[d].lower()
        out.append(Chord(d, r, (r, th, fi), q, rn + ("°" if q == "dim" else "")))
    v = out[4]
    out.append(Chord(4, v.root, v.pcs + (sc[3],), "7", "V7"))
    return out


_PRIOR = {0: 0.06, 3: 0.04, 4: 0.04, 5: 0.02, 1: 0.02, 2: -0.04, 6: -0.06}
_PROGRESSIONS = {(0, 3), (3, 4), (1, 4), (3, 0), (0, 4), (5, 3), (5, 1), (0, 5), (2, 5), (4, 5)}


def chord_fit(chord: Chord, mel: MelodyIndex, meter: Meter, a: float, b: float) -> float:
    """Duration-weighted chord-tone coverage of the melody in [a, b), strong beats weighted more."""
    tot = s = 0.0
    present = set()
    for n in mel.pitched:
        if n.end <= a + EPS or n.start >= b - EPS:
            continue
        st = max(a, n.start)
        w = (min(b, n.end) - st) * (WEIGHTS["chord_strong_mult"] if meter.is_strong(st) else 1.0)
        tot += w
        present.add(n.midi % 12)
        s += w if n.midi % 12 in chord.pcs else -WEIGHTS["chord_nonchord"] * w
    score = s / tot if tot else 0.0
    if chord.quality == "7":
        score -= WEIGHTS["chord_v7"] + (0.0 if chord.pcs[3] in present else 0.5)
    if chord.root in present:
        score += WEIGHTS["chord_root"]
    return score + _PRIOR[chord.degree]


def infer_chords(mel: MelodyIndex, key: KeySig, meter: Meter, end: float) -> list[Segment]:
    """One chord per bar (or per half bar when the melody clearly changes harmony),
    chosen by Viterbi over chord fit + progression bonuses."""
    chords = build_chords(key)
    segs: list[Segment] = []
    i = 0
    while meter.bar_start(i) < end - EPS:
        a, b = meter.bar_start(i), min(meter.bar_end(i), end)
        mid = meter.mid_strong
        full = abs((b - a) - meter.bar_len) < EPS
        if full and mid is not None and mel.onsets_in(a, a + mid) and mel.onsets_in(a + mid, b):
            m = a + mid
            whole = max(chords, key=lambda c: chord_fit(c, mel, meter, a, b))
            h1 = max(chords, key=lambda c: chord_fit(c, mel, meter, a, m))
            h2 = max(chords, key=lambda c: chord_fit(c, mel, meter, m, b))
            gain = (chord_fit(h1, mel, meter, a, m) + chord_fit(h2, mel, meter, m, b)) / 2 \
                - chord_fit(whole, mel, meter, a, b)
            if h1 != h2 and gain > WEIGHTS["chord_split_gain"]:
                segs += [Segment(a, m), Segment(m, b)]
                i += 1
                continue
        segs.append(Segment(a, b))
        i += 1

    n = len(segs)
    fits = [[chord_fit(c, mel, meter, s.start, s.end) for c in chords] for s in segs]
    empty = [not mel.onsets_in(s.start, s.end) and mel.pitch_at(s.start) is None for s in segs]
    phrase_end = [meter.bar_index(s.end - 0.01) % 4 == 0 and meter.bar_index(s.end - 0.01) > 0
                  and abs(meter.bar_pos(s.end)) < EPS for s in segs]

    def trans(p: Chord, c: Chord, k: int) -> float:
        bonus = 0.0
        if p.degree == 4 and c.degree == 0:
            bonus += WEIGHTS["chord_authentic"]
        elif (p.degree, c.degree) in _PROGRESSIONS:
            bonus += WEIGHTS["chord_progression"]
        if p == c and empty[k]:
            bonus += WEIGHTS["chord_same_empty"]
        return bonus

    score = [fits[0][j] + (WEIGHTS["chord_first_tonic"] if chords[j].degree == 0
                           and chords[j].quality != "7" else 0.0) for j in range(len(chords))]
    back: list[list[int]] = []
    for k in range(1, n):
        new, bk = [], []
        for j, c in enumerate(chords):
            best_v, best_i = -1e9, 0
            for pi, p in enumerate(chords):
                v = score[pi] + trans(p, c, k)
                if v > best_v + 1e-12:
                    best_v, best_i = v, pi
            extra = fits[k][j]
            if phrase_end[k] and c.degree in (0, 4):
                extra += WEIGHTS["chord_phrase_end"]
            if k == n - 1 and c.degree == 0 and c.quality != "7":
                extra += WEIGHTS["chord_final_tonic"]
            new.append(best_v + extra)
            bk.append(best_i)
        score = new
        back.append(bk)
    j = max(range(len(chords)), key=lambda x: (score[x], -x))
    path = [j]
    for bk in reversed(back):
        j = bk[j]
        path.append(j)
    for s, j in zip(segs, reversed(path)):
        s.chord = chords[j]
    return segs


def chord_at(segs: list[Segment], t: float) -> Chord:
    for s in segs:
        if s.start - EPS <= t < s.end - EPS:
            return s.chord
    return segs[-1].chord


# ---------------------------------------------------------------------------
# Context and interval helpers
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    key: KeySig
    meter: Meter
    mel: MelodyIndex
    voice: Voice
    side: str                  # counter sits 'above' or 'below' the melody
    center: float              # comfortable pitch centre for the counter
    segs: list[Segment]
    total_end: float           # end of the last bar
    start_t: float             # counter starts here (after any pickup)
    final_t: float             # onset of the melody's last note
    end_t: float               # end of the melody's last note
    mel_median: int = 60       # duration-weighted median melody pitch
    _bad: dict = field(default_factory=dict)

    def melodic_bad(self, a: int, b: int) -> bool:
        """Augmented/diminished melodic intervals, tritones, leaps over an octave."""
        k = (a, b)
        if k not in self._bad:
            self._bad[k] = _bad_interval(a, b, self.key)
        return self._bad[k]


_ALLOWED = {0: {0}, 1: {1, 2}, 2: {3, 4}, 3: {5}, 4: {7}, 5: {8, 9}, 6: {10, 11}}


def _bad_interval(a: int, b: int, key: KeySig) -> bool:
    semis = abs(b - a)
    if semis > 12 or semis % 12 == 6:
        return True
    sa, sb = key.spell(a), key.spell(b)
    da, db = sa[2] * 7 + sa[0], sb[2] * 7 + sb[0]
    steps = abs(db - da)
    return (semis - 12 * (steps // 7)) not in _ALLOWED[steps % 7]


def consonant(semis: int, final: bool) -> bool:
    """3rds, 6ths, P5, octaves; unison only on the final note."""
    if semis == 0:
        return final
    return semis % 12 in (0, 3, 4, 7, 8, 9)


def _perfect(semis: int) -> bool:
    return semis % 12 in (0, 7)


def _imperfect_class(semis: int) -> int:
    ic = semis % 12
    return 3 if ic in (3, 4) else 6 if ic in (8, 9) else 0


def wrong_side(ctx: Ctx, p: int, m: int) -> bool:
    return p > m if ctx.side == "below" else p < m


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


# ---------------------------------------------------------------------------
# 4/5. Style and rhythm plan
# ---------------------------------------------------------------------------

def choose_style(mel: MelodyIndex, start: float, end: float) -> str:
    """Busy melody -> 'calm' (fewer, longer notes); sparse melody -> 'active'."""
    beats = max(end - start, 1.0)
    density = len(mel.onsets_in(start, end)) / beats
    return "calm" if density >= WEIGHTS["style_busy_density"] else "active"


def plan_rhythm(ctx: Ctx, style: str) -> list[float]:
    """Complementary rhythm: move where the melody holds or rests, hold where it moves.
    Returns sorted onset times; the last slot runs from final_t to end_t."""
    meter, mel = ctx.meter, ctx.mel
    bl = meter.beat_len
    onsets = set()
    for seg in ctx.segs:
        a0 = max(seg.start, ctx.start_t)
        if a0 >= min(seg.end, ctx.final_t) - EPS:
            continue
        onsets.add(a0)
        wins = []
        t = a0
        while t < seg.end - EPS:
            wins.append((t, min(t + bl, seg.end)))
            t += bl
        kinds = []
        for a, b in wins:
            ons = mel.onsets_in(a, b)
            kinds.append("quiet" if not ons else
                         "step" if len(ons) == 1 and abs(ons[0] - a) < EPS else "busy")
        for (a, b), kind in zip(wins, kinds):
            if kind == "quiet":
                onsets.add(a)
                if style == "active" and b - a >= 1.0 - EPS:
                    onsets.add(a + (1.0 if b - a > 1.25 else (b - a) / 2))
        length = seg.end - a0
        if length >= 4 - EPS and kinds.count("busy") * 2 < len(kinds):
            onsets.add(a0 + length / 2)
        # active: an 8th "pickup" into the next chord, only if the counter is otherwise
        # holding through the last beat (avoids choppy syncopation)
        last_a, last_b = wins[-1] if wins else (a0, a0)
        moving = any(a0 + EPS < o < last_a + EPS for o in onsets if o < seg.end)
        if (style == "active" and kinds and kinds[-1] == "step" and last_b - last_a >= 1 - EPS
                and not (moving and max(o for o in onsets if o < seg.end) > last_a - meter.beat_len + EPS)):
            onsets.add(last_b - 0.5)
    pts = sorted(o for o in onsets if ctx.start_t - EPS <= o < ctx.final_t - EPS)
    pts.append(ctx.final_t)
    return _dedupe(pts)


def _dedupe(pts: list[float]) -> list[float]:
    out: list[float] = []
    for p in sorted(pts):
        if not out or p - out[-1] > 0.25 - EPS:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# 7. Slots and beam search
# ---------------------------------------------------------------------------

@dataclass
class Slot:
    start: float
    end: float
    chord: Chord
    final: bool
    m_before: Optional[int]
    m_on: Optional[int]
    cands: list[Optional[int]]
    vert: dict = field(default_factory=dict)    # pitch -> vertical cost
    nct: dict = field(default_factory=dict)     # pitch -> needs passing/neighbour treatment
    cross: dict = field(default_factory=dict)   # pitch -> (head, tail, whole-slot) crossing beats


def candidate_pitches(ctx: Ctx, chord: Chord, only: Optional[tuple[int, ...]] = None) -> list[int]:
    """Scale tones (or `only` pcs) inside the voice range. In minor the leading
    tone replaces the subtonic over V / V7 / vii°."""
    pcs = set(ctx.key.scale_pcs)
    if ctx.key.mode == "minor" and chord.degree in (4, 6):
        pcs.discard((ctx.key.tonic_pc + 10) % 12)
        pcs.add((ctx.key.tonic_pc + 11) % 12)
    if only is not None:
        pcs = set(only)
    return [p for p in range(ctx.voice.low, ctx.voice.high + 1) if p % 12 in pcs]


def slot_events(ctx: Ctx, a: float, b: float) -> list[tuple[float, float, Optional[int], bool]]:
    """(time, duration, melody pitch, strong) for every vertical event inside a slot."""
    meter = ctx.meter
    times = {a}
    times.update(ctx.mel.starts_in(a, b))
    i = meter.bar_index(a)
    while meter.bar_start(i) < b - EPS:
        for pos in (0.0, meter.mid_strong):
            if pos is None:
                continue
            t = meter.bar_end(i) - meter.bar_len + pos
            if a + EPS < t < b - EPS:
                times.add(t)
        i += 1
    ts = sorted(times)
    return [(t, (ts[k + 1] if k + 1 < len(ts) else b) - t, ctx.mel.pitch_at(t), meter.is_strong(t))
            for k, t in enumerate(ts)]


def make_slot(ctx: Ctx, a: float, b: float, final: bool, fixed: Optional[int] = None,
              only: Optional[tuple[int, ...]] = None, allow_rest: bool = True) -> Slot:
    """Build a slot and precompute history-independent (vertical) costs per candidate."""
    W = WEIGHTS
    chord = chord_at(ctx.segs, a)
    cands: list[Optional[int]] = [fixed] if fixed is not None else candidate_pitches(ctx, chord, only)
    if allow_rest and fixed is None:
        cands.append(None)
    slot = Slot(a, b, chord, final, ctx.mel.pitch_before(a), ctx.mel.pitch_at(a), cands)
    events = slot_events(ctx, a, b)
    strong_onset = ctx.meter.is_strong(a)
    tonic, third = ctx.key.tonic_pc, (ctx.key.tonic_pc + ctx.key.intervals[2]) % 12
    for p in cands:
        if p is None:
            slot.vert[p], slot.nct[p], slot.cross[p] = W["rest"], False, (0.0, 0.0, False)
            continue
        cost, nct = 0.0, False
        runs, cur = [], 0.0
        for j, (t, dur, m, strong) in enumerate(events):
            if m is None or not wrong_side(ctx, p, m):
                runs.append(cur)
                cur = 0.0
            if m is None:
                continue
            semis = abs(p - m)
            if wrong_side(ctx, p, m):
                cur += dur
                cost += W["crossing"] * dur
            cons = consonant(semis, final)
            if strong:
                if not cons:
                    cost += HARD
                elif semis % 12 == 0 and not final:
                    cost += W["doubling"]
            else:
                if semis == 0 and not final:
                    cost += W["unison_weak"]
                elif not cons:
                    if j == 0:
                        cost += W["weak_dissonance"]
                        nct = True
                    else:
                        cost += W["melody_dissonance"]
        if p % 12 not in chord.pcs:
            if strong_onset:
                cost += W["nct_strong"]
            else:
                cost += W["nct_weak"]
                nct = True
        runs.append(cur)
        if max(runs) > ctx.meter.beat_len + EPS:
            cost += HARD                    # crossing for more than a beat
        slot.cross[p] = (runs[0], runs[-1], len(runs) == 1 and runs[0] > 0)
        cost += W["drift"] * ((p - ctx.center) / 6.0) ** 2
        if p <= ctx.voice.low + 1 or p >= ctx.voice.high - 1:
            cost += W["range_edge"] * (b - a)
        if final:
            pc = p % 12
            cost += W["cadence_root"] if pc == tonic else W["cadence_third"] if pc == third \
                else W["cadence_other"]
        slot.vert[p], slot.nct[p] = cost, nct
    return slot


def transition(ctx: Ctx, slot: Slot, prev: Optional[Slot], p1: Optional[int], p2: Optional[int],
               rep: int, par: int, cr: float, p: Optional[int]) -> tuple[float, int, int, float]:
    """Cost of singing `p` in `slot` after (p2, p1); `cr` = crossing run carried in.
    Returns (cost, rep, par, crossing run carried out)."""
    W = WEIGHTS
    c = slot.vert[p]
    if p is None:
        if prev is not None and p1 is not None and prev.nct[p1]:
            c += W["nct_unresolved"]
        return c, 0, 0, 0.0
    head, tail, whole = slot.cross[p]
    if head > 0 and cr + head > ctx.meter.beat_len + EPS:
        c += HARD                           # crossing continues for more than a beat
    new_cr = cr + head if whole else tail
    if p1 is None:
        return c, 1, 0, new_cr
    iv = p - p1
    a = abs(iv)
    if ctx.melodic_bad(p1, p):
        c += HARD
    if a in (10, 11):
        c += W["seventh_leap"]
    if a == 0:
        rep += 1
        c += W["repeat"]
        if rep >= 3:
            c += W["repeat3"]
    else:
        rep = 1
        if a <= 2:
            c += W["step"]
        elif a >= 6:
            c += W["leap"] + W["leap_size"] * (a - 5)
    if p == p2 and a > 0:
        c += W["oscillation"]
    if p2 is not None and abs(p1 - p2) >= 5:
        if not (1 <= a <= 2 and _sign(iv) == -_sign(p1 - p2)):
            c += W["leap_no_recovery"]
    if prev is not None and prev.nct[p1]:
        ok = p2 is not None and 1 <= abs(p1 - p2) <= 2 and 1 <= a <= 2
        if not ok:
            c += W["nct_unresolved"]
    new_par = 0
    mb, mo = slot.m_before, slot.m_on
    if mb is not None and mo is not None:
        dm, dc = _sign(mo - mb), _sign(iv)
        i1, i2 = abs(p1 - mb), abs(p - mo)
        if dm == 0 or dc == 0:
            if dm != 0 or dc != 0:
                c += W["oblique"]
        else:
            if _perfect(i1) and _perfect(i2) and i1 % 12 == i2 % 12:
                c += HARD
            if dc == -dm:
                c += W["contrary"]
            else:
                c += W["similar"]
                if _perfect(i2) and a > 2:
                    c += W["hidden_perfect"]
                k1, k2 = _imperfect_class(i1), _imperfect_class(i2)
                if k1 and k1 == k2:
                    new_par = par + 1
                    if new_par >= 2:
                        c += W["parallel_imperfect"]
    return c, rep, new_par, new_cr


def beam_search(ctx: Ctx, slots: list[Slot], width: int) -> list[tuple[float, list[Optional[int]]]]:
    """Beam search (with DP-style state merging). Returns finished lines, best first."""
    # state: (cost, p1, p2, rep, par, crossing, node) with node = (pitch, parent_node)
    beam = [(0.0, None, None, 0, 0, 0.0, None)]
    for k, slot in enumerate(slots):
        prev = slots[k - 1] if k else None
        expanded = []
        for cost, p1, p2, rep, par, cr, node in beam:
            for p in slot.cands:
                dc, r2, pa2, cr2 = transition(ctx, slot, prev, p1, p2, rep, par, cr, p)
                expanded.append((cost + dc, p, p1, r2, pa2, cr2, (p, node)))
        expanded.sort(key=lambda s: s[0])          # stable -> deterministic ties
        seen = set()
        beam = []
        for st in expanded:
            sig = (st[1], st[2], min(st[3], 3), min(st[4], 2), round(st[5], 2))
            if sig in seen:
                continue
            seen.add(sig)
            beam.append(st)
            if len(beam) >= width:
                break
    finals = []
    last = slots[-1] if slots else None
    for cost, p1, _p2, _r, _pa, _cr, node in beam:
        if last is not None and p1 is not None and last.nct[p1]:
            cost += WEIGHTS["nct_unresolved"]
        seq = []
        while node is not None:
            seq.append(node[0])
            node = node[1]
        finals.append((cost, seq[::-1]))
    finals.sort(key=lambda f: f[0])
    return finals


def line_to_notes(ctx: Ctx, slots: list[Slot], seq: list[Optional[int]]) -> list[Note]:
    """Slots + chosen pitches -> contiguous counter note list (rests merged)."""
    notes: list[Note] = []

    def add(midi: Optional[int], a: float, b: float) -> None:
        if b - a < EPS:
            return
        if notes and midi is None and notes[-1].midi is None:
            notes[-1].dur = b - notes[-1].start
        else:
            notes.append(Note(midi, a, b - a))

    add(None, 0.0, slots[0].start if slots else ctx.total_end)
    for s, p in zip(slots, seq):
        add(p, s.start, s.end)
    if slots:
        add(None, slots[-1].end, ctx.total_end)
    return notes


# ---------------------------------------------------------------------------
# Validation (hard rules) and quality
# ---------------------------------------------------------------------------

def _event_times(ctx: Ctx, counter: list[Note]) -> list[float]:
    times = set(n.start for n in ctx.mel.notes) | set(n.start for n in counter)
    i = 0
    m = ctx.meter
    while m.bar_start(i) < ctx.total_end - EPS:
        base = m.bar_end(i) - m.bar_len
        for pos in (0.0, m.mid_strong):
            if pos is not None and 0 <= base + pos < ctx.total_end - EPS:
                times.add(base + pos)
        i += 1
    return sorted(t for t in times if t < ctx.total_end - EPS)


def hard_violations(ctx: Ctx, counter: list[Note]) -> list[str]:
    """Independent check of every hard rule. Empty list = the line is safe."""
    errs: list[str] = []
    cidx = MelodyIndex(counter)
    pitched = [n for n in counter if n.midi is not None]
    final_t = pitched[-1].start if pitched else 0.0
    for n in pitched:
        if not ctx.voice.low <= n.midi <= ctx.voice.high:
            errs.append(f"out of range at {n.start:g}")
    prev = None
    for t in _event_times(ctx, counter):
        m, c = ctx.mel.pitch_at(t), cidx.pitch_at(t)
        if m is not None and c is not None and ctx.meter.is_strong(t):
            if not consonant(abs(c - m), t >= final_t - EPS):
                errs.append(f"strong-beat dissonance at {t:g}")
        if prev is not None:
            m0, c0 = prev
            if None not in (m0, c0, m, c) and m0 != m and c0 != c:
                i0, i1 = abs(c0 - m0), abs(c - m)
                if _perfect(i0) and _perfect(i1) and i0 % 12 == i1 % 12:
                    errs.append(f"parallel {'5ths' if i1 % 12 == 7 else '8ves'} at {t:g}")
        prev = (m, c)
    run = 0.0
    t = 0.0
    while t < ctx.total_end - EPS:
        m, c = ctx.mel.pitch_at(t), cidx.pitch_at(t)
        run = run + 0.25 if (m is not None and c is not None and wrong_side(ctx, c, m)) else 0.0
        if run > ctx.meter.beat_len + EPS:
            errs.append(f"voice crossing longer than a beat at {t:g}")
            run = -1e9
        t += 0.25
    for a, b in zip(counter, counter[1:]):
        if a.midi is not None and b.midi is not None and ctx.melodic_bad(a.midi, b.midi):
            errs.append(f"bad leap {a.midi}->{b.midi} at {b.start:g}")
    return errs


def quality(ctx: Ctx, counter: list[Note]) -> float:
    """0..1: consonant strong beats, stepwise motion, no hard violations, no crossing."""
    cidx = MelodyIndex(counter)
    pitched = [n for n in counter if n.midi is not None]
    if not pitched:
        return 0.0
    final_t = pitched[-1].start
    good = total = 0.0
    for t in _event_times(ctx, counter):
        m = ctx.mel.pitch_at(t)
        if m is None or not ctx.meter.is_strong(t) or t < ctx.start_t - EPS or t >= ctx.end_t - EPS:
            continue
        c = cidx.pitch_at(t)
        total += 1
        good += 0.5 if c is None else (1.0 if consonant(abs(c - m), t >= final_t - EPS) else 0.0)
    cons = good / total if total else 1.0
    moves = steps = 0
    for a, b in zip(counter, counter[1:]):
        if a.midi is not None and b.midi is not None and a.midi != b.midi:
            moves += 1
            steps += abs(a.midi - b.midi) <= 2
    step_share = steps / moves if moves else 1.0
    both = crossed = 0.0
    t = 0.0
    while t < ctx.total_end - EPS:
        m, c = ctx.mel.pitch_at(t), cidx.pitch_at(t)
        if m is not None and c is not None:
            both += 1
            crossed += wrong_side(ctx, c, m)
        t += 0.25
    cross_ok = 1.0 - (crossed / both if both else 0.0)
    no_hard = 0.0 if hard_violations(ctx, counter) else 1.0
    return round(0.35 * cons + 0.25 * min(1.0, step_share / 0.6) + 0.2 * no_hard + 0.2 * cross_ok, 3)


def independence(melody: list[Note], counter: list[Note]) -> float:
    """Share of counter onsets that do not coincide with a melody onset."""
    mel_on = {round(n.start, 4) for n in melody if n.midi is not None}
    ons = [round(n.start, 4) for n in counter if n.midi is not None]
    return sum(o not in mel_on for o in ons) / len(ons) if ons else 0.0


# ---------------------------------------------------------------------------
# 6. Motif echo
# ---------------------------------------------------------------------------

def _to_degree(midi: int, key: KeySig) -> Optional[int]:
    pcs = list(key.scale_pcs)
    pc = midi % 12
    if pc not in pcs:
        if key.mode == "minor" and pc == (key.tonic_pc + 11) % 12:
            pc = (key.tonic_pc + 10) % 12
        else:
            return None
    idx = pcs.index(pc)
    octv = (midi - key.tonic_pc - key.intervals[idx]) // 12
    return octv * 7 + idx


def _from_degree(d: int, key: KeySig) -> int:
    octv, idx = divmod(d, 7)
    return 12 * octv + key.tonic_pc + key.intervals[idx]


def echo_options(ctx: Ctx, max_opts: int = 3) -> list[list[Note]]:
    """Candidate echoes: a distinctive 3-5 note melody fragment, delayed 1-2 beats,
    placed where the melody holds/rests, diatonically transposed onto a chord tone."""
    notes = ctx.mel.notes
    frags = []
    for L in (4, 3, 5):
        for i in range(len(notes) - L + 1):
            g = notes[i:i + L]
            if any(n.midi is None for n in g):
                continue
            span = g[-1].end - g[0].start
            mids = [n.midi for n in g]
            if not 1.0 <= span <= 4.0 or len(set(mids)) < 2:
                continue
            if any(_to_degree(m, ctx.key) is None for m in mids):
                continue
            leap = any(abs(x - y) >= 3 for x, y in zip(mids, mids[1:]))
            score = len(set(mids)) + leap + 0.5 * min(2, len({n.dur for n in g})) + (0.5 if L == 4 else 0)
            frags.append((-score, i, g))
    frags.sort(key=lambda f: (f[0], f[1]))
    placements = []
    for rank, (_s, _i, g) in enumerate(frags[:12]):
        span = g[-1].end - g[0].start
        for delay in (1, 2):
            es = g[0].start + delay * ctx.meter.beat_len
            ee = es + span
            if es < ctx.start_t - EPS or ee > ctx.final_t + EPS:
                continue
            busy = len(ctx.mel.onsets_in(es, ee))
            if busy > span * 0.5:
                continue
            placements.append((busy / span, rank, delay, es, g))
    placements.sort(key=lambda p: p[:3])
    out: list[list[Note]] = []
    for _b, _r, _d, es, g in placements:
        degs = [_to_degree(n.midi, ctx.key) for n in g]
        chord = chord_at(ctx.segs, es)
        shifts = sorted(range(-14, 15), key=lambda k: (abs(sum(_from_degree(d + k, ctx.key)
                                                               for d in degs) / len(degs) - ctx.center), k))
        for k in shifts:
            pitches = [_from_degree(d + k, ctx.key) for d in degs]
            if not all(ctx.voice.low <= p <= ctx.voice.high for p in pitches):
                continue
            if pitches[0] % 12 not in chord.pcs:
                continue
            if any(ctx.melodic_bad(x, y) for x, y in zip(pitches, pitches[1:])):
                continue
            echo = [Note(p, es + (n.start - g[0].start), n.dur) for p, n in zip(pitches, g)]
            ok = True
            for e in echo:
                s = make_slot(ctx, e.start, e.end, False, fixed=e.midi, allow_rest=False)
                if s.vert[e.midi] >= HARD or any(
                        m is not None and wrong_side(ctx, e.midi, m)
                        for _t, _d, m, _s in slot_events(ctx, e.start, e.end)):
                    ok = False
                    break
            if ok:
                if not any(o[0].start == echo[0].start for o in out):
                    out.append(echo)
                break
        if len(out) >= max_opts:
            break
    return out


# ---------------------------------------------------------------------------
# 8. Generation, fallback
# ---------------------------------------------------------------------------

@dataclass
class Result:
    melody: list[Note]
    counter: list[Note]
    key: KeySig
    key_conf: float
    meter: Meter
    segs: list[Segment]
    style: str
    quality: float
    fallback: bool
    echo: bool
    voice: Voice
    warnings: list[str]
    ctx: Ctx


def build_ctx(score: Score, voice: str) -> tuple[Ctx, float, list[str]]:
    """Clean the melody, find key and chords, decide side/centre of the counter."""
    warnings = list(score.warnings)
    notes = clean(score.notes)
    if not any(n.midi is not None for n in notes):
        raise ValueError("melody has no notes")
    if score.key is not None:
        key, conf = score.key, 1.0
    else:
        key, conf = detect_key(notes)
        warnings.append(f"no \\key given; detected {key.name()} (confidence {conf:.2f})")
    meter = score.meter
    mel = MelodyIndex(notes)
    total_end = meter.end_of_music(notes[-1].end)
    v = VOICES[voice]
    ws = sorted((n.midi, n.dur) for n in mel.pitched)
    half, acc, med = sum(d for _, d in ws) / 2, 0.0, ws[0][0]
    for m, d in ws:
        acc += d
        if acc >= half - EPS:
            med = m
            break
    room_above, room_below = v.high - med, med - v.low
    side = "above" if room_above > room_below else "below"
    center = side_center(v, med, side)
    last = mel.pitched[-1]
    start_t = meter.pickup if meter.pickup > EPS else 0.0
    final_t = max(last.start, start_t)
    end_t = max(last.end, final_t + 0.25)
    segs = infer_chords(mel, key, meter, total_end)
    ctx = Ctx(key, meter, mel, v, side, center, segs, total_end, start_t, final_t, end_t, med)
    return ctx, conf, warnings


def side_center(v: Voice, med: int, side: str) -> float:
    """Comfortable centre: halfway between the voice's middle and a 5th from the melody."""
    ideal = med + 7 if side == "above" else med - 7
    return min(max((ideal + (v.low + v.high) / 2) / 2, v.low + 3), v.high - 3)


def slots_from_onsets(ctx: Ctx, onsets: list[float], fixed: Optional[dict] = None) -> list[Slot]:
    fixed = fixed or {}
    bounds = onsets + [ctx.end_t]
    return [make_slot(ctx, a, b, abs(a - ctx.final_t) < EPS, fixed=fixed.get(round(a, 4)))
            for a, b in zip(bounds, bounds[1:]) if b - a > EPS]


def ranked_lines(ctx: Ctx, slots: list[Slot], want: int) -> list[tuple[float, list[Note]]]:
    """Up to `want` distinct (cost, line) pairs that pass every hard rule, best first."""
    out: list[tuple[float, list[Note]]] = []
    seen = set()
    for cost, seq in beam_search(ctx, slots, int(WEIGHTS["beam_width"])):
        if cost >= HARD:
            break
        key = tuple(seq)
        if key in seen:
            continue
        seen.add(key)
        notes = line_to_notes(ctx, slots, seq)
        if not hard_violations(ctx, notes):
            out.append((cost, notes))
            if len(out) >= want:
                break
    return out


def fallback_lines(ctx: Ctx, want: int) -> list[list[Note]]:
    """Held chord tones, one per chord, smoothest voice leading. Segments where no
    chord tone fits every strong beat are split at strong beats; rests are the last resort."""
    slots: list[Slot] = []
    bounds = []
    for seg in ctx.segs:
        a, b = max(seg.start, ctx.start_t), min(seg.end, ctx.end_t)
        if b - a < EPS or a >= ctx.final_t - EPS:
            continue
        bounds.append((a, min(b, ctx.final_t)))
    bounds.append((ctx.final_t, ctx.end_t))
    for a, b in bounds:
        final = abs(a - ctx.final_t) < EPS
        s = make_slot(ctx, a, b, final, only=ctx.segs and chord_at(ctx.segs, a).pcs)
        if all(s.vert[p] >= HARD for p in s.cands if p is not None):
            cuts = [a] + [t for t, _d, _m, strong in slot_events(ctx, a, b) if strong and t > a + EPS] + [b]
            slots += [make_slot(ctx, x, y, final and abs(x - ctx.final_t) < EPS)
                      for x, y in zip(cuts, cuts[1:])]
        else:
            slots.append(s)
    lines = [notes for _c, notes in ranked_lines(ctx, slots, want)]
    if not lines:
        lines = [line_to_notes(ctx, slots, [None] * len(slots))]
    return lines


def generate(score: Score, voice: str = "alto", rank: int = 1, style: str = "auto",
             force_fallback: bool = False) -> Result:
    """Run the whole pipeline and return the single best counter-melody.
    `rank`, `style` and `force_fallback` are TESTING ONLY hooks; the app uses the defaults."""
    base, conf, warnings = build_ctx(score, voice)
    st = choose_style(base.mel, base.start_t, base.end_t) if style == "auto" else style
    # Try the counter both above and below the melody; keep the cheaper valid line.
    ctx, lines, onsets = base, [], plan_rhythm(base, st)
    best_cost = None
    for side in (base.side, "below" if base.side == "above" else "above"):
        c = dataclasses.replace(base, side=side,
                                center=side_center(base.voice, base.mel_median, side))
        ons = plan_rhythm(c, st)
        found = ranked_lines(c, slots_from_onsets(c, ons), rank)
        if found and (best_cost is None or found[0][0] < best_cost - EPS):
            ctx, lines, onsets, best_cost = c, found, ons, found[0][0]
    used_echo = False
    if st == "active" and not force_fallback:
        for echo in echo_options(ctx):
            es, ee = echo[0].start, echo[-1].end
            ons = [o for o in onsets if o < es - EPS or o >= ee - EPS]
            ons += [e.start for e in echo] + [ee]
            ons = _dedupe([o for o in ons if o <= ctx.final_t + EPS])
            if ons[-1] < ctx.final_t - EPS:
                ons.append(ctx.final_t)
            fixed = {round(e.start, 4): e.midi for e in echo}
            if any(round(o, 4) not in {round(x, 4) for x in ons} for o in fixed):
                continue
            elines = ranked_lines(ctx, slots_from_onsets(ctx, ons, fixed), rank)
            if len(elines) >= rank and quality(ctx, elines[rank - 1][1]) >= WEIGHTS["quality_min"]:
                lines, used_echo = elines, True
                break
    chosen = lines[min(rank, len(lines)) - 1][1] if lines else None
    q = quality(ctx, chosen) if chosen else 0.0
    use_fallback = force_fallback or chosen is None or q < WEIGHTS["quality_min"] \
        or conf < WEIGHTS["key_conf_min"]
    if use_fallback:
        fl = fallback_lines(ctx, rank)
        chosen = fl[min(rank, len(fl)) - 1]
        q = quality(ctx, chosen)
        used_echo = False
        if conf < WEIGHTS["key_conf_min"]:
            warnings.append(f"low key confidence ({conf:.2f}); using the safe fallback line")
    return Result(ctx.mel.notes, chosen, ctx.key, conf, ctx.meter, ctx.segs, st, q,
                  use_fallback, used_echo, ctx.voice, warnings, ctx)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def melody_clef(notes: list[Note]) -> str:
    ps = sorted(n.midi for n in notes if n.midi is not None)
    return "bass" if ps[len(ps) // 2] < 55 else "treble"


def render(res: Result, score: Score, title: str) -> tuple[str, str]:
    """(full .ly file, bare counter-melody string)."""
    meta = (f"key={res.key.name()}; style={res.style}; quality={res.quality:.2f}; "
            f"fallback={'yes' if res.fallback else 'no'}; voice={res.voice.name}; "
            f"echo={'yes' if res.echo else 'no'}")
    chords = [(s.start, s.end, s.chord.root, s.chord.quality) for s in res.segs]
    ly = lily.write_score(
        title=title, melody=res.melody, counter=res.counter, key=res.key, meter=res.meter,
        tempo_bpm=score.tempo_bpm, tempo_unit=score.tempo_unit, chords=chords,
        voice_name=res.voice.name, counter_clef=res.voice.clef,
        melody_clef=melody_clef(res.melody), meta=meta)
    bare = lily.format_notes(res.counter, res.key, res.meter, res.ctx.total_end)
    return ly, bare


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate a singable counter-melody.")
    ap.add_argument("file", nargs="?", help="input .ly file")
    ap.add_argument("--text", help="LilyPond text instead of a file")
    ap.add_argument("--voice", default="alto", choices=sorted(VOICES))
    # --rank, --style and --midi are TESTING ONLY switches; the app always uses the defaults.
    ap.add_argument("--rank", type=int, default=1, help="(testing) return the n-th best line")
    ap.add_argument("--style", default="auto", choices=["auto", "calm", "active"],
                    help="(testing) override the automatic style")
    ap.add_argument("--out", help="directory for <name>_counter.ly")
    ap.add_argument("--midi", action="store_true", help="(testing) also write .mid files")
    args = ap.parse_args(argv)
    if bool(args.file) == bool(args.text):
        ap.error("give exactly one of FILE or --text")
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
        name = os.path.splitext(os.path.basename(args.file))[0]
    else:
        text, name = args.text, "text"

    t0 = time.perf_counter()
    score = lily.parse(text)
    res = generate(score, args.voice, max(1, args.rank), args.style)
    ly, bare = render(res, score, name)
    elapsed = time.perf_counter() - t0

    for w in _grouped(res.warnings):
        print(f"warning: {w}", file=sys.stderr)
    print(ly)
    print("% counter-melody alone:")
    print(bare)
    print(f"% key={res.key.name()} style={res.style} quality={res.quality:.2f} "
          f"fallback={'yes' if res.fallback else 'no'} echo={'yes' if res.echo else 'no'} "
          f"independent-onsets={independence(res.melody, res.counter):.0%} ({elapsed * 1000:.0f} ms)",
          file=sys.stderr)

    if args.out or args.midi:
        out_dir = args.out or "out"
        os.makedirs(out_dir, exist_ok=True)
        if args.out:
            with open(os.path.join(out_dir, f"{name}_counter.ly"), "w", encoding="utf-8") as fh:
                fh.write(ly)
        if args.midi:   # TESTING ONLY: lets you listen to the result; not used by the app
            from testing_midi import write_midi
            qpm = score.tempo_qpm
            write_midi(os.path.join(out_dir, f"{name}_original.mid"),
                       [(res.melody, 0, "Melody")], qpm, res.meter)
            write_midi(os.path.join(out_dir, f"{name}_counter.mid"),
                       [(res.counter, 71, "Counter")], qpm, res.meter)
            write_midi(os.path.join(out_dir, f"{name}_both.mid"),
                       [(res.melody, 0, "Melody (piano)"), (res.counter, 71, "Counter (clarinet)")],
                       qpm, res.meter)
    return 0


def _grouped(warnings: list[str]) -> list[str]:
    """Collapse repeated warnings into 'msg (xN)'."""
    counts: dict[str, int] = {}
    for w in warnings:
        counts[w] = counts.get(w, 0) + 1
    return [w if c == 1 else f"{w} (x{c})" for w, c in counts.items()]


if __name__ == "__main__":
    sys.exit(main())
