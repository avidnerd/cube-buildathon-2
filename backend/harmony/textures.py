"""Textures beyond parallel harmony: rounds, canons, echoes and riffs.

    plan_textures(melody, chord_at, key, voice, beats=None, bar=4, phase=0)
        -> {texture id: {part id: [notes]}}

The harmonies in harmonizer.py sing the lead's words at the lead's moment.
These give the arrangement other shapes, all derived from the sung melody and
the song's chords by general rules (nothing is looked up per song):

  round   the melody itself enters again, 1-4 bars later (up to three
          entries). The delay is the one whose overlaps sound best.
  canon   one imitating voice at a diatonic interval (3rd, 5th, 6th...),
          a short distance behind. Interval and delay chosen the same way.
  echo    call and response: the end of each phrase is answered in the
          rest that follows it, on the pitch that fits the chord there.
  riff    a one-bar hook taken from the tune's own rhythm and contour,
          repeated every bar and re-fitted to that bar's chord, over a
          root-fifth bass line.

Round, canon and echo notes are the lead's own notes moved in time and
diatonically in pitch, one entry per melody note so the engine can sing them
in the lead's voice: `delay` (seconds) says where the note moves to, `rest`
marks notes this voice doesn't sing. Riff and bass notes are new notes on the
beat grid (`synth`: played as tones, not re-pitched from the lead).

How a choice is scored (lower is better), over the time the voices overlap:
  clash      2nds, 7ths and tritones between any two sounding voices,
             weighted by how long they ring together
  outside    a moved note that is not in the chord sounding at its new time
  doubling   unisons/octaves with another voice (a canon that mostly
             doubles the lead isn't a second line)
  thirds     3rds and 6ths are rewarded: they are what makes overlap sweet
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

from backend.harmony.harmonizer import LOWEST_VOICE
from backend.harmony.reharmonize import Chord
from backend.harmony.tis import MAJOR, MINOR

TEXTURES = {
    "round": {"label": "Round", "parts": (("second", "2nd entry"), ("third", "3rd entry"))},
    "canon": {"label": "Canon", "parts": (("canon", "Canon"),)},
    "echo": {"label": "Echo", "parts": (("echo", "Echo"),)},
    "riff": {"label": "Riff + bass", "parts": (("riff", "Riff"), ("bass", "Bass line"))},
}

CLASH = {1: 1.0, 11: 1.0, 6: 0.8, 2: 0.55, 10: 0.55}
SWEET = (3, 4, 8, 9)
W_CLASH = 3.0
W_OUTSIDE = 1.2
W_DOUBLING_CANON = 0.8
W_DOUBLING_ROUND = 0.15
W_SWEET = 0.6
MIN_OVERLAP = 0.35      # a delayed voice must sing over the lead at least this share of its time
HELD_S = 0.2            # shorter notes are passing: an outside pitch there is fine
MAX_CLASH_SHARE = 0.18  # a round/canon worse than this isn't offered
THIRD_ENTRY_MAX = 0.12  # the 3rd entry of a round only joins if it adds little clash


# ---------------------------------------------------------------------------
# Pitch and time helpers
# ---------------------------------------------------------------------------

def diatonic(pitch: int, steps: int, key: tuple[int, str]) -> int:
    """Move `steps` scale degrees in the key (chromatic notes keep their inflection)."""
    tonic, mode = key
    sc = MAJOR if mode == "major" else MINOR
    octave, pc = divmod(int(pitch) - tonic, 12)
    d = max(i for i, s in enumerate(sc) if s <= pc)
    o2, d2 = divmod(d + steps, 7)
    return tonic + 12 * (octave + o2) + sc[d2] + (pc - sc[d])


def beat_seconds(melody: Sequence[dict], beats: Sequence[float] | None) -> float:
    if beats is not None and len(beats) > 2:
        return float(np.median(np.diff(beats)))
    r = [(n["t1"] - n["t0"]) / n["duration"] for n in melody if n.get("duration") and "t0" in n and "t1" in n]
    return float(np.median(r)) if r else 0.5


def _time_of(beat: float, beats: Sequence[float], spb: float) -> float:
    """Seconds at a (fractional) beat index, extrapolating past the grid."""
    b = np.asarray(beats, dtype=float)
    if beat <= 0:
        return float(b[0] + beat * spb)
    if beat >= len(b) - 1:
        return float(b[-1] + (beat - (len(b) - 1)) * spb)
    return float(np.interp(beat, np.arange(len(b)), b))


def _sounding(notes):
    return [(n["t0"], n["t1"], int(n["pitch"])) for n in notes]


def overlap_stats(a, b) -> dict[str, float]:
    """Seconds of clash / doubling / 3rds-6ths / any overlap between two voices ((t0, t1, pitch) lists)."""
    out = {"clash": 0.0, "doubling": 0.0, "sweet": 0.0, "overlap": 0.0}
    a, b = sorted(a), sorted(b)
    j0 = 0
    for t0, t1, p in a:
        while j0 < len(b) and b[j0][1] <= t0:
            j0 += 1
        j = j0
        while j < len(b) and b[j][0] < t1:
            o = min(t1, b[j][1]) - max(t0, b[j][0])
            if o > 0:
                ic = abs(p - b[j][2]) % 12
                out["overlap"] += o
                out["clash"] += o * CLASH.get(ic, 0.0)
                out["doubling"] += o * (ic == 0)
                out["sweet"] += o * (ic in SWEET)
            j += 1
    return out


def _outside(notes, chord_at) -> float:
    s = 0.0
    for t0, t1, p in notes:
        if t1 - t0 < HELD_S:
            continue
        ch = chord_at(0.5 * (t0 + t1))
        if ch is not None and p % 12 not in ch.tones:
            s += t1 - t0
    return s


def _moved(melody, steps, delay_s, delay_beats, key, octave=0, rest=None) -> list[dict]:
    out = []
    for i, n in enumerate(melody):
        r = rest is not None and rest[i]
        out.append({
            "pitch": diatonic(int(n["pitch"]), steps, key) + octave, "melody_pitch": int(n["pitch"]),
            "t0": n["t0"] + delay_s, "t1": n["t1"] + delay_s,
            "start": (n["start"] + delay_beats) if n.get("start") is not None else None,
            "duration": n.get("duration"), "lyric": n.get("lyric", ""), "word_start": n.get("word_start", False),
            "delay": round(delay_s, 4), **({"rest": True} if r else {}),
        })
    return out


def _sung(part):
    return [n for n in part if not n.get("rest")]


def _too_low(part) -> bool:
    """A voice sung in the singer's voice may not go below E2 (nobody can sing it)."""
    return any(n["pitch"] < LOWEST_VOICE for n in _sung(part))


