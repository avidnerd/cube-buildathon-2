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

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
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
    # A 3rd above and a 6th below are the same note an octave apart, which is
    # thin. With the top part a 3rd above, the chord's remaining note sits a
    # 4th below the lead, so the three voices spell a full chord.
    "classic": {"label": "3rd above + 4th below (full chord)",
                "parts": (("high", "Harmony above", +1, 3.5), ("low", "Harmony below", -1, 5.0))},
    "close": {"label": "3rds above and below (tight)",
              "parts": (("high", "Harmony above", +1, 3.5), ("low", "Harmony below", -1, 3.5))},
    "stack": {"label": "3rd + 5th above (stacked)",
              "parts": (("high", "Top harmony", +1, 7.0), ("low", "Middle harmony", +1, 3.5))},
}

# ---------------------------------------------------------------------------
# The scoring model: named musical features x weights
# ---------------------------------------------------------------------------
#
# Every candidate harmony note gets a vector of features that describe its
# musical relationship to the lead, the chord and the line it continues
# ("a diatonic 3rd", "a chord tone on a held word", "parked while the lead
# moves", "measured clash with what's playing"...). Its cost is weights . features.
# The weights are a *style*: the defaults below are hand-set, and fit_style()
# learns them from a musician's corrections (a structured perceptron), so the
# tool adopts the user's taste instead of imposing a formula. Because the
# features are relationships, not notes, a learned style carries to new songs.

# Scale-degree pairing, separately for notes above and below the lead: a
# taught upper line says nothing about what the voice underneath should do.
DEGREE_PAIRS = tuple(f"deg_{d}_{a}_{b}" for d in ("up", "dn") for a in range(1, 8) for b in range(1, 8))

NODE_FEATURES = (
    "clash",            # dissonance beyond the consonant band against a *real, measured* band
    "clash_guess",      # same, but against guessed chords (a cappella): a weaker signal
    "band_support",     # how strongly that note is actually sounding in the real band (0..1)
    "chord_tone",       # in the chord at that moment
    "chord_tone_held",  # chord tone, scaled by how long the note is held (stressed words)
    "in_key",
    "out_of_key",       # in neither the key nor the chord
    "dist_target",      # semitones away from the arrangement's target interval
    "unison",           # same note as the lead
    "unison_low",       # unison while the lead is low in its range (pickups often join the melody)
    "unison_start",     # unison on the first notes of a phrase
    "octave_double",    # same note name as the lead, different octave
    "third_sixth",      # a 3rd or 6th from the lead (sweet)
    "fourth_fifth",     # a 4th or 5th from the lead (open)
    "diatonic_third",   # exactly a scale-third on the arrangement's side
    "step_clash",       # a 2nd/7th against the lead, scaled by how long it's held
    "tritone",          # a tritone against the lead, scaled by how long it's held
    "wrong_side",       # below the lead for an upper part (or above for a lower one)
    "comfort",          # semitones outside the singer's comfortable range
    "part_double",      # same note name as another harmony part
    "part_rub",         # a 2nd against another harmony part
    "completes_triad",  # with the lead and the other part(s), spells a major/minor triad
)
# Plus DEGREE_PAIRS: lead on scale degree a -> harmony on degree b (a singer's
# instinct, learnable). At most one is active per candidate, so they're stored
# as an index rather than ~100 mostly-zero columns.
EDGE_FEATURES = (
    "motion",           # semitones the harmony moves
    "same_interval",    # keeps the same diatonic interval to the lead as before (parallel)
    "static",           # harmony holds while the lead moves (parked)
    "similar_motion",   # moves the same direction as the lead
    "parallel_perfect", # parallel unisons/5ths/8ves with the lead
    "leap",             # jumps more than a major 3rd
)

# Safety features are physics, not taste: learning never touches them, so a
# style learned on one song can't talk the harmony into a real clash on another.
FROZEN = frozenset({"clash", "band_support", "step_clash", "tritone", "wrong_side", "comfort"})

