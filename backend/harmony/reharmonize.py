"""Reharmonization and harmony-part generation.

No machine learning: every choice is a named, explainable music-theory move
the user can steer, lock, or reject. The tool proposes; the musician decides.

Public entry points:

    reharmonize(melody, chords, novelty=0.0, palette=None, locks=None, ...)
        -> list[Reharmonization]
        Viterbi over beats on 84 candidate chords (12 roots x 7 qualities).
        Returns the top 3 (diverse) paths so the UI can offer alternatives.
          novelty  how far from the detected chords to go (0..1)
          palette  which *kind* of move: LENSES (borrowed, secondary, tritone,
                   color, passing, suspense, density), each 0..1
          locks    beats the user has decided on; the search works around them
        Each result has .explain(): per changed segment, roman numeral plus
        reasons ("secondary dominant: V7/ii", "borrowed from C minor", ...).

    harmony_parts(melody, chords, voice_profile, style="parallel")
        -> {"third_above": [...], "sixth_below": [...]}
        Two backing lines. Each note is snapped to a chord tone of the chord
        sounding at that moment, so the interval bends to the harmony instead
        of being a fixed transposition. Styles: HARMONY_STYLES (parallel,
        voice_led, contrary, pad).

    harmony_variations(melody, chords, voice_profile) -> {style: parts}
        Every style side by side, for the singer to audition.

Conventions
    * Time is measured in beats (floats). One window = one beat by default
      (`beat_len`).
    * Pitches are MIDI numbers. A melody note is a dict
      {"pitch": int, "start": float, "duration": float} (also accepts "dur",
      "end", or a (pitch, start, duration) tuple). pitch=None is a rest.
    * Chords are symbols ("Am7", "G7", "Bbmaj7", "N.C."), Chord objects, or
      dicts {"root": 0-11, "quality": "min7"} / {"symbol": "Am7"}. Either one
      per beat, or timed: {"symbol": "C", "start": 0, "end": 4}.

Score of a path:
    d_t   = phase_distance(c_t, original_t)
    total = sum_t  emission(c_t)
                 - lambda_t * transition(c_{t-1}, c_t)
                 + novelty * W_NOVELTY * d_t                  # novelty bonus
                 - W_TARGET * (d_t - novelty * D_TARGET_MAX)^2 # shaping
                 + (1 - novelty) * W_EXACT * [c_t == original_t]
                 - W_OUT_OF_KEY * out_of_key_fraction(c_t)

Terms beyond the original sketch, and why:
  * The exact-match anchor: emission alone often prefers a chord that fits the
    melody slightly better than what was played, so novelty 0 would not
    reproduce the detected progression.
  * The quadratic shaping: a bonus linear in d_t makes the output flip from
    "original" to "maximally far" at one slider value. Pulling toward a target
    distance that grows with novelty makes the slider ramp.
  * Out-of-key penalty: phase distance alone happily wanders into other keys.
    Penalizing tones outside parallel major + minor keeps the far-out choices
    in borrowed-chord / modal-interchange territory.
  * The DFT-magnitude cosine is transposition-invariant (C and F# major have
    identical magnitudes), so it only scores chord *shape*; the direct
    chord-tone terms are what pick the root.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Chord vocabulary
# ---------------------------------------------------------------------------

QUALITIES: dict[str, tuple[int, ...]] = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10),
    "dim": (0, 3, 6),
    "sus4": (0, 5, 7),
}
QUALITY_ORDER = tuple(QUALITIES)

# Non-chord tones that still sound fine sustained over the chord (intervals
# above the root). Deliberately excludes the avoid notes (e.g. 4th over major).
TENSIONS: dict[str, tuple[int, ...]] = {
    "maj": (2, 9),
    "min": (2, 5),
    "7": (2, 9),
    "maj7": (2, 6, 9),
    "min7": (2, 5, 9),
    "dim": (2, 5),
    "sus4": (2, 9, 10),
}

SUFFIX = {"maj": "", "min": "m", "7": "7", "maj7": "maj7", "min7": "m7", "dim": "dim", "sus4": "sus4"}
NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass(frozen=True)
class Chord:
    root: int
    quality: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root % 12)
        if self.quality not in QUALITIES:
            raise ValueError(f"unknown chord quality {self.quality!r}")

    @property
    def intervals(self) -> tuple[int, ...]:
        return QUALITIES[self.quality]

    @property
    def tones(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in self.intervals)

    @property
    def tensions(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in TENSIONS[self.quality])

    @property
    def name(self) -> str:
        return NOTE_NAMES[self.root] + SUFFIX[self.quality]

    @property
    def index(self) -> int:
        return self.root * len(QUALITY_ORDER) + QUALITY_ORDER.index(self.quality)

    def __str__(self) -> str:
        return self.name


CANDIDATES: tuple[Chord, ...] = tuple(Chord(r, q) for r in range(12) for q in QUALITY_ORDER)
N_CAND = len(CANDIDATES)  # 84

_SYMBOL_RE = re.compile(r"^\s*([A-Ga-g])([#b♯♭]?)(.*?)\s*(?:/.*)?$")


def _parse_quality(rest: str) -> str:
    """Map a chord-symbol suffix onto the 7-quality vocabulary (nearest fit)."""
    s = rest.strip().replace("(", "").replace(")", "")
    low = s.lower()
    if low in ("", "maj", "major"):
        return "maj"
    # Order matters: "maj7" before "m", "m7b5" before "m7".
    if low.startswith(("maj7", "ma7", "maj9", "maj13")) or s.startswith(("M7", "M9", "Δ")):
        return "maj7"
    if low.startswith(("m7b5", "min7b5", "-7b5", "ø", "dim", "°", "o")):
        return "dim"
    if low.startswith("sus"):
        return "sus4"
    if s.startswith(("m7", "m9", "m11", "m13", "min7", "min9", "-7", "-9")):
        return "min7"
    if s.startswith(("m", "-")) and not low.startswith("maj"):
        return "min"
    if low.startswith(("7", "9", "11", "13", "dom")):
        return "7"
    return "maj"  # 6, add9, 5, aug, ... collapse to major


def parse_chord(value: Any) -> Chord | None:
    """Accepts Chord, symbol string, or dict. Returns None for no-chord."""
    if value is None or isinstance(value, Chord):
        return value
    if isinstance(value, dict):
        if "root" in value and "quality" in value:
            q = value["quality"]
            return Chord(int(value["root"]), q if q in QUALITIES else _parse_quality(str(q)))
        for key in ("symbol", "chord", "name", "label"):
            if key in value:
                return parse_chord(value[key])
        raise ValueError(f"cannot parse chord from {value!r}")
    if isinstance(value, str):
        if value.strip().upper() in ("N", "NC", "N.C.", "N.C", "-", ""):
            return None
        m = _SYMBOL_RE.match(value)
        if not m:
            raise ValueError(f"cannot parse chord symbol {value!r}")
        letter, acc, rest = m.groups()
        root = _LETTER_PC[letter.upper()] + (1 if acc in ("#", "♯") else -1 if acc in ("b", "♭") else 0)
        return Chord(root, _parse_quality(rest))
    raise TypeError(f"cannot parse chord from {type(value).__name__}")


# ---------------------------------------------------------------------------
# Melody normalization
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Note:
    pitch: int
    start: float
    dur: float

    @property
    def end(self) -> float:
        return self.start + self.dur


def _parse_notes(melody: Iterable[Any]) -> list[Note]:
    notes: list[Note] = []
    for n in melody:
        if isinstance(n, Note):
            notes.append(n)
            continue
        if isinstance(n, dict):
            pitch = n.get("pitch", n.get("midi"))
            start = float(n.get("start", n.get("time", 0.0)))
            if "duration" in n:
                dur = float(n["duration"])
            elif "dur" in n:
                dur = float(n["dur"])
            elif "end" in n:
                dur = float(n["end"]) - start
            else:
                raise ValueError(f"note has no duration: {n!r}")
        else:
            pitch, start, dur = n
            start, dur = float(start), float(dur)
        if pitch is None or dur <= 0:
            continue
        notes.append(Note(int(round(pitch)), start, dur))
    notes.sort(key=lambda x: (x.start, x.pitch))
    return notes


def _parse_timeline(chords: Sequence[Any], beat_len: float) -> list[tuple[float, float, Chord | None]]:
    """Normalize chords into [(start, end, chord)] in beats."""
    timeline = []
    for i, c in enumerate(chords):
        if isinstance(c, dict) and "start" in c:
            start = float(c["start"])
            if "end" in c:
                end = float(c["end"])
            else:
                end = start + float(c.get("duration", c.get("dur", beat_len)))
            timeline.append((start, end, parse_chord(c)))
        else:
            timeline.append((i * beat_len, (i + 1) * beat_len, parse_chord(c)))
    timeline.sort(key=lambda x: x[0])
    return timeline


def _chord_at(timeline: Sequence[tuple[float, float, Chord | None]], t: float) -> Chord | None:
    best = None
    for start, end, chord in timeline:
        if start - 1e-9 <= t < end - 1e-9:
            best = chord
        elif start > t:
            break
    return best


# ---------------------------------------------------------------------------
# Pitch-class Fourier space
# ---------------------------------------------------------------------------

_KS = slice(1, 7)  # DFT coefficients 1..6; coefficient 0 is just total mass


def _chord_mask(chord: Chord) -> np.ndarray:
    v = np.zeros(12)
    v[list(chord.tones)] = 1.0
    return v


MASKS = np.stack([_chord_mask(c) for c in CANDIDATES])  # (84, 12)
TENSION_MASKS = np.stack(
    [np.isin(np.arange(12), list(c.tensions)).astype(float) for c in CANDIDATES]
)  # (84, 12)
_FFT = np.fft.fft(MASKS, axis=1)[:, _KS]  # (84, 6) complex
MAGS = np.abs(_FFT)
PHASES = np.angle(_FFT)


def _phase_distance_matrix() -> np.ndarray:
    """Angular distance between Fourier phase vectors, in [0, 1].

    Each coefficient's phase difference is weighted by the product of the two
    magnitudes: a coefficient that is ~0 for either chord has no meaningful
    phase and should not count.
    """
    dphi = np.abs(PHASES[:, None, :] - PHASES[None, :, :])
    dphi = np.minimum(dphi, 2 * np.pi - dphi) / np.pi  # (84, 84, 6) in [0,1]
    w = MAGS[:, None, :] * MAGS[None, :, :]
    tot = w.sum(axis=2)
    return np.where(tot > 1e-9, (w * dphi).sum(axis=2) / np.maximum(tot, 1e-9), 0.5)


PHASE_DIST = _phase_distance_matrix()  # (84, 84)


def phase_distance(a: Chord, b: Chord) -> float:
    return float(PHASE_DIST[a.index, b.index])


# ---------------------------------------------------------------------------
# Transition: voice leading + function
# ---------------------------------------------------------------------------


def _pc_dist(x: int, y: int) -> int:
    d = abs(x - y) % 12
    return min(d, 12 - d)


@lru_cache(maxsize=None)
def _vl_shape(qa: str, qb: str, shift: int) -> int:
    a = QUALITIES[qa]
    b = tuple((i + shift) % 12 for i in QUALITIES[qb])
    big, small = (a, b) if len(a) >= len(b) else (b, a)
    best = 10**9
    # Every voice of the larger chord moves to some voice of the smaller one,
    # and every voice of the smaller one is used (doubling allowed).
    for assign in itertools.product(range(len(small)), repeat=len(big)):
        if len(set(assign)) != len(small):
            continue
        cost = sum(_pc_dist(big[i], small[j]) for i, j in enumerate(assign))
        best = min(best, cost)
    return best


def voice_leading_distance(a: Chord, b: Chord) -> int:
    """Minimal total semitone motion between the two chords' voices."""
    return _vl_shape(a.quality, b.quality, (b.root - a.root) % 12)