def _heard(n) -> int:
    """The pitch the singer actually sang (measured), else the transcribed one."""
    return int(round(n["heard"])) if n.get("heard") is not None else int(n["pitch"])


# ---------------------------------------------------------------------------
# Round and canon: exhaustive search (every option is scored, the best is kept)
# ---------------------------------------------------------------------------

W_RANGE = 0.6        # per semitone (per second) outside the singer's comfortable range
W_RANGE_HARD = 3.0   # per semitone (per second) outside the singer's full range
OCTAVES = (-24, -12, 0, 12, 24)


def _range_cost(notes, voice) -> float:
    low, high, s_low, s_high = voice
    c = 0.0
    for t0, t1, p in notes:
        c += (t1 - t0) * (W_RANGE * (max(0, s_low - p) + max(0, p - s_high))
                          + W_RANGE_HARD * (max(0, low - p) + max(0, p - high)))
    return c


def _entry_cost(entry, others, chord_at, w_doubling, voice) -> tuple[float, float, float]:
    """(total cost, seconds sung, share of overlap that clashes); inf if it barely overlaps."""
    me = _sounding(_sung(entry))
    dur = sum(t1 - t0 for t0, t1, _ in me) or 1.0
    clash = doubling = sweet = overlap = 0.0
    for o in others:
        s = overlap_stats(me, _sounding(_sung(o)))
        clash += s["clash"]; doubling += s["doubling"]; sweet += s["sweet"]; overlap += s["overlap"]
    if overlap < MIN_OVERLAP * dur:
        return float("inf"), dur, 1.0
    cost = (W_CLASH * clash + W_OUTSIDE * _outside(me, chord_at) + w_doubling * doubling - W_SWEET * sweet
            + _range_cost(me, voice))
    return cost, dur, clash / max(overlap, 1e-9)