DEFAULT_WEIGHTS: dict[str, float] = {
    "clash": 8.0, "clash_guess": 1.5, "band_support": -2.5, "chord_tone": -0.3, "chord_tone_held": -1.0, "in_key": -0.3, "out_of_key": 0.6,
    "dist_target": 0.15, "unison": 2.0, "unison_low": -0.8, "unison_start": -0.6, "octave_double": 1.2,
    "third_sixth": -0.5, "fourth_fifth": 0.0, "diatonic_third": -0.6, "step_clash": 3.0, "tritone": 2.5,
    "wrong_side": 4.0, "comfort": 1.0, "part_double": 2.0, "part_rub": 1.5, "completes_triad": -1.5,
    "motion": 0.12, "same_interval": -0.5, "static": 0.4, "similar_motion": -0.2,
    "parallel_perfect": 0.6, "leap": 0.5,
    **{f: 0.0 for f in DEGREE_PAIRS},
}
NET_WINDOW = 14        # semitones around the lead the learned model was trained on
CONSONANT_BAND = 0.45  # measured dissonance within this of the best counts as no clash
CLASH_FULL_S = 0.25    # clashes count fully once held this long (shorter ones pass by)
PHRASE_GAP_S = 0.35    # notes further apart than this are in different phrases

STYLE_PATH = Path(__file__).with_name("style.json")


def load_style() -> dict[str, float]:
    """The learned style if one has been fitted, else the defaults."""
    w = dict(DEFAULT_WEIGHTS)
    if STYLE_PATH.exists():
        try:
            w.update({k: float(v) for k, v in json.loads(STYLE_PATH.read_text())["weights"].items() if k in w})
        except (ValueError, KeyError):
            pass
    return w


def _is_triad(pcs: set[int]) -> bool:
    if len(pcs) != 3:
        return False
    return any({(r + i) % 12 for i in q} == pcs for r in range(12) for q in ((0, 4, 7), (0, 3, 7)))


def _diatonic_steps(a: int, b: int, sc: frozenset[int]) -> int:
    """Signed scale steps from a to b (chromatic notes round toward a)."""
    lo, hi = sorted((a, b))
    steps = sum(1 for p in range(lo + 1, hi + 1) if p % 12 in sc)
    return steps if b >= a else -steps


@dataclass
class Lattice:
    """Every candidate's features, for decoding or training."""
    cands: list[np.ndarray]          # per note: candidate pitches
    node: list[np.ndarray]           # per note: (C, len(NODE_FEATURES)) float32
    deg: list[np.ndarray]            # per note: (C,) index into DEGREE_PAIRS, -1 if none
    edge: list[np.ndarray]           # per transition i-1 -> i: (C_prev, C, len(EDGE_FEATURES)) float32
    raw: list[np.ndarray] | None = None  # per note: (C, len(RAW_FEATURES)) context for the learned scorer


# Raw context for the learned (neural) scorer: what a musician "sees" when choosing
# a harmony note, without hand-made judgements on top.
_IV_RANGE = 15
RAW_FEATURES = (
    [f"iv_{d}" for d in range(-_IV_RANGE, _IV_RANGE + 1)]          # interval to the lead (one-hot)
    + [f"cand_pc_{k}" for k in range(12)]                          # candidate's pitch class, relative to the key
    + [f"lead_pc_{k}" for k in range(12)]                          # lead's pitch class, relative to the key
    + [f"band_rel_cand_{k}" for k in range(12)]                    # band energy k semitones above the candidate
    + [f"band_rel_key_{k}" for k in range(12)]                     # band energy by key-relative pitch class
    + ["minor", "measured", "log_dur", "phrase_pos", "lead_from_prev", "lead_to_next",
       "lead_height", "cand_height", "first_in_phrase", "last_in_phrase"]
)


def _raw_features(opts: np.ndarray, m: int, tonic: int, mode: str, chroma: np.ndarray, measured: bool,
                  dur: float, pos: int, prev_iv: float, next_iv: float, lead_mid: float,
                  first: bool, last: bool) -> np.ndarray:
    C = len(opts)
    X = np.zeros((C, len(RAW_FEATURES)), dtype=np.float32)
    iv = np.clip(opts - m, -_IV_RANGE, _IV_RANGE) + _IV_RANGE
    X[np.arange(C), iv] = 1.0
    o = 2 * _IV_RANGE + 1
    X[np.arange(C), o + (opts - tonic) % 12] = 1.0
    o += 12
    X[:, o + (m - tonic) % 12] = 1.0
    o += 12
    ch = chroma / max(float(chroma.max()), 1e-9)
    X[:, o:o + 12] = np.stack([np.roll(ch, -int(p % 12)) for p in opts])
    o += 12
    X[:, o:o + 12] = np.roll(ch, -tonic)
    o += 12
    X[:, o:] = [mode == "minor", measured, np.log(max(dur, 0.05)), min(pos, 6) / 6.0,
                np.clip(prev_iv, -12, 12) / 12.0, np.clip(next_iv, -12, 12) / 12.0,
                (m - lead_mid) / 12.0, 0.0, first, last]
    X[:, -3] = (opts - m) / 12.0
    return X