VL = np.array([[voice_leading_distance(a, b) for b in CANDIDATES] for a in CANDIDATES], dtype=float)

# Root-motion cost by interval (b.root - a.root) mod 12, used everywhere.
ROOT_MOTION = {0: 0.0, 5: -0.15, 7: 0.0, 2: 0.1, 10: 0.05, 3: 0.1, 9: 0.1, 4: 0.15, 8: 0.1, 1: 0.35, 11: 0.3, 6: 0.8}

# Idiomatic progressions by scale degree (root semitones above the tonic).
# Negative = cheap. Works for major and minor keys since degrees are absolute.
FUNCTIONAL = {
    (7, 0): -0.6,   # V    -> I
    (0, 7): -0.3,   # I    -> V
    (5, 7): -0.4,   # IV   -> V
    (2, 7): -0.5,   # ii   -> V
    (5, 0): -0.3,   # IV   -> I   (plagal; also iv -> i)
    (0, 5): -0.3,   # I    -> IV
    (9, 2): -0.4,   # vi   -> ii
    (9, 5): -0.3,   # vi   -> IV
    (0, 9): -0.2,   # I    -> vi
    (4, 9): -0.3,   # iii  -> vi
    (7, 9): -0.2,   # V    -> vi  (deceptive)
    (11, 0): -0.4,  # vii° -> I
    (2, 5): -0.1,   # ii   -> IV
    (10, 0): -0.3,  # bVII -> I   (mixolydian / borrowed)
    (5, 10): -0.2,  # IV   -> bVII
    (8, 10): -0.3,  # bVI  -> bVII
    (8, 7): -0.3,   # bVI  -> V
    (0, 8): -0.1,   # I    -> bVI
    (3, 8): -0.2,   # bIII -> bVI
    (10, 3): -0.2,  # bVII -> bIII
    (1, 0): -0.3,   # bII  -> I   (tritone sub)
    (0, 3): -0.1,   # I    -> bIII
}