def _score_entry(entry, others, chord_at, w_doubling, voice=(0, 127, 0, 127)) -> tuple[float, float]:
    """(cost per second of the entry, share of its time that clashes)."""
    c, d, share = _entry_cost(entry, others, chord_at, w_doubling, voice)
    return c / d, share


ROUND_BARS = (1, 2, 3, 4)


def plan_round(melody, chord_at, key, voice, spb: float, bar: int) -> dict[str, list[dict]] | None:
    """The melody against itself, a whole number of bars later.

    Searched exhaustively: every entry spacing (1-4 bars), every octave for each
    entry, two or three entries. Objective: the cost per sung second of all the
    entries together (each against the lead and the entries before it), subject to
    every entry's clash share staying under the limit. The minimum is returned.
    """
    best = None
    for bars in ROUND_BARS:
        db = bars * bar
        for o2 in OCTAVES:
            second = _moved(melody, 0, db * spb, db, key, o2)
            if _too_low(second):
                continue
            c2, d2, sh2 = _entry_cost(second, [melody], chord_at, W_DOUBLING_ROUND, voice)
            if sh2 > MAX_CLASH_SHARE or not np.isfinite(c2):
                continue
            cand = [(c2 / d2, {"second": second, "third": [{**n, "rest": True} for n in second]})]
            for o3 in OCTAVES:
                third = _moved(melody, 0, 2 * db * spb, 2 * db, key, o3)
                if _too_low(third):
                    continue
                c3, d3, sh3 = _entry_cost(third, [melody, second], chord_at, W_DOUBLING_ROUND, voice)
                if sh3 <= THIRD_ENTRY_MAX and np.isfinite(c3):
                    cand.append(((c2 + c3) / (d2 + d3), {"second": second, "third": third}))
            for j, parts in cand:
                if best is None or j < best[0] - 1e-12:
                    best = (j, parts)
    return None if best is None else best[1]


CANON_STEPS = (-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6)   # every diatonic interval (unison/octave are rounds)