def build_lattice(
    melody: Sequence[dict],
    chord_at: Callable[[float], Chord | None],
    key: tuple[int, str],
    voice: tuple[int, int, int, int],
    side: int,
    target: float,
    scene_for: Callable[[dict], Scene] | None = None,
    others: Sequence[Sequence[int]] = (),
    must_include: Sequence[int | None] | None = None,
    max_iv: int | None = None,
    compact: bool = False,
) -> Lattice:
    tonic, mode = key
    sc = scale(tonic, mode)
    sc_ext = sc | ({(tonic + 11) % 12} if mode == "minor" else set())  # harmonic-minor leading tone
    low, high, s_low, s_high = voice
    lead_mid = float(np.median([n["pitch"] for n in melody]))

    cands, node, degs, raws = [], [], [], []
    pos_in_phrase = 0
    for k, n in enumerate(melody):
        if k > 0 and n["t0"] - melody[k - 1]["t1"] >= PHRASE_GAP_S:
            pos_in_phrase = 0
        m = int(n["pitch"])
        ch = chord_at(0.5 * (n["t0"] + n["t1"]))
        base = list(ch.tones) if ch is not None else [tonic, (tonic + (4 if mode == "major" else 3)) % 12, (tonic + 7) % 12]
        pool = set(range(low, high + 1)) | {m}
        if max_iv is not None:
            pool = {p for p in pool if abs(p - m) <= max_iv}
        if must_include is not None and must_include[k] is not None:
            pool.add(int(must_include[k]))
        opts = np.array(sorted(pool), dtype=int)
        pcs = opts % 12
        ic = np.abs(opts - m) % 12
        held = min(1.0, (n["t1"] - n["t0"]) / CLASH_FULL_S)
        tones = ch.tones if ch is not None else frozenset()
        scene = scene_for(n) if scene_for is not None else chord_scene(base, m)
        d = candidate_dissonance(scene, opts, m)
        iv = (opts - m) * side
        steps = np.array([_diatonic_steps(m, int(p), sc) for p in opts])
        unison = (opts == m).astype(float)
        excess = np.maximum(0.0, d - d.min() - CONSONANT_BAND)
        F = {
            "clash": excess if scene.measured else np.zeros(len(opts)),
            "clash_guess": np.zeros(len(opts)) if scene.measured else excess,
            "band_support": (np.clip(scene.chroma[pcs] / max(float(np.max(scene.chroma)), 1e-9), 0, 1)
                             if scene.measured else np.zeros(len(opts))),
            "chord_tone": np.isin(pcs, list(tones)).astype(float),
            "in_key": np.isin(pcs, list(sc_ext)).astype(float),
            "out_of_key": (~np.isin(pcs, list(sc_ext | tones))).astype(float),
            "dist_target": np.abs(iv - target),
            "unison": unison,
            "unison_low": unison * float(np.clip((lead_mid - m) / 5.0, 0.0, 1.0)),
            "unison_start": unison * float(pos_in_phrase < 3),
            "octave_double": ((pcs == m % 12) & (opts != m)).astype(float),
            "third_sixth": np.isin(ic, (3, 4, 8, 9)).astype(float),
            "fourth_fifth": np.isin(ic, (5, 7)).astype(float),
            "diatonic_third": ((steps == 2 * side) & (opts != m)).astype(float),
            "step_clash": (0.4 + 0.6 * held) * np.isin(ic, (1, 2, 10, 11)),
            "tritone": (0.4 + 0.6 * held) * (ic == 6),
            "wrong_side": (iv < 0).astype(float),
            "comfort": (np.maximum(0, opts - s_high) + np.maximum(0, s_low - opts)).astype(float),
            "part_double": np.zeros(len(opts)),
            "part_rub": np.zeros(len(opts)),
            "completes_triad": np.zeros(len(opts)),
        }
        F["chord_tone_held"] = F["chord_tone"] * held
        # Scale-degree pairing (only when both notes are in the key's scale).
        deg = {pc: i + 1 for i, pc in enumerate(sorted(sc, key=lambda q: (q - tonic) % 12))}
        ld = deg.get(m % 12)
        di = np.full(len(opts), -1, dtype=np.int16)
        if ld is not None:
            for q, pc in enumerate(pcs):
                hd = deg.get(int(pc))
                if hd is not None and opts[q] != m:
                    di[q] = _DEG_INDEX[f"deg_{'up' if opts[q] > m else 'dn'}_{ld}_{hd}"]
        for other in others:
            o = int(other[k])
            F["part_double"] += (pcs == o % 12)
            F["part_rub"] += held * np.isin(np.abs(opts - o) % 12, (1, 2, 10, 11))
        if others:
            have = {m % 12} | {int(o[k]) % 12 for o in others}
            for q, pc in enumerate(pcs):
                F["completes_triad"][q] = float(_is_triad(have | {int(pc)}))
        cands.append(opts)
        node.append(np.stack([F[f] for f in NODE_FEATURES], axis=1).astype(np.float32))
        degs.append(di)
        nxt = melody[k + 1] if k + 1 < len(melody) else None
        prv = melody[k - 1] if k > 0 else None
        first = pos_in_phrase == 0
        last = nxt is None or nxt["t0"] - n["t1"] >= PHRASE_GAP_S
        rf = _raw_features(opts, m, tonic, mode, scene.chroma, scene.measured, n["t1"] - n["t0"],
                           pos_in_phrase, (m - int(prv["pitch"])) if prv else 0.0,
                           (int(nxt["pitch"]) - m) if nxt else 0.0, lead_mid, first, last)
        raws.append(rf.astype(np.float16) if compact else rf)
        pos_in_phrase += 1

    steps_all = [np.array([_diatonic_steps(int(n["pitch"]), int(p), sc) for p in c]) for n, c in zip(melody, cands)]
    edge = []
    for i in range(1, len(melody)):
        prev, cur = melody[i - 1], melody[i]
        pm, cm = int(prev["pitch"]), int(cur["pitch"])
        P, C = cands[i - 1][:, None], cands[i][None, :]
        joined = cur["t0"] - prev["t1"] < PHRASE_GAP_S
        short = (cur["t1"] - cur["t0"]) < 0.15
        k = (1.5 if short else 1.0) if joined else 0.25
        dP = C - P
        moved = (dP != 0) & (cm != pm)
        perfect = np.isin(np.abs(P - pm) % 12, (0, 7)) & np.isin(np.abs(C - cm) % 12, (0, 7))
        E = {
            "motion": k * np.abs(dP),
            "same_interval": k * (steps_all[i - 1][:, None] == steps_all[i][None, :]),
            "static": k * ((dP == 0) & (cm != pm)),
            "similar_motion": k * ((np.sign(dP) == np.sign(cm - pm)) & moved),
            "parallel_perfect": (moved & perfect).astype(float),
            "leap": k * (np.abs(dP) > 4),
        }
        edge.append(np.stack([np.broadcast_to(E[f], (len(cands[i - 1]), len(cands[i])))
                              for f in EDGE_FEATURES], axis=2).astype(np.float32))
    if compact:
        edge = [e.astype(np.float16) for e in edge]
    return Lattice(cands, node, degs, edge, raws)