def functional_cost(a: Chord, b: Chord, tonic: int) -> float:
    cost = ROOT_MOTION[(b.root - a.root) % 12]
    cost += FUNCTIONAL.get(((a.root - tonic) % 12, (b.root - tonic) % 12), 0.0)
    if a.quality == "7" and (b.root - a.root) % 12 == 5:
        cost -= 0.2  # dominant seventh resolving down a fifth
    if a.quality == "dim" and (b.root - a.root) % 12 == 1:
        cost -= 0.2  # leading-tone diminished resolving up
    return cost


VL_SCALE = 4.0  # semitones of total motion that cost as much as 1.0 of emission
CHANGE_COST = 0.5  # flat cost of changing chord at all; keeps harmonic rhythm from going beat-by-beat


def transition_matrix(tonic: int, change_cost: float = CHANGE_COST) -> np.ndarray:
    func = np.array([[functional_cost(a, b, tonic) for b in CANDIDATES] for a in CANDIDATES])
    change = change_cost * (1.0 - np.eye(N_CAND))
    return VL / VL_SCALE + func + change


# ---------------------------------------------------------------------------
# Key estimation (only used to orient the functional table)
# ---------------------------------------------------------------------------

_KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(profile: np.ndarray) -> tuple[int, str]:
    if profile.sum() <= 0:
        return 0, "major"
    best = (-2.0, 0, "major")
    for mode, prof in (("major", _KK_MAJOR), ("minor", _KK_MINOR)):
        for tonic in range(12):
            r = np.corrcoef(profile, np.roll(prof, tonic))[0, 1]
            if np.isfinite(r) and r > best[0]:
                best = (r, tonic, mode)
    return best[1], best[2]


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

W_MAG = 0.5        # DFT-magnitude cosine (shape of the chord; transposition-invariant)
W_DIRECT = 1.5     # share of window duration on chord tones / tensions
W_TOP = 1.0        # heaviest pitch classes are chord tones
W_SEMI = 2.5       # longest note a semitone above a chord tone, unresolved
TENSION_CREDIT = 0.4
OTHER_PENALTY = 0.8


def _windows(notes: Sequence[Note], n_beats: int, beat_len: float):
    W = np.zeros((n_beats, 12))
    longest: list[tuple[float, int] | None] = [None] * n_beats
    for i, n in enumerate(notes):
        t0 = max(int(math.floor(n.start / beat_len)), 0)
        t1 = min(int(math.ceil(n.end / beat_len - 1e-9)), n_beats)
        for t in range(t0, t1):
            ov = min(n.end, (t + 1) * beat_len) - max(n.start, t * beat_len)
            if ov <= 1e-9:
                continue
            W[t, n.pitch % 12] += ov
            if longest[t] is None or ov > longest[t][0] + 1e-9:
                longest[t] = (ov, i)
    return W, longest


