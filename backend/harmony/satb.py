"""Four-part (SATB) voicing of a sung melody, for a group of four singers.

    plan_satb(melody, chord_at, key, melody_voice="soprano") -> {soprano, alto, tenor, bass}

One voice carries the melody, moved into that voice's octave. The bass is
chosen first (chord roots, moving sensibly), then the two remaining voices are
chosen *together*, note by note over the whole line (Viterbi over pairs), with
the classic four-part rules as costs:

  hard    voices in S >= A >= T >= B order (no crossing), each in its range
  chord   root and third present, fifth preferably; don't double the third
          or the leading tone
  ear     no 2nds/tritones against the melody on held notes; open spacing
          no wider than an octave between upper voices
  line    small steps, no parallel 5ths/8ves, and keep moving when the melody
          moves (inner parts that park on one note sound detached from the tune)

Every voice has one note per melody note, on the lead's real timing, so all
four sing the same words at the same moment.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

from backend.harmony.reharmonize import Chord
from backend.harmony.tis import scale

VOICES = ("soprano", "alto", "tenor", "bass")
RANGES = {"soprano": (60, 81), "alto": (55, 74), "tenor": (48, 69), "bass": (40, 62)}
MELODY_CENTER = {"soprano": 69, "tenor": 58}

W_NOT_CHORD = 1.5       # a passing, in-key note that isn't in the chord (scaled by how long it's held)
W_MISSING = {"root": 3.0, "third": 3.0, "fifth": 0.5, "seventh": 0.3}
W_DOUBLE_THIRD = 1.5
W_DOUBLE_LEADING = 3.0
W_CLASH = 3.0           # 2nd/tritone against the melody (scaled by how long it's held)
W_RUB = 1.5             # 2nd between the two free voices
W_SPACING = 2.0         # more than an octave between adjacent upper voices
W_REGISTER = 0.03       # per semitone from the middle of the voice's range
W_MOTION = 0.18         # per semitone a free voice moves
W_LEAP = 1.5            # more than a 4th
W_PARALLEL = 4.0        # parallel 5th/8ve between any two voices
W_STATIC = 1.3          # a free voice holding while the melody moves
HELD_FULL_S = 0.25


def melody_octave_shift(melody: Sequence[dict], voice: str) -> int:
    med = float(np.median([n["pitch"] for n in melody]))
    return 12 * int(round((MELODY_CENTER[voice] - med) / 12.0))


def _chord_roles(ch: Chord) -> dict[int, str]:
    roles = {}
    iv = ch.intervals
    names = ["root", "third", "fifth", "seventh"]
    if ch.quality == "sus4":
        names = ["root", "fifth", "fifth"]      # the 4th stands in; nothing is a "third"
    for i, name in zip(iv, names):
        roles[(ch.root + i) % 12] = name
    return roles


def _plan_bass(melody, chords, upper_limit: Sequence[int]) -> list[int]:
    lo, hi = RANGES["bass"]
    n = len(melody)
    cands, node = [], []
    for i, (m, ch) in enumerate(zip(melody, chords)):
        roles = _chord_roles(ch)
        top = min(hi, upper_limit[i] - 1)
        opts = np.array([p for p in range(lo, max(lo, top) + 1) if p % 12 in roles] or [lo + (ch.root - lo) % 12], dtype=int)
        cost = []
        for p in opts:
            role = roles.get(int(p) % 12, "fifth")
            c = {"root": 0.0, "third": 1.5, "fifth": 1.0, "seventh": 2.5}[role]
            if i in (0, n - 1) and role != "root":
                c += 3.0
            cost.append(c + 0.04 * abs(p - 48))           # sit low, around C3
        cands.append(opts)
        node.append(np.array(cost))
    acc = node[0].copy()
    back = []
    for i in range(1, n):
        d = np.abs(cands[i][None, :] - cands[i - 1][:, None])
        tot = acc[:, None] + 0.1 * d + 1.0 * (d > 7)
        back.append(tot.argmin(axis=0))
        acc = tot.min(axis=0) + node[i]
    j = int(acc.argmin())
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    path.reverse()
    return [int(cands[i][j]) for i, j in enumerate(path)]


def plan_satb(melody: Sequence[dict], chord_at: Callable[[float], Chord | None], key: tuple[int, str],
              melody_voice: str = "soprano") -> dict[str, list[dict]]:
    if not melody:
        return {v: [] for v in VOICES}
    if melody_voice not in MELODY_CENTER:
        raise ValueError("the melody can be in the soprano or the tenor")
    tonic, mode = key
    sc = scale(tonic, mode)
    in_key = sc | ({(tonic + 11) % 12} if mode == "minor" else set())
    leading = (tonic + 11) % 12
    home = Chord(tonic, "maj" if mode == "major" else "min")
    shift = melody_octave_shift(melody, melody_voice)
    tune = [int(n["pitch"]) + shift for n in melody]
    chords = [chord_at(0.5 * (n["t0"] + n["t1"])) or home for n in melody]
    bass = _plan_bass(melody, chords, tune)

    mi = VOICES.index(melody_voice)
    free = [i for i in range(3) if i != mi]         # the two voices to choose (bass is index 3)
    states: list[np.ndarray] = []                   # per note: (S, 4) pitches of S A T B
    node: list[np.ndarray] = []
    for k, (n, ch) in enumerate(zip(melody, chords)):
        roles = _chord_roles(ch)
        m = tune[k]
        held = min(1.0, (n["t1"] - n["t0"]) / HELD_FULL_S)
        lists = []
        for v in free:
            lo, hi = RANGES[VOICES[v]]
            lists.append([p for p in range(lo, hi + 1) if p % 12 in roles or p % 12 in in_key])
        rows = []
        for x in lists[0]:
            for y in lists[1]:
                row = [0, 0, 0, bass[k]]
                row[mi], row[free[0]], row[free[1]] = m, x, y
                if row[0] >= row[1] >= row[2] >= row[3]:
                    rows.append(row)
        if not rows:   # very wide or very narrow spots: relax to the closest ordered voicing
            base = max(bass[k] + 1, m - 7)
            row = [0, 0, 0, bass[k]]
            row[mi], row[free[0]], row[free[1]] = m, max(m, base) if free[0] < mi else min(m, base), base
            rows = [sorted(row, reverse=True)]
        V = np.array(rows, dtype=int)
        cost = np.zeros(len(V))
        pcs = V % 12
        for i, row in enumerate(pcs):
            present = [roles.get(int(p)) for p in row]
            for role in set(roles.values()):
                if role not in present:
                    cost[i] += W_MISSING[role]
            if present.count("third") > 1:
                cost[i] += W_DOUBLE_THIRD
            if (row == leading).sum() > 1 and ch.root != leading:
                cost[i] += W_DOUBLE_LEADING
        for v in free:
            x = V[:, v]
            cost += W_NOT_CHORD * (0.4 + 0.6 * held) * ~np.isin(x % 12, list(roles))
            cost += W_CLASH * (0.4 + 0.6 * held) * np.isin(np.abs(x - m) % 12, (1, 2, 6, 10, 11))
            lo, hi = RANGES[VOICES[v]]
            cost += W_REGISTER * np.abs(x - (lo + hi) / 2)
            cost += 2.0 * (x == m)                                    # unison with the melody
        cost += W_RUB * held * np.isin(np.abs(V[:, free[0]] - V[:, free[1]]) % 12, (1, 2, 10, 11))
        cost += W_SPACING * ((V[:, 0] - V[:, 1] > 12).astype(float) + (V[:, 1] - V[:, 2] > 12))
        states.append(V)
        node.append(cost)

    pairs = [(a, b) for a in range(4) for b in range(a + 1, 4)]
    acc = node[0].copy()
    back = []
    for k in range(1, len(melody)):
        P, C = states[k - 1][:, None, :], states[k][None, :, :]
        d = C - P
        edge = np.zeros(d.shape[:2])
        moved_melody = tune[k] != tune[k - 1]
        joined = melody[k]["t0"] - melody[k - 1]["t1"] < 0.35
        scale_ = 1.0 if joined else 0.25
        for v in free:
            ad = np.abs(d[:, :, v])
            edge += scale_ * (W_MOTION * ad + W_LEAP * (ad > 5))
            if moved_melody:
                edge += scale_ * W_STATIC * (ad == 0)
        for a, b in pairs:
            same_way = (np.sign(d[:, :, a]) == np.sign(d[:, :, b])) & (d[:, :, a] != 0)
            before = np.abs(P[:, :, a] - P[:, :, b]) % 12
            after = np.abs(C[:, :, a] - C[:, :, b]) % 12
            edge += W_PARALLEL * (same_way & (before == after) & np.isin(after, (0, 7)))
        tot = acc[:, None] + edge
        back.append(tot.argmin(axis=0))
        acc = tot.min(axis=0) + node[k]
    j = int(acc.argmin())
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    path.reverse()

    out: dict[str, list[dict]] = {v: [] for v in VOICES}
    for k, (n, j) in enumerate(zip(melody, path)):
        for v, name in enumerate(VOICES):
            out[name].append({
                "pitch": int(states[k][j][v]), "melody_pitch": int(n["pitch"]),
                "t0": n["t0"], "t1": n["t1"], "start": n.get("start"), "duration": n.get("duration"),
                "lyric": n.get("lyric", ""), "word_start": n.get("word_start", False),
            })
    return out