_DEG_INDEX = {f: i for i, f in enumerate(DEGREE_PAIRS)}
_F = {f: i for i, f in enumerate(NODE_FEATURES)}


def _vectors(w: dict[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(dense node weights, degree-pair weights + a trailing 0 for 'none', edge weights)."""
    return (np.array([w[f] for f in NODE_FEATURES]),
            np.array([w[f] for f in DEGREE_PAIRS] + [0.0]),
            np.array([w[f] for f in EDGE_FEATURES]))


def _node_cost(lat: Lattice, i: int, wn: np.ndarray, wd: np.ndarray) -> np.ndarray:
    return lat.node[i] @ wn + wd[lat.deg[i]]  # index -1 hits the trailing 0


def decode(lat: Lattice, w: dict[str, float]) -> list[int]:
    """Viterbi: index of the chosen candidate per note."""
    wn, wd, we = _vectors(w)
    acc = _node_cost(lat, 0, wn, wd)
    back = []
    for i in range(1, len(lat.cands)):
        total = acc[:, None] + lat.edge[i - 1] @ we
        back.append(np.argmin(total, axis=0))
        acc = total.min(axis=0) + _node_cost(lat, i, wn, wd)
    j = int(np.argmin(acc))
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    return path[::-1]


def path_features(lat: Lattice, path: Sequence[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fn = np.sum([lat.node[i][j] for i, j in enumerate(path)], axis=0, dtype=np.float64)
    fd = np.zeros(len(DEGREE_PAIRS))
    for i, j in enumerate(path):
        if lat.deg[i][j] >= 0:
            fd[lat.deg[i][j]] += 1
    fe = sum((lat.edge[i - 1][path[i - 1], path[i]] for i in range(1, len(path))), np.zeros(len(EDGE_FEATURES)))
    return fn, fd, fe


def plan_part(
    melody: Sequence[dict],
    chord_at: Callable[[float], Chord | None],
    key: tuple[int, str],
    voice: tuple[int, int, int, int],
    side: int,
    target: float,
    scene_for: Callable[[dict], Scene] | None = None,
    others: Sequence[Sequence[int]] = (),
    weights: dict[str, float] | None = None,
    personal: dict | None = None,
) -> list[dict]:
    """melody: notes with pitch, t0, t1 (seconds). Returns harmony notes with the same timing.

    scene_for(note) -> what's sounding under that note (measured from the real
    accompaniment). Without it, the chord at that time is used as a soft pad.
    others: pitches (one per melody note) of harmony parts already planned;
    this part avoids doubling them so the voices spell out a full chord.
    weights: a style (see fit_style); defaults to the learned/default style.
    """
    if not melody:
        return []
    net = None
    if weights is None:  # the learned model, if trained (with the user's personal adjustment)
        from backend.harmony import neural

        net = neural.base_model()
    # The learned model only knows candidates within its training window around the lead.
    lat = build_lattice(melody, chord_at, key, voice, side, target, scene_for, others,
                        max_iv=NET_WINDOW if net is not None else None)
    if net is not None:
        # The arrangement's side is a rule, not a preference: an upper part never
        # goes below the lead (unison allowed), a lower part never above it.
        # personal: this song's adjustments from the user's fixes (never applied to other songs)
        path = net.decode(lat, bias=neural.personal_bias(lat, personal))  # includes the side rule
    else:
        path = decode(lat, weights or load_style())
    out = []
    for n, opts, j in zip(melody, lat.cands, path):
        out.append({
            "pitch": int(opts[j]), "melody_pitch": int(n["pitch"]),
            "t0": n["t0"], "t1": n["t1"],
            "start": n.get("start"), "duration": n.get("duration"),
            "lyric": n.get("lyric", ""), "word_start": n.get("word_start", False),
        })
    return out


def plan_parts(melody, chord_at, key, voice, arrangement: str = "classic",
               scene_for: Callable[[dict], Scene] | None = None,
               weights: dict[str, float] | None = None,
               personal: dict | None = None) -> dict[str, list[dict]]:
    arr = ARRANGEMENTS[arrangement]
    weights = weights or load_style()
    if scene_for is not None:  # measure each note's scene once for all parts
        cache = {id(n): scene_for(n) for n in melody}
        scene_for = lambda n, _c=cache: _c[id(n)]  # noqa: E731
    out: dict[str, list[dict]] = {}
    for pid, _, side, target in arr["parts"]:  # later parts fill in around earlier ones
        others = [[h["pitch"] for h in part] for part in out.values()]
        out[pid] = mirror_runs(melody, plan_part(melody, chord_at, key, voice, side, target, scene_for, others, weights, personal))
    return out


RUN_NOTE_S = 0.2    # notes shorter than this, joined to a neighbour, are embellishments
RUN_JOIN_S = 0.06


def mirror_runs(melody: Sequence[dict], part: list[dict]) -> list[dict]:
    """Embellishments don't get harmony notes of their own.

    Through a singer's quick run or grace notes, the backing voice simply
    holds the note of the held melody note the run decorates: it sings the
    plain melody's harmony, not a copy of the ornament.
    """
    n = len(melody)
    if n < 2:
        return part
    dur = [m["t1"] - m["t0"] for m in melody]
    joined = [False] + [melody[k]["t0"] - melody[k - 1]["t1"] < RUN_JOIN_S for k in range(1, n)]
    out = [dict(h) for h in part]
    k = 0
    while k < n:
        if dur[k] >= RUN_NOTE_S:
            k += 1
            continue
        # the run: consecutive quick notes joined together
        j = k
        while j + 1 < n and dur[j + 1] < RUN_NOTE_S and joined[j + 1]:
            j += 1
        anchors = [a for a in (k - 1 if k > 0 and joined[k] else None, j + 1 if j + 1 < n and joined[j + 1] else None)
                   if a is not None]
        if anchors:
            a = max(anchors, key=lambda q: dur[q])  # the held note the run belongs to
            for q in range(k, j + 1):
                out[q]["pitch"] = int(part[a]["pitch"])  # hold it through the run
        k = j + 1
    return out


# ---------------------------------------------------------------------------
# Chords implied by the voices
# ---------------------------------------------------------------------------

def implied_chords(melody: Sequence[dict], parts: Sequence[Sequence[dict]], beats: Sequence[float],
                   n_beats: int, key: tuple[int, str], fallback: Sequence[Chord | None],
                   every: int = 1, phase: int = 0) -> list[Chord | None]:
    """With no band, the chord is whatever the lead and harmony voices spell.
    Per beat: duration-weighted pitch classes of all voices, matched to chord
    templates (triads preferred, staying put preferred), smoothed by holding the
    previous chord where the voices are silent or ambiguous."""
    from backend.harmony.reharmonize import CANDIDATES, MASKS

    beats = np.asarray(beats, dtype=float)
    sc = scale(*key)
    in_key = np.array([c.tones <= sc for c in CANDIDATES], dtype=float)
    triad = np.array([len(c.tones) == 3 and c.quality in ("maj", "min") for c in CANDIDATES], dtype=float)
    unit = MASKS / np.linalg.norm(MASKS, axis=1, keepdims=True)
    def bt(b):
        return beats[b] if b < len(beats) else beats[-1] + (b - len(beats) + 1) * (beats[-1] - beats[-2])

    # One chord per harmonic-rhythm segment (e.g. per bar, starting at the downbeat).
    every = max(1, int(every))
    starts = sorted({0} | {b for b in range(n_beats) if (b - phase) % every == 0})
    seg_of = np.searchsorted(starts, np.arange(n_beats), side="right") - 1
    seg_chord: dict[int, Chord | None] = {}
    out: list[Chord | None] = []
    prev: int | None = None
    for b in range(n_beats):
        si = int(seg_of[b])
        if si in seg_chord:
            out.append(seg_chord[si])
            continue
        t0 = bt(starts[si])
        t1 = bt(starts[si + 1]) if si + 1 < len(starts) else bt(n_beats)
        w = np.zeros(12)
        for voice in (melody, *parts):
            for n in voice:
                ov = min(n["t1"], t1) - max(n["t0"], t0)
                if ov > 0:
                    w[int(n["pitch"]) % 12] += ov
        if w.sum() < 0.05 or np.count_nonzero(w) < 2:
            seg_chord[si] = CANDIDATES[prev] if prev is not None else (fallback[b] if b < len(fallback) else None)
            out.append(seg_chord[si])
            continue
        score = unit @ (w / np.linalg.norm(w)) + 0.08 * in_key + 0.06 * triad
        # the chord that was planned here (the base progression) is the natural reading
        fb = fallback[b] if b < len(fallback) else None
        if fb is not None:
            score[fb.index] += 0.12
        if prev is not None:
            score[prev] += 0.05
        prev = int(np.argmax(score))
        seg_chord[si] = CANDIDATES[prev]
        out.append(seg_chord[si])
    return out


# ---------------------------------------------------------------------------
# Learning a style from corrections (structured perceptron)
# ---------------------------------------------------------------------------

@dataclass
class Example:
    """One corrected part: the lattice it was chosen from and the user's notes."""
    lattice: Lattice
    gold: list[int]   # index into lattice.cands per note


def make_example(melody, chord_at, key, voice, side, target, gold_pitches, scene_for=None, others=(),
                 max_iv: int | None = None, compact: bool = False) -> Example:
    lat = build_lattice(melody, chord_at, key, voice, side, target, scene_for, others, must_include=gold_pitches,
                        max_iv=max_iv, compact=compact)
    gold = [int(np.flatnonzero(c == g)[0]) for c, g in zip(lat.cands, gold_pitches)]
    return Example(lat, gold)


def agreement(examples: Sequence[Example], w: dict[str, float]) -> float:
    hit = tot = 0
    for ex in examples:
        pred = decode(ex.lattice, w)
        hit += sum(int(ex.lattice.cands[i][a] == ex.lattice.cands[i][b]) for i, (a, b) in enumerate(zip(pred, ex.gold)))
        tot += len(ex.gold)
    return hit / max(tot, 1)


def fit_style(examples: Sequence[Example], w0: dict[str, float] | None = None, epochs: int = 150,
              lr: float = 0.1, prior: float = 0.02, frozen: frozenset[str] = FROZEN) -> dict[str, float]:
    """Averaged structured perceptron, pulled gently back toward the starting style.

    For each example, decode with the current weights; wherever the user's
    notes are not the cheapest path, move the weights so that their features
    become cheaper than the predicted path's. `prior` keeps weights near w0 so
    a few corrections nudge the style rather than overfit one song.
    """
    w0 = dict(w0 or DEFAULT_WEIGHTS)
    wn0, wd0, we0 = _vectors(w0)
    wd0 = wd0[:-1]
    free_n = np.array([f not in frozen for f in NODE_FEATURES], dtype=float)
    free_e = np.array([f not in frozen for f in EDGE_FEATURES], dtype=float)
    wn, wd, we = wn0.copy(), wd0.copy(), we0.copy()
    sn, sd, se, count = np.zeros_like(wn), np.zeros_like(wd), np.zeros_like(we), 0

    def as_dict(a, b, c):
        return dict(zip(NODE_FEATURES, map(float, a))) | dict(zip(DEGREE_PAIRS, map(float, b))) | dict(zip(EDGE_FEATURES, map(float, c)))

    order = list(range(len(examples)))
    rng = np.random.default_rng(0)
    for _ in range(epochs):
        rng.shuffle(order)
        for k in order:
            ex = examples[k]
            pred = decode(ex.lattice, as_dict(wn, wd, we))
            if pred != ex.gold:
                gn, gd, ge = path_features(ex.lattice, ex.gold)
                pn, pd, pe = path_features(ex.lattice, pred)
                wn -= lr * free_n * (gn - pn)
                wd -= lr * (gd - pd)
                we -= lr * free_e * (ge - pe)
            wn -= lr * prior * (wn - wn0)
            wd -= lr * prior * (wd - wd0)
            we -= lr * prior * (we - we0)
            sn += wn
            sd += wd
            se += we
            count += 1
    return as_dict(sn / count, sd / count, se / count)


def save_style(w: dict[str, float], note: str = "") -> None:
    STYLE_PATH.write_text(json.dumps({"note": note, "weights": {k: round(v, 4) for k, v in w.items()}}, indent=1))


# ---------------------------------------------------------------------------
# Rendering in the lead's voice: TD-PSOLA
# ---------------------------------------------------------------------------

GLIDE_S = 0.08
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


def smooth_f0(hz: np.ndarray) -> np.ndarray:
    """Pitch track for grain placement: octave slips folded back, short voicing
    gaps bridged, cycle-to-cycle jitter smoothed; vibrato (5-7 Hz) survives."""
    f = np.asarray(hz, dtype=float).copy()
    v = ~np.isnan(f)
    if v.sum() < 3:
        return f
    lg = np.full_like(f, np.nan)
    lg[v] = np.log2(f[v])
    # octave slips: a frame an octave away from the local median comes back
    idx = np.flatnonzero(v)
    for k, i in enumerate(idx):
        win = lg[idx[max(0, k - 5): k + 6]]
        med = np.median(win)
        d = lg[i] - med
        if abs(d) > 0.75:
            lg[i] -= np.round(d)
    # bridge gaps of <= 4 frames (40 ms) inside a voiced stretch
    i = 0
    while i < len(lg):
        if np.isnan(lg[i]):
            j = i
            while j < len(lg) and np.isnan(lg[j]):
                j += 1
            if 0 < i and j < len(lg) and j - i <= 4:
                lg[i:j] = np.linspace(lg[i - 1], lg[j], j - i + 2)[1:-1]
            i = j
        else:
            i += 1
    # 3-frame median then 3-frame mean (30 ms): kills jitter, keeps vibrato
    out = lg.copy()
    for i in np.flatnonzero(~np.isnan(lg)):
        w = lg[max(0, i - 1): i + 2]
        out[i] = np.median(w[~np.isnan(w)])
    sm = out.copy()
    for i in np.flatnonzero(~np.isnan(out)):
        w = out[max(0, i - 1): i + 2]
        sm[i] = np.mean(w[~np.isnan(w)])
    return 2.0 ** sm


@lru_cache(maxsize=64)
def _hann(n: int) -> np.ndarray:
    return np.hanning(max(n, 3))


def psola(x: np.ndarray, sr: int, f0_times: np.ndarray, f0_hz: np.ndarray,
          shift_t: np.ndarray, shift_s: np.ndarray, target: tuple[np.ndarray, np.ndarray] | None = None) -> np.ndarray:
    """Pitch-shift x by the semitone curve (shift_t, shift_s), keeping timing.

    f0_hz: the lead's pitch track (nan where unvoiced). Unvoiced sound
    (consonants, breaths) is passed through unshifted.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    f0_hz = smooth_f0(f0_hz)
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

    # 1. Analysis marks: one per glottal cycle in voiced regions, fixed steps
    #    elsewhere. Peaks are found on a low-passed copy: breathy highs and
    #    formant ripples create false peaks that make the cuts jump around
    #    (phase noise = grainy, crackly texture).
    from scipy.signal import butter, sosfiltfilt

    f0v = f0_hz[~np.isnan(f0_hz)]
    cut = float(np.clip(1.3 * np.percentile(f0v, 90), 300.0, 1200.0)) if f0v.size else 800.0
    xl = sosfiltfilt(butter(4, cut, fs=sr, output="sos"), x)
    marks, periods, voiced = [], [], []
    pos = 0.0
    unv = UNVOICED_STEP_S * sr
    while pos < n:
        f = f0_at(pos)
        if f > 0:
            T = sr / f
            a, b = int(pos), int(min(n, pos + T))
            if not marks or not voiced[-1]:
                p = a + int(np.argmax(xl[a:b])) if b > a else a
            else:
                c = marks[-1] + T
                lo, hi = int(max(0, c - T / 4)), int(min(n, c + T / 4 + 1))
                p = lo + int(np.argmax(xl[lo:hi])) if hi > lo else int(c)
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
            if target is not None:
                # Pitch-correct onto the target note: the output cycle length is
                # set by the target, whatever the singer's pitch is doing.
                f_t = 440.0 * 2.0 ** ((float(np.interp(ts / sr, target[0], target[1])) - 69.0) / 12.0)
                step = sr / f_t
            else:
                r = 2.0 ** (float(np.interp(ts / sr, shift_t, shift_s)) / 12.0)
                step = T / r
            # Grain = two periods of whichever is longer, analysis or synthesis:
            # lowering pitch then still overlaps grains by half, so they sum
            # smoothly instead of leaving dips between cycles.
            L = int(max(T, step))
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
    # Only undo pile-up where grains overlap by more than one (raising pitch).
    # Lowering pitch leaves real gaps between glottal pulses; dividing by the
    # small window sum there would amplify grain edges into buzz and hiss.
    ok = wsum > 0.05
    y[ok] /= np.maximum(wsum[ok], 0.5)  # windows now sum to ~1; only tame pile-up and tiny edges
    y[~ok] = 0.0
    return y


def target_curve(melody: Sequence[dict], part: Sequence[dict], tuning_cents: float = 0.0):
    """Absolute pitch (MIDI, fractional) the harmony voice sings over time:
    each note held steady, a short glide (GLIDE_S) between notes, matched to
    the singer's overall tuning so the parts don't beat against the lead."""
    kt: list[float] = []
    kp: list[float] = []
    for m, h in zip(melody, part):
        p = float(h["pitch"]) + tuning_cents / 100.0
        t0, t1 = float(m["t0"]), float(m["t1"])
        g = min(GLIDE_S / 2, (t1 - t0) / 4)
        a, b = t0 + g, t1 - g
        if kt and a <= kt[-1]:
            a = kt[-1] + 1e-4
            b = max(b, a)
        kt += [a, b]
        kp += [p, p]
    return np.array(kt), np.array(kp)


def render_part(vocals: np.ndarray, sr: int, f0_times: np.ndarray, f0_hz: np.ndarray,
                melody: Sequence[dict], part: Sequence[dict], tuning_cents: float = 0.0,
                follow_slides: bool = False) -> np.ndarray:
    """The lead's own voice, singing `part`. Silent where the lead is silent.

    By default the harmony sings clean, steady notes: the singer's slides,
    scoops, runs and wobbles are corrected away (only the voice's character is
    kept). follow_slides=True instead shifts by a fixed interval per note, so
    the harmony copies every inflection of the lead.
    """
    t, s = shift_curve(melody, part)
    if len(t) == 0:
        return np.zeros_like(vocals)
    target = None if follow_slides else target_curve(melody, part, tuning_cents)
    return psola(vocals, sr, f0_times, f0_hz, t, s, target)