def _emission_matrix(notes: Sequence[Note], n_beats: int, beat_len: float) -> np.ndarray:
    W, longest = _windows(notes, n_beats, beat_len)
    E = np.zeros((n_beats, N_CAND))
    mag_norm = np.linalg.norm(MAGS, axis=1)
    other = 1.0 - MASKS - TENSION_MASKS  # (84, 12) 1 where neither tone nor tension
    for t in range(n_beats):
        w = W[t]
        total = w.sum()
        if total <= 1e-9:
            continue  # rest: let transitions and the anchor decide
        p = w / total

        # 1. Fourier magnitude cosine.
        wm = np.abs(np.fft.fft(p))[_KS]
        denom = mag_norm * np.linalg.norm(wm)
        cos = np.where(denom > 1e-9, MAGS @ wm / np.maximum(denom, 1e-9), 0.0)

        # 2. Direct chord-tone coverage.
        direct = MASKS @ p + TENSION_CREDIT * (TENSION_MASKS @ p) - OTHER_PENALTY * (other @ p)

        # 3. Heaviest pitch classes.
        order = [pc for pc in np.argsort(-w) if w[pc] > 1e-9][:2]
        top = np.zeros(N_CAND)
        for weight, pc in zip((0.65, 0.35), order):
            top += weight * (MASKS[:, pc] + 0.3 * TENSION_MASKS[:, pc] - 0.5 * other[:, pc])

        # 4. The audible error: sustained note a semitone above a chord tone.
        semi = np.zeros(N_CAND)
        if longest[t] is not None and longest[t][0] >= 0.25 * beat_len:
            n = notes[longest[t][1]]
            pc = n.pitch % 12
            flagged = (MASKS[:, pc] == 0) & (MASKS[:, (pc - 1) % 12] == 1)
            nxt = _next_note(notes, longest[t][1])
            if nxt is not None and (n.pitch - nxt.pitch) in (1, 2):
                flagged &= MASKS[:, nxt.pitch % 12] == 0  # resolves down to a chord tone: fine
            semi = flagged.astype(float) * min(1.0, 2.0 * longest[t][0] / beat_len)

        E[t] = W_MAG * cos + W_DIRECT * direct + W_TOP * top - W_SEMI * semi
    return E


def _next_note(notes: Sequence[Note], i: int) -> Note | None:
    n = notes[i]
    for m in notes[i + 1:]:
        if m.start >= n.end - 1e-6:
            return m if m.start - n.end <= 1.0 else None
    return None



# ---------------------------------------------------------------------------
# Key, scales, roman numerals
# ---------------------------------------------------------------------------

_MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
_MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
_ROMAN = {0: "I", 1: "bII", 2: "II", 3: "bIII", 4: "III", 5: "IV", 6: "#IV", 7: "V", 8: "bVI", 9: "VI", 10: "bVII", 11: "VII"}
_ROMAN_SUFFIX = {"maj": "", "min": "", "7": "7", "maj7": "maj7", "min7": "7", "dim": "°", "sus4": "sus4"}


def _scales(tonic: int, mode: str) -> tuple[frozenset[int], frozenset[int]]:
    """(home scale, parallel scale). Minor includes the harmonic-minor leading tone."""
    major = frozenset((tonic + i) % 12 for i in _MAJOR_SCALE)
    minor = frozenset((tonic + i) % 12 for i in _MINOR_SCALE) | {(tonic + 11) % 12}
    return (major, minor) if mode == "major" else (minor, major)


def roman(chord: Chord | None, tonic: int, *, suffix: bool = True) -> str:
    if chord is None:
        return "N.C."
    numeral = _ROMAN[(chord.root - tonic) % 12]
    if chord.quality in ("min", "min7", "dim"):
        numeral = numeral.lower()
    return numeral + (_ROMAN_SUFFIX[chord.quality] if suffix else "")


def out_of_key_fraction(tonic: int) -> np.ndarray:
    """Fraction of each candidate's tones outside parallel major + minor (+ leading tone).

    This pool is exactly the material for borrowed chords / modal interchange
    (bIII, iv, bVI, bVII, V7 ...), so far-in-phase wandering stays in it
    rather than sliding off into a different key.
    """
    pool = {(tonic + i) % 12 for i in (0, 2, 3, 4, 5, 7, 8, 9, 10, 11)}
    outside = np.array([[0.0 if pc in pool else 1.0 for pc in range(12)]])
    return (MASKS * outside).sum(axis=1) / MASKS.sum(axis=1)


# ---------------------------------------------------------------------------
# Lenses: named, independent creative knobs (each 0..1)
# ---------------------------------------------------------------------------
#
# The novelty slider says "how far". Lenses say "in which direction". Each one
# is a small, explainable bonus on a family of moves a musician would name,
# so the user steers the search instead of accepting a black-box answer.

LENSES = {
    "borrowed": "chords from the parallel major/minor (iv, bVI, bVII, bIII ...)",
    "secondary": "secondary dominants: a 7th chord a fifth above the next chord (V7/x)",
    "tritone": "tritone substitutions: a 7th chord a semitone above the next chord",
    "color": "7th-chord colour: maj7, m7, 7 instead of plain triads",
    "passing": "passing diminished chords that resolve up a semitone",
    "suspense": "sus4 chords that resolve to the same root",
    "density": "harmonic rhythm: 0 = few changes, 0.5 = neutral, 1 = changes on most beats",
}
W_LENS = 1.0
LENS_NOVELTY_FLOOR = 0.4  # a lens at 1.0 implies at least this much novelty
TRITONE_SUB_BONUS = 2.0   # per beat, for bII7 replacing a detected V7


def _lens_emission(palette: dict[str, float], tonic: int, mode: str) -> np.ndarray:
    home, parallel = _scales(tonic, mode)
    bonus = np.zeros(N_CAND)
    for i, c in enumerate(CANDIDATES):
        if c.tones <= parallel and not c.tones <= home:
            bonus[i] += W_LENS * palette.get("borrowed", 0.0)
        if c.quality in ("7", "maj7", "min7"):
            # Diatonic sevenths (Imaj7, ii7, V7 ...) get the full colour bonus;
            # chromatic ones (I7 in major) half, so colour doesn't turn into blues.
            fit = 1.0 if c.tones <= home else 0.5
            bonus[i] += 0.6 * fit * W_LENS * palette.get("color", 0.0)
    return bonus