def plan_canon(melody, chord_at, key, voice, spb: float, bar: int) -> dict[str, list[dict]] | None:
    """One imitating voice at a diatonic interval, a short distance behind.

    Searched exhaustively: every diatonic interval, every delay of 1 beat to 2
    bars, every octave. Objective: cost per sung second against the lead, with
    the clash share under the limit. The minimum is returned.
    """
    best = None
    for steps in CANON_STEPS:
        for db in range(1, 2 * bar + 1):
            for octave in OCTAVES:
                part = _moved(melody, steps, db * spb, db, key, octave)
                if _too_low(part):
                    continue
                cost, share = _score_entry(part, [melody], chord_at, W_DOUBLING_CANON, voice)
                if share <= MAX_CLASH_SHARE and np.isfinite(cost) and (best is None or cost < best[0] - 1e-12):
                    best = (cost, [{**n, "interval": steps + 7 * (octave // 12)} for n in part])
    return None if best is None else {"canon": best[1]}


# ---------------------------------------------------------------------------
# Echo (call and response): exact, phrase by phrase
# ---------------------------------------------------------------------------

ECHO_MAX_NOTES = 4
ECHO_STEPS = (0, 2, -2, 4, -3, 7, -7)   # unison, 3rds, 5th above / 4th below, octaves
ECHO_MIN_SPAN = 0.25
W_ECHO = 1.0          # reward per second of answer (an echo that fits is worth having)
W_WAIT = 0.15         # per beat of waiting after the call before answering
W_ECHO_STEP = 0.03    # per scale step away from the call's own pitches


def phrases(melody, spb: float) -> list[list[int]]:
    """Indices of each phrase: a new phrase starts after a rest of a beat or more."""
    gap = max(0.45, 0.9 * spb)
    out = [[0]] if melody else []
    for i in range(1, len(melody)):
        if melody[i]["t0"] - melody[i - 1]["t1"] >= gap:
            out.append([])
        out[-1].append(i)
    return out


def _echo_options(melody, ph, nxt, spb, beats, key, voice, chord_at):
    """Every answer to one phrase: (cost, fragment, delay, steps). Cost 0 = no answer."""
    end = melody[ph[-1]]["t1"]
    if beats is not None and len(beats) > 1:
        starts = [float(b) for b in beats if end + 0.1 <= b < nxt][:4] or [end + 0.15]
    else:
        starts = [end + 0.15 + k * spb for k in range(3)]
    opts = []
    for L in range(1, min(ECHO_MAX_NOTES, len(ph)) + 1):
        frag = ph[-L:]
        span = end - melody[frag[0]]["t0"]
        if span < ECHO_MIN_SPAN:
            continue
        for start in starts:
            d = start - melody[frag[0]]["t0"]
            if start + span > nxt - 0.1:
                continue
            for st in ECHO_STEPS:
                notes = [(melody[i]["t0"] + d, melody[i]["t1"] + d, diatonic(int(melody[i]["pitch"]), st, key)) for i in frag]
                for octave in OCTAVES:
                    q = [(t0, t1, p + octave) for t0, t1, p in notes]
                    if min(p for _, _, p in q) < LOWEST_VOICE:
                        continue
                    sung = sum(t1 - t0 for t0, t1, _ in q)
                    cost = (W_OUTSIDE * _outside(q, chord_at) + _range_cost(q, voice) + W_WAIT * (start - end) / spb
                            + W_ECHO_STEP * abs(st + 7 * octave // 12) - W_ECHO * sung)
                    opts.append((cost, frag, d, st, octave))
    return opts


def plan_echo(melody, chord_at, key, voice, spb: float, beats=None) -> dict[str, list[dict]] | None:
    """Each answer sits in its own rest (it must finish before the next phrase), so
    answers never meet and the total cost is a sum over phrases: the best answer
    per phrase (or none, cost 0) is the exact global optimum. Every suffix of up to
    4 notes, every beat in the rest, every interval and octave is tried."""
    rest = [True] * len(melody)
    delay = [0.0] * len(melody)
    steps_for = [0] * len(melody)
    octave_for = [0] * len(melody)
    ps = phrases(melody, spb)
    for k, ph in enumerate(ps):
        end = melody[ph[-1]]["t1"]
        nxt = melody[ps[k + 1][0]]["t0"] if k + 1 < len(ps) else end + 8 * spb
        opts = _echo_options(melody, ph, nxt, spb, beats, key, voice, chord_at)
        if not opts:
            continue
        cost, frag, d, st, octave = min(opts, key=lambda o: o[0])
        if cost >= 0:
            continue
        for i in frag:
            rest[i], delay[i], steps_for[i], octave_for[i] = False, d, st, octave
    if all(rest):
        return None
    out = []
    for i, n in enumerate(melody):
        out.append(_moved([n], steps_for[i], delay[i], delay[i] / spb, key, octave_for[i], [rest[i]])[0])
    return {"echo": out}


# ---------------------------------------------------------------------------
# Riff and bass
# ---------------------------------------------------------------------------

def _tone(ch: Chord | None, key, which: int) -> int:
    """Pitch class of the chord's root (0), third (1) or fifth (2)."""
    if ch is None:
        tonic, mode = key
        ch = Chord(tonic, "maj" if mode == "major" else "min")
    iv = ch.intervals
    return (ch.root + iv[min(which, len(iv) - 1)]) % 12


def _nearest(pcs, around: float, lo: int, hi: int) -> int:
    cands = [p for p in range(lo, hi + 1) if p % 12 in pcs]
    return min(cands, key=lambda p: (abs(p - around), p)) if cands else int(around)


def find_motif(melody, bar: int, phase: int) -> list[tuple[float, float, int]] | None:
    """The hook: the busiest early bar of the tune, as (beat in bar, length, scale steps from its first note)."""
    if not melody or melody[0].get("start") is None:
        return None
    first = int(np.floor((melody[0]["start"] - phase) / bar))
    best = None
    for k in range(first, first + 8):
        b0 = phase + k * bar
        notes = [n for n in melody if b0 <= n["start"] < b0 + bar]
        if not 2 <= len(notes) <= 6:
            continue
        score = (len({n["pitch"] for n in notes}), len(notes), -k)
        if best is None or score > best[0]:
            best = (score, b0, notes)
    if best is None:
        return None
    _, b0, notes = best
    offs = [round(2 * (n["start"] - b0)) / 2 for n in notes]
    motif = []
    base = notes[0]["pitch"]
    for j, n in enumerate(notes):
        nxt = offs[j + 1] if j + 1 < len(notes) else bar
        length = max(0.5, min(nxt - offs[j], round(2 * float(n.get("duration", 1.0))) / 2 or 0.5))
        motif.append((offs[j], length, _steps_between(base, int(n["pitch"]))))
    if len({m[0] for m in motif}) < len(motif):     # two notes on one slot after rounding
        return None
    return motif


def _steps_between(a: int, b: int) -> int:
    """Rough scale-step distance (a 2nd per 1-2 semitones)."""
    d = b - a
    s = int(round(abs(d) * 7 / 12))
    return s if d >= 0 else -s


def _note(pitch, start, length, beats, spb):
    t0 = _time_of(start, beats, spb)
    return {"pitch": int(pitch), "start": float(start), "duration": float(length),
            "t0": t0, "t1": _time_of(start + length, beats, spb) - 0.02,
            "lyric": "", "word_start": False, "synth": True}


W_STRONG_OUT = 2.0    # a riff note on a strong beat that isn't in the chord
W_WEAK_OUT = 0.4      # ... on a weak beat (a passing note)
W_OUT_OF_KEY = 3.0    # in neither the key nor the chord
W_SHAPE = 0.8         # per scale step the riff bends the hook's shape
W_REG_RIFF = 0.03
W_BASS_ROLE = {"down": (0.0, 1.2, 1.5), "half": (0.2, 0.6, 0.0)}   # root, third, fifth
W_APPROACH = 2.0      # an approach note that doesn't step into the next root
W_LEAP_BASS = 1.0
# Per second against the sung melody. A half step or tritone against the lead must cost
# more than any other rule the riff could break; a whole step (a passing tone over a
# chord tone) is ordinary and keeps the mild weight.
LEAD_CLASH = {1: 12.0, 11: 12.0, 6: 9.6, 2: W_CLASH * CLASH[2], 10: W_CLASH * CLASH[10]}


def _lead_clash(t0, t1, cands, lead) -> np.ndarray:
    c = np.zeros(len(cands))
    for s0, s1, q, w in lead:
        o = min(t1, s1) - max(t0, s0)
        if o > 0:
            c += w * o * np.array([LEAD_CLASH.get(abs(int(p) - q) % 12, 0.0) for p in cands])
    return c


def riff_problem(melody, chord_at, key, voice, beats, bar: int, phase: int):
    """The riff + bass lines' notes (fixed rhythm), candidates and costs:
    (voices, events, edge, pair) for optimal.two_voice."""
    from backend.harmony.tis import scale

    if beats is None or len(beats) < 2 or not melody or melody[0].get("start") is None:
        return None
    spb = beat_seconds(melody, beats)
    motif = find_motif(melody, bar, phase) or [(float(b), 1.0, [0, 2, 4, 2][b % 4]) for b in range(bar)]
    # Tones have a fixed pitch, so they're checked against what was really sung
    # (a transcribed note can be a semitone from the singer's actual pitch). Where
    # the two disagree (a slide, a scoop) the written note might be heard too: it
    # counts at half weight.
    lead = [(n["t0"], n["t1"], _heard(n), 1.0) for n in melody]
    lead += [(n["t0"], n["t1"], int(n["pitch"]), 0.5) for n in melody if _heard(n) != int(n["pitch"])]
    med = float(np.median([n["pitch"] for n in melody]))
    center = float(np.clip(med - 9, 50, 64))
    first = int(np.floor((melody[0]["start"] - phase) / bar))
    last = int(np.ceil((max(n["start"] + n["duration"] for n in melody) - phase) / bar))
    sc = scale(*key)
    bars = list(range(first, last))
    chords = [chord_at(_time_of(phase + k * bar + 0.1, beats, spb)) for k in bars]

    # The two lines' notes (fixed rhythm), with their candidates and costs.
    riff, bass = [], []          # dicts: note + cands + node + kind
    for idx, (k, ch) in enumerate(zip(bars, chords)):
        b0 = phase + k * bar
        tones = {_tone(ch, key, w) for w in (0, 1, 2)}
        pool = np.array([p for p in range(int(center) - 9, int(center) + 10) if p % 12 in tones or p % 12 in sc])
        for j, (off, length, st) in enumerate(motif):
            n = _note(0, b0 + off, length, beats, spb)
            strong = abs(off - round(off)) < 1e-6 and (length >= 1 or off == 0)
            pcs = pool % 12
            in_ch = np.isin(pcs, list(tones))
            node = ((~in_ch) * (W_STRONG_OUT if strong else W_WEAK_OUT)
                    + (~in_ch & ~np.isin(pcs, list(sc))) * W_OUT_OF_KEY
                    + W_REG_RIFF * np.abs(pool - center)
                    + _lead_clash(n["t0"], n["t1"], pool, lead))
            riff.append({"note": n, "cands": pool, "node": node, "j": j, "st": st})
        root_pc, third_pc, fifth_pc = (_tone(ch, key, w) for w in (0, 1, 2))
        half = bar / 2 if bar % 2 == 0 else bar - 1
        nxt = chords[idx + 1] if idx + 1 < len(chords) else None
        walk = nxt is not None and _tone(nxt, key, 0) != root_pc and bar >= 4
        slots = [("down", b0, half), ("half", b0 + half, bar - half - (1 if walk else 0))]
        if walk:
            slots.append(("approach", b0 + bar - 1, 1))
        for kind, start, length in slots:
            n = _note(0, start, length, beats, spb)
            if kind == "approach":
                pool = np.array([p for p in range(38, 56) if p % 12 in sc or p % 12 in tones])
                node = np.zeros(len(pool))
            else:
                pool = np.array([p for p in range(38, 56) if p % 12 in (root_pc, third_pc, fifth_pc)])
                w_root, w_third, w_fifth = W_BASS_ROLE[kind]
                node = np.array([w_root if p % 12 == root_pc else w_fifth if p % 12 == fifth_pc else w_third for p in pool])
            node = node + 0.04 * np.abs(pool - 45) + _lead_clash(n["t0"], n["t1"], pool, lead)
            bass.append({"note": n, "cands": pool, "node": node, "kind": kind})

    riff = [r for r in riff if r["note"]["t0"] >= 0]     # a bar can begin before the recording
    bass = [r for r in bass if r["note"]["t0"] >= 0]
    if not riff or not bass:
        return None
    voices = (riff, bass)

    def edge(v, k):
        P, C = voices[v][k - 1]["cands"][:, None], voices[v][k]["cands"][None, :]
        if v == 0:
            cur, prev = voices[0][k], voices[0][k - 1]
            want = cur["st"] - prev["st"]      # the hook's own step (or its restart, across a barline)
            steps = np.vectorize(lambda a, b: _diatonic_steps(int(a), int(b), sc))(P, C)
            w = W_SHAPE if cur["j"] > 0 else 0.5 * W_SHAPE
            return w * np.abs(steps - want) + 0.02 * np.abs(C - P)
        d = np.abs(C - P)
        e = 0.1 * d + W_LEAP_BASS * (d > 7)
        if voices[1][k - 1]["kind"] == "approach":
            e = e + W_APPROACH * ~np.isin(d, (1, 2))
        return e

    def pair(i, j):
        a, b = voices[0][i]["note"], voices[1][j]["note"]
        o = min(a["t1"], b["t1"]) - max(a["t0"], b["t0"])
        if o <= 0:
            return None
        ic = np.abs(voices[0][i]["cands"][:, None] - voices[1][j]["cands"][None, :]) % 12
        return W_CLASH * o * np.vectorize(lambda x: CLASH.get(int(x), 0.0))(ic)

    events = sorted([(voices[v][k]["note"]["t0"], v, k) for v in (0, 1) for k in range(len(voices[v]))])
    return voices, [(v, k) for _, v, k in events], edge, pair


def follow_singer(notes: list[dict], melody: Sequence[dict], tuning_cents: float = 0.0, window_s: float = 2.0) -> list[dict]:
    """Tune tones to the singer: each gets `cents` = the singer's tuning plus how sharp
    or flat they were singing around then (median over the lead notes within window_s)."""
    drift = [(0.5 * (n["t0"] + n["t1"]), 100.0 * (n["heard"] - round(n["heard"])))
             for n in melody if n.get("heard") is not None]
    out = []
    for n in notes:
        mid = 0.5 * (n["t0"] + n["t1"])
        near = [d for t, d in drift if abs(t - mid) <= window_s]
        c = tuning_cents + (float(np.median(near)) if near else 0.0)
        out.append({**n, "cents": round(float(np.clip(c, -50.0, 50.0)), 1)})
    return out


def riff_objective(problem, choice) -> float:
    """The riff + bass cost of any choice (candidate index per note, per line)."""
    voices, _, edge, pair = problem
    c = sum(float(voices[v][k]["node"][x]) for v in (0, 1) for k, x in enumerate(choice[v]))
    c += sum(float(edge(v, k)[choice[v][k - 1], choice[v][k]]) for v in (0, 1) for k in range(1, len(choice[v])))
    for i in range(len(voices[0])):
        for j in range(len(voices[1])):
            p = pair(i, j)
            if p is not None:
                c += float(p[choice[0][i], choice[1][j]])
    return c


def plan_riff(melody, chord_at, key, voice, beats, bar: int, phase: int) -> dict[str, list[dict]] | None:
    """Riff and bass, chosen together over the whole song (an exact joint Viterbi,
    see optimal.two_voice). The rhythm is fixed (the hook's rhythm each bar; bass
    on the downbeat, half-bar and an approach beat); every pitch of both lines is
    chosen to minimise one cost: chord fit by beat strength, clashes with the
    lead and with each other, keeping the hook's shape, register and smooth motion."""
    from backend.harmony.optimal import two_voice

    problem = riff_problem(melody, chord_at, key, voice, beats, bar, phase)
    if problem is None:
        return None
    voices, events, edge, pair = problem
    riff, bass = voices
    (ri, bi), _ = two_voice(events, [[r["node"] for r in riff], [b["node"] for b in bass]], edge, pair)
    out = {}
    for name, line, choice in (("riff", riff, ri), ("bass", bass, bi)):
        out[name] = [{**r["note"], "pitch": int(r["cands"][c])} for r, c in zip(line, choice)]
    return out


def _diatonic_steps(a: int, b: int, sc) -> int:
    lo, hi = sorted((a, b))
    steps = sum(1 for p in range(lo + 1, hi + 1) if p % 12 in sc)
    return steps if b >= a else -steps


# ---------------------------------------------------------------------------

def plan_textures(melody: Sequence[dict], chord_at: Callable[[float], Chord | None], key: tuple[int, str],
                  voice, beats: Sequence[float] | None = None, bar: int = 4, phase: int = 0) -> dict[str, dict]:
    """Every texture that works for this melody (ones that would clash are left out)."""
    melody = [n for n in melody if "t0" in n and "t1" in n]
    if len(melody) < 3:
        return {}
    spb = beat_seconds(melody, beats)
    bar = max(2, int(bar or 4))
    out = {}
    for name, plan in (("round", lambda: plan_round(melody, chord_at, key, voice, spb, bar)),
                       ("canon", lambda: plan_canon(melody, chord_at, key, voice, spb, bar)),
                       ("echo", lambda: plan_echo(melody, chord_at, key, voice, spb, beats)),
                       ("riff", lambda: plan_riff(melody, chord_at, key, voice, beats, bar, phase))):
        parts = plan()
        if parts:
            out[name] = parts
    return out


def _ordinal(k: int) -> str:
    return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def describe(name: str, parts: dict[str, list[dict]], key, spb: float, bar: int) -> str:
    """A short description of what was chosen, e.g. 'Enters 2 bars later'."""
    if name == "round":
        first = _sung(parts["second"])[0]
        bars = max(1, round(first["delay"] / spb / bar))
        n = 2 + bool(_sung(parts["third"]))
        return f"{n} entries · {bars} bar{'s' if bars > 1 else ''} apart"
    if name == "canon":
        n = _sung(parts["canon"])[0]
        beats = round(n["delay"] / spb)
        steps = int(n.get("interval", 0))
        where = "above" if steps > 0 else "below"
        when = f"{beats // bar} bar{'s' if beats // bar > 1 else ''}" if beats % bar == 0 else \
            f"{beats} beat{'s' if beats > 1 else ''}"
        return f"A {_ordinal(abs(steps) + 1)} {where}, {when} behind"
    if name == "echo":
        k = len({round(n['delay'], 2) for n in _sung(parts['echo'])})
        return f"Answers {k} phrase ending{'s' if k > 1 else ''}"
    if name == "riff":
        return "Hook from your tune · bass line"
    return ""


def place(y: np.ndarray, sr: int, melody: Sequence[dict], part: Sequence[dict], pad_s: float = 0.04,
          fade_s: float = 0.015) -> np.ndarray:
    """Move a rendered voice in time: each run of sung notes (same `delay`) is cut
    from `y` (rendered at the lead's own times) and laid down `delay` seconds later;
    `rest` notes are dropped. Unchanged if nothing moves."""
    delays = [float(h.get("delay") or 0.0) for h in part]
    rests = [bool(h.get("rest")) for h in part]
    if not any(delays) and not any(rests):
        return y
    out = np.zeros(len(y) + int(np.ceil(max(0.0, max(delays)) * sr)) + 1, dtype=np.float32)
    fade = max(1, int(fade_s * sr))
    i = 0
    while i < len(part):
        if rests[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(part) and not rests[j + 1] and abs(delays[j + 1] - delays[i]) < 1e-6:
            j += 1
        a = max(0, int((melody[i]["t0"] - pad_s) * sr))
        b = min(len(y), int((melody[j]["t1"] + pad_s) * sr))
        if b > a:
            seg = y[a:b].astype(np.float32).copy()
            f = min(fade, len(seg) // 2)
            if f:
                ramp = np.linspace(0, 1, f, dtype=np.float32)
                seg[:f] *= ramp
                seg[-f:] *= ramp[::-1]
            d = int(round(delays[i] * sr))
            s = a + d
            if s < 0:
                seg, s = seg[-s:], 0
            out[s:s + len(seg)] += seg[: len(out) - s]
        i = j + 1
    return out