def _lens_transition(palette: dict[str, float], tonic: int) -> np.ndarray:
    """Bonus (not cost) for moving from a to b. Added unscaled by lambda."""
    B = np.zeros((N_CAND, N_CAND))
    sec, tri, pas, sus = (palette.get(k, 0.0) for k in ("secondary", "tritone", "passing", "suspense"))
    if not (sec or tri or pas or sus):
        return B
    for i, a in enumerate(CANDIDATES):
        for j, b in enumerate(CANDIDATES):
            motion = (b.root - a.root) % 12
            if a.quality == "7" and motion == 5 and b.root != tonic and b.quality != "dim":
                B[i, j] += 1.2 * W_LENS * sec        # V7/x -> x  (V7 -> I is already cheap)
            if a.quality == "7" and motion == 11 and b.quality not in ("dim", "7"):
                B[i, j] += 0.8 * W_LENS * tri        # bII7 -> I, the tritone sub
            if a.quality == "dim" and motion == 1:
                B[i, j] += 2.0 * W_LENS * pas
            if a.quality == "sus4" and motion == 0 and b.quality in ("maj", "7", "min"):
                B[i, j] += 1.2 * W_LENS * sus
    return B


def _density_change_cost(density: float | None) -> float:
    if density is None:
        return CHANGE_COST
    return CHANGE_COST * 4.0 ** (1.0 - 2.0 * float(np.clip(density, 0, 1)))  # 4x .. 0.25x


# ---------------------------------------------------------------------------
# Viterbi
# ---------------------------------------------------------------------------

W_NOVELTY = 1.0     # linear bonus for phase distance from the original chord
W_TARGET = 8.0      # quadratic pull toward distance = novelty * D_TARGET_MAX
D_TARGET_MAX = 0.5  # typical borrowed-chord distance (C->Fm 0.46, C->Ab 0.38, C->Eb 0.46)
W_EXACT = 1.2       # pull toward the exact detected chord, fades out with novelty
W_OUT_OF_KEY = 2.0  # per-fraction of chord tones outside the modal-interchange pool
LAMBDA = 0.6        # base transition weight
LAMBDA_AT_CHANGE = 0.6   # multiplier where the original changes chord
LAMBDA_DOWNBEAT = 0.8    # multiplier on downbeats
_LOCKED_OUT = -1e9


@dataclass
class Reharmonization:
    chords: list[Chord | None]  # one per beat
    score: float
    beat_len: float = 1.0
    changed_beats: list[int] = field(default_factory=list)
    original: list[Chord | None] = field(default_factory=list)
    key: tuple[int, str] = (0, "major")

    @property
    def symbols(self) -> list[str]:
        return [c.name if c else "N.C." for c in self.chords]

    @property
    def romans(self) -> list[str]:
        return [roman(c, self.key[0]) for c in self.chords]

    def timeline(self) -> list[dict]:
        """Consecutive identical beats merged into timed chords."""
        out: list[dict] = []
        for t, c in enumerate(self.chords):
            sym = c.name if c else "N.C."
            if out and out[-1]["symbol"] == sym:
                out[-1]["end"] = (t + 1) * self.beat_len
            else:
                out.append({
                    "symbol": sym, "roman": roman(c, self.key[0]),
                    "start": t * self.beat_len, "end": (t + 1) * self.beat_len,
                })
        return out

    def explain(self) -> list[dict]:
        """Why each changed segment was chosen, in musician's terms."""
        return explain_progression(self.chords, self.original, self.key, self.beat_len)

    def to_dict(self) -> dict:
        return {
            "chords": self.symbols,
            "romans": self.romans,
            "timeline": self.timeline(),
            "score": round(self.score, 4),
            "changed_beats": self.changed_beats,
            "explanations": self.explain(),
            "key": {"tonic": NOTE_NAMES[self.key[0]], "mode": self.key[1]},
        }


def explain_progression(
    chords: Sequence[Chord | None],
    original: Sequence[Chord | None],
    key: tuple[int, str],
    beat_len: float = 1.0,
) -> list[dict]:
    tonic, mode = key
    home, parallel = _scales(tonic, mode)
    other_mode = "minor" if mode == "major" else "major"

    # Segments of consecutive identical chords.
    segs: list[tuple[int, int, Chord | None]] = []
    for t, c in enumerate(chords):
        if segs and segs[-1][2] == c:
            segs[-1] = (segs[-1][0], t + 1, c)
        else:
            segs.append((t, t + 1, c))

    out = []
    for si, (t0, t1, c) in enumerate(segs):
        was = [o for o in original[t0:t1] if o is not None]
        if c is None or not was or all(o == c for o in was):
            continue
        orig = max(set(was), key=was.count)
        nxt = segs[si + 1][2] if si + 1 < len(segs) else None
        tags: list[str] = []
        motion = (nxt.root - c.root) % 12 if nxt else None

        if c.quality == "7" and motion == 5 and nxt is not None:
            if nxt.root == tonic:
                tags.append("dominant: pulls home to the tonic")
            else:
                tags.append(f"secondary dominant: V7/{roman(nxt, tonic, suffix=False)}, tonicizes {nxt.name} for a moment")
        if c.quality == "7" and motion == 11 and nxt is not None and nxt.quality not in ("dim", "7"):
            tags.append(f"tritone substitution: stands in for {NOTE_NAMES[(nxt.root + 7) % 12]}7, bass slides down a semitone")
        if c.quality == "dim" and motion == 1 and nxt is not None:
            tags.append(f"passing diminished: leans up a semitone into {nxt.name}")
        if c.quality == "sus4":
            tags.append("suspension: the 4th holds tension" + (" and resolves" if nxt and nxt.root == c.root else ""))
        if c.tones <= parallel and not c.tones <= home:
            tags.append(f"borrowed from {NOTE_NAMES[tonic]} {other_mode} (modal interchange)")
        elif not c.tones <= home | parallel and not tags:
            tags.append("chromatic colour outside the key")
        if c.root == orig.root and c.quality != orig.quality:
            if c.quality in ("7", "maj7", "min7") and orig.quality in ("maj", "min"):
                tags.append(f"colour: {orig.name} with an added 7th")
            elif {c.quality, orig.quality} == {"maj", "min"}:
                tags.append(f"mode flip: {orig.name} becomes {c.name}")
        shared = len(c.tones & orig.tones)
        if shared >= 2 and c.root != orig.root:
            tags.append(f"substitute: shares {shared} notes with {orig.name}, same job, new colour")
        if not tags:
            tags.append(f"re-voices the melody against {roman(c, tonic)}")

        out.append({
            "start": t0 * beat_len, "end": t1 * beat_len,
            "from": orig.name, "to": c.name,
            "roman": roman(c, tonic), "tags": tags,
        })
    return out


def _k_best_viterbi(
    E: np.ndarray, Tr: np.ndarray, lam: np.ndarray, k: int, bonus: np.ndarray | None = None
) -> list[tuple[float, list[int]]]:
    T, S = E.shape
    step = (lambda t: -lam[t] * Tr) if bonus is None else (lambda t: -lam[t] * Tr + bonus)
    score = np.full((T, S, k), -np.inf)
    bp_state = np.zeros((T, S, k), dtype=np.int32)
    bp_rank = np.zeros((T, S, k), dtype=np.int32)
    score[0, :, 0] = E[0]
    for t in range(1, T):
        # cand[p, s, j] = score of j-th best path ending in p, then moving to s
        cand = score[t - 1][:, None, :] + step(t)[:, :, None]  # (S, S, k)
        flat = cand.transpose(1, 0, 2).reshape(S, S * k)  # per destination s
        top = np.argpartition(-flat, k - 1, axis=1)[:, :k]
        vals = np.take_along_axis(flat, top, axis=1)
        order = np.argsort(-vals, axis=1)
        top = np.take_along_axis(top, order, axis=1)
        vals = np.take_along_axis(vals, order, axis=1)
        score[t] = vals + E[t][:, None]
        bp_state[t] = top // k
        bp_rank[t] = top % k

    final = score[T - 1].reshape(-1)
    idx = np.argsort(-final)[:k]
    paths = []
    for flat_i in idx:
        if not np.isfinite(final[flat_i]) or final[flat_i] < _LOCKED_OUT / 2:
            continue
        s, j = divmod(int(flat_i), k)
        path = [s]
        for t in range(T - 1, 0, -1):
            s, j = int(bp_state[t, s, j]), int(bp_rank[t, s, j])
            path.append(s)
        paths.append((float(final[flat_i]), path[::-1]))
    return paths


def _pick_diverse(paths: list[tuple[float, list[int]]], n: int, min_diff: int) -> list[tuple[float, list[int]]]:
    """Top-n paths that differ from each other in at least `min_diff` beats.

    Raw k-best Viterbi alternatives usually differ by one chord on one beat,
    which is useless as a UI choice.
    """
    chosen: list[tuple[float, list[int]]] = []
    for need in (min_diff, 1):
        for sc, p in paths:
            if len(chosen) >= n:
                return chosen
            if any(p == q for _, q in chosen):
                continue
            if all(sum(a != b for a, b in zip(p, q)) >= need for _, q in chosen):
                chosen.append((sc, p))
    return chosen


def reharmonize(
    melody: Iterable[Any],
    chords: Sequence[Any],
    novelty: float = 0.0,
    *,
    palette: dict[str, float] | None = None,
    locks: dict[int, Any] | Iterable[int] | None = None,
    beat_len: float = 1.0,
    beats_per_bar: int = 4,
    key: tuple[int, str] | int | None = None,
    lam: float = LAMBDA,
    n_paths: int = 3,
) -> list[Reharmonization]:
    """Reharmonize `melody` starting from the detected `chords`.

    novelty: 0 keeps (close to) the detected progression; 1 pays the decoder to
        move far away in Fourier phase space, toward borrowed chords and modal
        interchange, while emission keeps melody notes as chord tones or
        acceptable tensions.
    palette: lens weights 0..1, see LENSES. Steers *which kind* of move. A
        lens above 0 also lifts novelty to at least LENS_NOVELTY_FLOOR * lens.
    locks: beats the user has decided on. Either {beat: chord} or a list of
        beats to keep as detected. The search works around them.

    Returns up to `n_paths` alternatives, best first, each with explanations.
    """
    novelty = float(np.clip(novelty, 0.0, 1.0))
    palette = {k: float(np.clip(v, 0.0, 1.0)) for k, v in (palette or {}).items()}
    unknown = set(palette) - set(LENSES)
    if unknown:
        raise ValueError(f"unknown lenses {sorted(unknown)}; choose from {sorted(LENSES)}")
    # Turning a lens up is a request for change: give it room even if the
    # novelty slider is at 0, otherwise the anchor silently wins.
    lens_drive = max([v for k, v in palette.items() if k != "density"] + [0.0])
    novelty = max(novelty, LENS_NOVELTY_FLOOR * lens_drive)

    notes = _parse_notes(melody)
    timeline = _parse_timeline(chords, beat_len)
    end = max([e for _, e, _ in timeline] + [n.end for n in notes] + [beat_len])
    n_beats = max(1, int(math.ceil(end / beat_len - 1e-9)))
    original = [_chord_at(timeline, (t + 0.5) * beat_len) for t in range(n_beats)]

    # Key: from melody durations plus the detected chords' tones.
    if key is None:
        prof = np.zeros(12)
        for n in notes:
            prof[n.pitch % 12] += n.dur
        for c in original:
            if c is not None:
                prof += 0.5 * MASKS[c.index]
        tonic, mode = estimate_key(prof)
    elif isinstance(key, tuple):
        tonic, mode = int(key[0]) % 12, key[1]
    else:
        tonic, mode = int(key) % 12, "major"

    E = _emission_matrix(notes, n_beats, beat_len)
    E -= W_OUT_OF_KEY * out_of_key_fraction(tonic)[None, :]
    E += _lens_emission(palette, tonic, mode)[None, :]

    # Novelty: reward phase distance from the original chord at each beat.
    # The reward peaks at a target distance that grows with the slider, so
    # the output moves away gradually instead of flipping all at once.
    target = novelty * D_TARGET_MAX
    for t, c in enumerate(original):
        if c is None:
            continue
        d = PHASE_DIST[:, c.index]
        E[t] += novelty * W_NOVELTY * d                      # the slider's bonus
        E[t] -= W_TARGET * (d - target) ** 2                 # ...shaped around a target distance
        E[t, c.index] += (1.0 - novelty) * W_EXACT          # novelty 0 => the detected chord wins

    # Tritone lens, substitution half: offer bII7 wherever a dominant 7th was
    # detected. (The resolution half lives in _lens_transition.) Needed because
    # the tritone sub is far in phase space and the novelty shaping resists it.
    tri = palette.get("tritone", 0.0)
    if tri:
        for t, c in enumerate(original):
            if c is not None and c.quality == "7":
                E[t, Chord(c.root + 6, "7").index] += TRITONE_SUB_BONUS * tri

    # Locks: the human's decisions are hard constraints.
    if locks is not None:
        items = locks.items() if isinstance(locks, dict) else ((t, None) for t in locks)
        for t, ch in items:
            t = int(t)
            if not 0 <= t < n_beats:
                continue
            ch = parse_chord(ch) if ch is not None else original[t]
            if ch is None:
                continue
            keep = E[t, ch.index]
            E[t, :] = _LOCKED_OUT
            E[t, ch.index] = keep

    lam_t = np.full(n_beats, lam)
    for t in range(1, n_beats):
        if original[t] != original[t - 1]:
            lam_t[t] *= LAMBDA_AT_CHANGE
        if t % beats_per_bar == 0:
            lam_t[t] *= LAMBDA_DOWNBEAT

    Tr = transition_matrix(tonic, _density_change_cost(palette.get("density")))
    B = _lens_transition(palette, tonic)
    raw = _k_best_viterbi(E, Tr, lam_t, k=max(8 * n_paths, 24), bonus=B if B.any() else None)
    picked = _pick_diverse(raw, n_paths, min_diff=max(1, round(0.1 * n_beats)))

    results = []
    for sc, path in picked:
        chs = [CANDIDATES[i] for i in path]
        changed = [t for t, (a, b) in enumerate(zip(chs, original)) if b is not None and a != b]
        results.append(Reharmonization(chs, sc, beat_len, changed, original, (tonic, mode)))
    return results


# ---------------------------------------------------------------------------
# Harmony parts
# ---------------------------------------------------------------------------

_NOTE_RE = re.compile(r"^\s*([A-Ga-g])([#b]?)(-?\d+)\s*$")


def _midi(v: Any) -> int:
    if isinstance(v, str):
        m = _NOTE_RE.match(v)
        if not m:
            raise ValueError(f"cannot parse note name {v!r}")
        letter, acc, octave = m.groups()
        return 12 * (int(octave) + 1) + _LETTER_PC[letter.upper()] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return int(round(v))


def _parse_voice_profile(vp: dict) -> tuple[int, int, int, int]:
    def get(*names):
        for n in names:
            if n in vp and vp[n] is not None:
                return _midi(vp[n])
        return None

    low = get("low", "lowest", "min", "rangeLow", "range_low")
    high = get("high", "highest", "max", "rangeHigh", "range_high")
    if low is None or high is None:
        raise ValueError("voice profile needs 'low' and 'high'")
    if low > high:
        low, high = high, low
    strong_low = get("strongLow", "strong_low")
    strong_high = get("strongHigh", "strong_high")
    strong_low = low if strong_low is None else min(max(strong_low, low), high)
    strong_high = high if strong_high is None else max(min(strong_high, high), strong_low)
    return low, high, strong_low, strong_high


def _snap(melody_pitch: int, tones: frozenset[int], above: bool, target: float, prev: int | None) -> int:
    """Chord-tone pitch on the requested side whose interval is closest to `target`."""
    best, best_cost = None, math.inf
    for p in range(melody_pitch - 24, melody_pitch + 25):
        if p % 12 not in tones or p == melody_pitch:
            continue
        iv = p - melody_pitch if above else melody_pitch - p
        if iv <= 0:
            continue
        cost = abs(iv - target)
        if prev is not None:
            cost += 0.05 * abs(p - prev)  # mild preference for smooth lines
        if cost < best_cost:
            best, best_cost = p, cost
    assert best is not None
    return best


def _fit_range(p: int, melody_pitch: int, tones: frozenset[int], rng: tuple[int, int, int, int]) -> int:
    low, high, strong_low, strong_high = rng
    if p > strong_high and p - 12 >= low:
        p -= 12  # invert down an octave
    elif p < strong_low and p + 12 <= strong_high:
        p += 12
    while p > high:
        p -= 12
    while p < low:
        p += 12
    if low <= p <= high and p != melody_pitch:
        return p
    # Range narrower than an octave around this pitch class (or landed on the
    # melody): take the closest in-range chord tone, then any in-range pitch.
    for pool in (tones, frozenset(range(12))):
        opts = [q for q in range(low, high + 1) if q % 12 in pool and q != melody_pitch]
        if opts:
            return min(opts, key=lambda q: (abs(q - p), q))
    return min(max(p, low), high)


# Styles beyond "parallel" are decoded as a whole line (Viterbi over in-range
# chord-tone pitches), so each part is a singable melody of its own rather
# than a note-by-note transposition.
HARMONY_STYLES = {
    "parallel": "a third above and a sixth below, bent to each chord (classic close harmony)",
    "voice_led": "inner voices: hold common tones, move by step, like real backing singers",
    "contrary": "parts move against the melody: it rises, they fall",
    "pad": "sustained chord tones that only move when the harmony forces them to",
}
_STYLE_WEIGHTS = {
    #             interval  motion  contrary
    "voice_led": (0.6,      0.35,   0.0),
    "contrary":  (0.25,     0.1,    1.5),
    "pad":       (0.25,     1.2,    0.0),
}
W_COMFORT = 1.5        # per semitone outside [strongLow, strongHigh]
W_WRONG_SIDE = 3.0     # upper part dipping below the melody (or lower part above it)
W_PARALLEL_PERFECT = 0.8  # parallel unisons/fifths/octaves with the melody


def _line_viterbi(
    notes: Sequence[Note], tones_per_note: Sequence[frozenset[int]], rng: tuple[int, int, int, int],
    above: bool, target: float, weights: tuple[float, float, float],
) -> list[int]:
    low, high, strong_low, strong_high = rng
    w_iv, w_motion, w_contrary = weights

    cands: list[list[int]] = []
    node: list[np.ndarray] = []
    for n, tones in zip(notes, tones_per_note):
        opts = [p for p in range(low, high + 1) if p % 12 in tones and p != n.pitch]
        if not opts:
            opts = [p for p in range(low, high + 1) if p != n.pitch] or [low]
        cost = []
        for p in opts:
            iv = p - n.pitch if above else n.pitch - p
            c = w_iv * abs(iv - target)
            c += W_COMFORT * (max(0, p - strong_high) + max(0, strong_low - p))
            c += W_WRONG_SIDE * (iv <= 0)
            cost.append(c)
        cands.append(opts)
        node.append(np.array(cost))

    acc = node[0].copy()
    back: list[np.ndarray] = []
    for i in range(1, len(notes)):
        prev_p = np.array(cands[i - 1])[:, None]
        cur_p = np.array(cands[i])[None, :]
        dp = cur_p - prev_p
        edge = w_motion * np.abs(dp)
        dm = notes[i].pitch - notes[i - 1].pitch
        if w_contrary and dm != 0:
            same = np.sign(dp) == np.sign(dm)
            edge = edge + w_contrary * same - 0.3 * w_contrary * (np.sign(dp) == -np.sign(dm))
        # Parallel perfect intervals against the melody sound hollow.
        iv_prev = np.abs(prev_p - notes[i - 1].pitch) % 12
        iv_cur = np.abs(cur_p - notes[i].pitch) % 12
        perfect = np.isin(iv_prev, (0, 7)) & np.isin(iv_cur, (0, 7)) & (dp != 0) & (dm != 0)
        edge = edge + W_PARALLEL_PERFECT * perfect
        total = acc[:, None] + edge
        back.append(np.argmin(total, axis=0))
        acc = total.min(axis=0) + node[i]

    j = int(np.argmin(acc))
    path = [j]
    for b in reversed(back):
        j = int(b[j])
        path.append(j)
    path.reverse()
    return [cands[i][j] for i, j in enumerate(path)]


def _merge_held(track: list[dict], chord_ids: list[Any]) -> list[dict]:
    """Join contiguous repeats of the same pitch under the same chord (pad style)."""
    out: list[dict] = []
    last_chord = None
    for note, cid in zip(track, chord_ids):
        if (out and out[-1]["pitch"] == note["pitch"] and cid == last_chord
                and abs(out[-1]["start"] + out[-1]["duration"] - note["start"]) < 1e-6):
            out[-1]["duration"] = note["start"] + note["duration"] - out[-1]["start"]
        else:
            out.append(dict(note))
        last_chord = cid
    return out


def harmony_parts(
    melody: Iterable[Any], chords: Sequence[Any], voice_profile: dict, *,
    style: str = "parallel", beat_len: float = 1.0,
) -> dict:
    """Two backing lines, a third above and a sixth below, bent to the harmony.

    Each part note is a chord tone of the chord sounding at the note's onset
    and never leaves [low, high]. In "parallel" style a note above
    `strongHigh` is inverted down an octave; the line styles treat
    strongLow/strongHigh as a comfort zone with a steep cost outside it.

    `chords`: a Reharmonization, a per-beat list, or a timed list.
    `voice_profile`: {"low", "high", "strongLow"?, "strongHigh"?} as MIDI
    numbers or note names ("A2").
    `style`: one of HARMONY_STYLES.
    """
    if style not in HARMONY_STYLES:
        raise ValueError(f"unknown style {style!r}; choose from {sorted(HARMONY_STYLES)}")
    if isinstance(chords, Reharmonization):
        beat_len = chords.beat_len
        chords = chords.chords
    notes = _parse_notes(melody)
    timeline = _parse_timeline(chords, beat_len)
    rng = _parse_voice_profile(voice_profile)

    # Fallback for N.C. sections: snap to the melody's estimated scale.
    prof = np.zeros(12)
    for n in notes:
        prof[n.pitch % 12] += n.dur
    tonic, mode = estimate_key(prof)
    scale = _scales(tonic, mode)[0]

    sounding = [_chord_at(timeline, n.start) for n in notes]
    tones = [c.tones if c is not None else scale for c in sounding]

    if style == "parallel":
        ups, lows = [], []
        prev_u = prev_l = None
        for n, ts in zip(notes, tones):
            prev_u = _fit_range(_snap(n.pitch, ts, True, 3.5, prev_u), n.pitch, ts, rng)
            prev_l = _fit_range(_snap(n.pitch, ts, False, 8.5, prev_l), n.pitch, ts, rng)
            ups.append(prev_u)
            lows.append(prev_l)
    else:
        w = _STYLE_WEIGHTS[style]
        ups = _line_viterbi(notes, tones, rng, True, 3.5, w) if notes else []
        lows = _line_viterbi(notes, tones, rng, False, 8.5, w) if notes else []

    def track(pitches):
        return [{"pitch": p, "start": n.start, "duration": n.dur} for p, n in zip(pitches, notes)]

    upper, lower = track(ups), track(lows)
    if style == "pad":
        ids = [c.name if c else None for c in sounding]
        upper, lower = _merge_held(upper, ids), _merge_held(lower, ids)
    return {"third_above": upper, "sixth_below": lower}


def harmony_variations(melody: Iterable[Any], chords: Sequence[Any], voice_profile: dict, **kw) -> dict:
    """Every harmony style side by side, so the singer picks (or mixes) by ear."""
    melody = list(melody)
    return {
        style: {"description": desc, **harmony_parts(melody, chords, voice_profile, style=style, **kw)}
        for style, desc in HARMONY_STYLES.items()
    }
