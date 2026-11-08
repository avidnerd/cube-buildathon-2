"""lily.py — a small LilyPond parser and writer for single-voice melodies.

This module is only the input/output layer. Music logic lives in counter.py and
works on the internal representation defined here: a list of `Note`
(midi or None for a rest, start in quarter-note beats, duration in beats),
plus a `KeySig`, a `Meter` and a tempo.
"""
from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field
from typing import Optional

EPS = 1e-6
STEP_NAMES = "cdefgab"
NATURAL = (0, 2, 4, 5, 7, 9, 11)          # semitone of each natural letter
MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)      # natural minor


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Note:
    """One note or rest. Times are in quarter-note beats."""
    midi: Optional[int]
    start: float
    dur: float

    @property
    def end(self) -> float:
        return self.start + self.dur


@dataclass(frozen=True)
class KeySig:
    """A major or minor key, stored by its spelled tonic (step 0-6 = c..b)."""
    step: int
    alter: int
    mode: str  # 'major' | 'minor'

    @property
    def tonic_pc(self) -> int:
        return (NATURAL[self.step] + self.alter) % 12

    @property
    def intervals(self) -> tuple[int, ...]:
        return MAJOR_STEPS if self.mode == "major" else MINOR_STEPS

    @property
    def scale_pcs(self) -> tuple[int, ...]:
        return tuple((self.tonic_pc + i) % 12 for i in self.intervals)

    def scale_spelling(self) -> list[tuple[int, int]]:
        """(step, alter) for the 7 scale degrees."""
        out = []
        for i, iv in enumerate(self.intervals):
            st = (self.step + i) % 7
            pc = (self.tonic_pc + iv) % 12
            out.append((st, (pc - NATURAL[st] + 6) % 12 - 6))
        return out

    @property
    def sharpness(self) -> int:
        """>0 for sharp keys, <0 for flat keys, 0 for C major / A minor."""
        return sum(a for _, a in self.scale_spelling())

    def lily(self) -> str:
        return f"{pitch_name(self.step, self.alter)} \\{self.mode}"

    def name(self) -> str:
        acc = {1: "#", 2: "##", -1: "b", -2: "bb"}.get(self.alter, "")
        return f"{STEP_NAMES[self.step].upper()}{acc} {self.mode}"

    def spell(self, midi: int) -> tuple[int, int, int]:
        """Spell a MIDI pitch in this key -> (step, alter, octave)."""
        st, alt = _spelling(self)[midi % 12]
        octave = (midi - alt - NATURAL[st]) // 12 - 1
        return st, alt, octave


@functools.lru_cache(maxsize=None)
def _spelling(key: KeySig) -> dict[int, tuple[int, int]]:
    """pc -> (step, alter). Diatonic notes use the key; chromatic notes prefer
    the spelling closest to natural, then sharps in sharp keys / flats in flat keys.
    In minor, the raised 6th and 7th are always spelled as raised degrees."""
    base = key.scale_spelling()
    table: dict[int, tuple[int, int]] = {}
    for st, alt in base:
        table[(NATURAL[st] + alt) % 12] = (st, alt)
    if key.mode == "minor":
        for d in (5, 6):
            st, alt = base[d]
            table.setdefault((NATURAL[st] + alt + 1) % 12, (st, alt + 1))
    sharp_key = key.sharpness >= 0
    by_pc = {(NATURAL[st] + alt) % 12: (st, alt) for st, alt in base}
    for pc in range(12):
        if pc in table:
            continue
        opts = []
        if (pc - 1) % 12 in by_pc:
            st, alt = by_pc[(pc - 1) % 12]
            opts.append((abs(alt + 1), 0 if sharp_key else 1, (st, alt + 1)))
        if (pc + 1) % 12 in by_pc:
            st, alt = by_pc[(pc + 1) % 12]
            opts.append((abs(alt - 1), 1 if sharp_key else 0, (st, alt - 1)))
        table[pc] = min(opts)[2]
    return table


@dataclass(frozen=True)
class Meter:
    """Time signature plus an optional pickup (anacrusis) length in beats.
    Time 0 is the first note; with a pickup, bar 0 is the partial bar."""
    num: int = 4
    den: int = 4
    pickup: float = 0.0

    @property
    def bar_len(self) -> float:
        return self.num * 4.0 / self.den

    @property
    def offset(self) -> float:
        return self.bar_len - self.pickup if self.pickup > EPS else 0.0

    @property
    def beat_len(self) -> float:
        return 1.5 if (self.den == 8 and self.num % 3 == 0) else 4.0 / self.den

    @property
    def mid_strong(self) -> Optional[float]:
        """Position of the secondary strong beat (e.g. beat 3 in 4/4), if any."""
        if self.num in (4, 6, 12) or (self.num == 2 and self.den == 2):
            return self.bar_len / 2
        return None

    def bar_index(self, t: float) -> int:
        return int(math.floor((t + self.offset + EPS) / self.bar_len))

    def bar_pos(self, t: float) -> float:
        s = t + self.offset
        pos = s - math.floor((s + EPS) / self.bar_len) * self.bar_len
        return 0.0 if abs(pos) < EPS else pos

    def bar_start(self, i: int) -> float:
        return max(0.0, i * self.bar_len - self.offset)

    def bar_end(self, i: int) -> float:
        return (i + 1) * self.bar_len - self.offset

    def is_strong(self, t: float) -> bool:
        pos = self.bar_pos(t)
        mid = self.mid_strong
        return pos < EPS or (mid is not None and abs(pos - mid) < EPS)

    def end_of_music(self, t: float) -> float:
        """Round a time up to the next barline."""
        if t <= EPS:
            return 0.0
        return self.bar_end(self.bar_index(t - 0.001))


@dataclass
class Score:
    """Parsed input: notes plus header information."""
    notes: list[Note]
    key: Optional[KeySig] = None
    meter: Meter = field(default_factory=Meter)
    tempo_bpm: int = 100
    tempo_unit: str = "4"
    warnings: list[str] = field(default_factory=list)

    @property
    def tempo_qpm(self) -> float:
        """Tempo in quarter notes per minute."""
        return self.tempo_bpm * _dur_beats(self.tempo_unit)


# ---------------------------------------------------------------------------
# Pitch / duration helpers
# ---------------------------------------------------------------------------

def pitch_name(step: int, alter: int) -> str:
    """LilyPond (Dutch) name for a spelled pitch, without octave marks."""
    letter = STEP_NAMES[step]
    if alter > 0:
        return letter + "is" * alter
    if alter < 0:
        if letter in "ea":
            return letter + "s" + "es" * (-alter - 1)
        return letter + "es" * (-alter)
    return letter


def octave_marks(octave: int) -> str:
    """Absolute-mode octave marks: c = C3, c' = C4, c, = C2."""
    n = octave - 3
    return "'" * n if n > 0 else "," * (-n)


def midi_to_lily(midi: int, key: KeySig) -> str:
    st, alt, octv = key.spell(midi)
    return pitch_name(st, alt) + octave_marks(octv)


_NOTE_NAME = re.compile(r"^([a-g])(isis|eses|ses|is|es|s)?$")
_ACC = {"": 0, "is": 1, "isis": 2, "es": -1, "eses": -2, "s": -1, "ses": -2}


def parse_note_name(word: str) -> Optional[tuple[int, int]]:
    """'fis' -> (3, 1). Returns None if `word` is not a note name."""
    m = _NOTE_NAME.match(word)
    if not m:
        return None
    letter, acc = m.group(1), m.group(2) or ""
    if acc in ("s", "ses") and letter not in "ea":
        return None
    return STEP_NAMES.index(letter), _ACC[acc]


def _dur_beats(s: str) -> float:
    """'4.' -> 1.5 beats."""
    m = re.match(r"(\d+)(\.*)", s)
    if not m:
        return 1.0
    base = 4.0 / int(m.group(1))
    total, add = base, base
    for _ in m.group(2):
        add /= 2
        total += add
    return total


DUR_TABLE = [(6.0, "1."), (4.0, "1"), (3.0, "2."), (2.0, "2"), (1.5, "4."),
             (1.0, "4"), (0.75, "8."), (0.5, "8"), (0.375, "16."), (0.25, "16"),
             (0.125, "32"), (0.0625, "64")]


def split_duration(d: float) -> list[tuple[float, str]]:
    """Greedy split of a duration into notatable values (tied in output)."""
    out = []
    rem = d
    while rem > 0.0625 - EPS:
        for val, s in DUR_TABLE:
            if val <= rem + EPS:
                out.append((val, s))
                rem -= val
                break
    return out


def duration_string(d: float) -> str:
    """A single LilyPond duration for `d` beats (uses 16*n if not a plain value)."""
    for val, s in DUR_TABLE:
        if abs(val - d) < EPS:
            return s
    return f"16*{int(round(d * 4))}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_MODES = {"major": "major", "minor": "minor", "ionian": "major", "aeolian": "minor",
          "dorian": "minor", "phrygian": "minor", "lydian": "major",
          "mixolydian": "major", "locrian": "minor"}
_SKIP_BLOCKS = {"header", "paper", "layout", "midi", "with"}
_ONE_ARG = {"clef", "bar", "mark", "markup", "set", "override", "unset",
            "language", "include", "version", "new", "context", "transposition"}


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)
        self.warnings: list[str] = []
        self.notes: list[Note] = []
        self.t = 0.0
        self.last_dur = 1.0
        self.depth = 0
        self.rel_ref: Optional[int] = None       # diatonic number of previous note
        self.rel_depth: Optional[int] = None
        self.pending_tie = False
        self.key: Optional[KeySig] = None
        self.num, self.den = 4, 4
        self.time_set = False
        self.pickup = 0.0
        self.partial_given = False
        self.tempo_bpm, self.tempo_unit = 100, "4"
        self.bar_start_t = 0.0
        self.bar_no = 1

    # -- low-level scanning ------------------------------------------------
    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def skip_ws(self) -> None:
        while self.i < self.n:
            c = self.s[self.i]
            if c.isspace():
                self.i += 1
            elif c == "%":
                self.skip_comment()
            else:
                break

    def skip_comment(self) -> None:
        if self.s.startswith("%{", self.i):
            j = self.s.find("%}", self.i + 2)
            self.i = self.n if j < 0 else j + 2
        else:
            j = self.s.find("\n", self.i)
            self.i = self.n if j < 0 else j + 1

    def match(self, pattern: str) -> Optional[re.Match]:
        m = re.compile(pattern).match(self.s, self.i)
        if m:
            self.i = m.end()
        return m

    def skip_string(self) -> str:
        m = self.match(r'"(?:[^"\\]|\\.)*"')
        return m.group(0) if m else ""

    def skip_block(self) -> None:
        """Skip a balanced { ... } block (after an ignored command)."""
        self.skip_ws()
        if self.i >= self.n or self.s[self.i] != "{":
            return
        level = 0
        while self.i < self.n:
            c = self.s[self.i]
            if c == "%":
                self.skip_comment()
                continue
            if c == '"':
                if not self.skip_string():
                    self.i += 1
                continue
            self.i += 1
            if c == "{":
                level += 1
            elif c == "}":
                level -= 1
                if level == 0:
                    return

    def read_duration(self) -> Optional[float]:
        """Read an optional duration; returns beats or None if absent."""
        m = self.match(r"(\d+)?(\.*)(?:\*(\d+)(?:/(\d+))?)?")
        if not m or not m.group(0):
            return None
        if m.group(1):
            n = int(m.group(1))
            if n not in (1, 2, 4, 8, 16, 32, 64, 128):
                self.warn(f"unsupported duration '{n}', using a quarter")
                n = 4
            base = 4.0 / n
            total, add = base, base
            for _ in m.group(2):
                add /= 2
                total += add
            self.last_dur = total
        elif m.group(2):
            self.warn("dots without a duration number ignored")
        dur = self.last_dur
        if m.group(3):
            dur *= int(m.group(3)) / int(m.group(4) or 1)
        return dur

    def read_pitch_word(self) -> Optional[tuple[int, int, int]]:
        """Read note name + octave marks -> (step, alter, mark_count)."""
        m = self.match(r"[a-z]+")
        if not m:
            return None
        nn = parse_note_name(m.group(0))
        if nn is None:
            return None
        marks = self.match(r"[',]*").group(0)
        return nn[0], nn[1], marks.count("'") - marks.count(",")

    # -- main loop ------------------------------------------------------------
    def run(self) -> Score:
        while self.i < self.n:
            c = self.s[self.i]
            if c.isspace():
                self.i += 1
            elif c == "%":
                self.skip_comment()
            elif c == "{":
                self.depth += 1
                self.i += 1
            elif c == "}":
                self.depth -= 1
                self.i += 1
                if self.rel_depth is not None and self.depth <= self.rel_depth:
                    self.rel_ref, self.rel_depth = None, None
            elif c == "|":
                self.i += 1
                self.bar_check()
            elif c == "~":
                self.i += 1
                self.pending_tie = True
            elif c == "\\":
                self.command()
            elif c.isalpha():
                self.word()
            elif c == '"':
                self.warn(f"ignored string {self.skip_string() or c}")
                if self.s[self.i:self.i + 1] == '"':
                    self.i += 1
            elif c in "-^_" and self.i + 1 < self.n:
                self.i += 1
                if self.s[self.i] == '"':
                    self.skip_string()
                elif self.s[self.i] == "\\":
                    self.match(r"\\[A-Za-z]+")
                else:
                    self.i += 1
                self.warn("ignored articulation")
            else:
                self.warn(f"ignored '{c}'")
                self.i += 1
        return self.finish()

    def finish(self) -> Score:
        if self.pending_tie:
            self.warn("dangling tie '~' at end ignored")
        merged: list[Note] = []
        for nt in self.notes:
            if merged and nt.midi is None and merged[-1].midi is None:
                merged[-1].dur += nt.dur
            else:
                merged.append(nt)
        meter = Meter(self.num, self.den, self.pickup)
        return Score(merged, self.key, meter, self.tempo_bpm, self.tempo_unit, self.warnings)

    def bar_check(self) -> None:
        length = self.t - self.bar_start_t
        if length < EPS:
            return
        bar_len = self.num * 4.0 / self.den
        expected = bar_len
        if self.bar_no == 1 and self.pickup > EPS:
            expected = self.pickup
        elif self.bar_no == 1 and length < bar_len - EPS and not self.partial_given:
            self.pickup = length
            expected = length
            self.warn(f"bar 1 is {length:g} beats; treating it as a pickup (\\partial)")
        if abs(length - expected) > EPS:
            self.warn(f"bar {self.bar_no}: length {length:g} beats, expected {expected:g}")
        self.bar_start_t = self.t
        self.bar_no += 1

    def word(self) -> None:
        m = self.match(r"[A-Za-z]+")
        w = m.group(0)
        nn = parse_note_name(w)
        if nn is not None:
            marks = self.match(r"[',]*").group(0)
            self.match(r"[!?]?")
            dur = self.read_duration()
            self.add_note(nn[0], nn[1], marks.count("'") - marks.count(","),
                          self.last_dur if dur is None else dur)
        elif w in ("r", "s", "R"):
            dur = self.read_duration()
            self.add_rest(self.last_dur if dur is None else dur)
        else:
            self.warn(f"ignored word '{w}'")

    def add_note(self, step: int, alter: int, marks: int, dur: float) -> None:
        if self.rel_ref is not None:
            prev_step = self.rel_ref % 7
            delta = (step - prev_step) % 7
            if delta > 3:
                delta -= 7
            dn = self.rel_ref + delta + 7 * marks
            self.rel_ref = dn
        else:
            dn = (3 + marks) * 7 + step
        octave, st = divmod(dn, 7)
        midi = 12 * (octave + 1) + NATURAL[st] + alter
        if self.pending_tie:
            self.pending_tie = False
            last = self.notes[-1] if self.notes else None
            if last is not None and last.midi == midi and abs(last.end - self.t) < EPS:
                last.dur += dur
                self.t += dur
                return
            self.warn("tie between different pitches ignored")
        self.notes.append(Note(midi, self.t, dur))
        self.t += dur

    def add_rest(self, dur: float) -> None:
        if self.pending_tie:
            self.warn("tie into a rest ignored")
            self.pending_tie = False
        self.notes.append(Note(None, self.t, dur))
        self.t += dur

    def command(self) -> None:
        m = self.match(r"\\([A-Za-z]+)")
        if not m:
            self.warn(f"ignored '{self.s[self.i:self.i + 2]}'")
            self.i += 2
            return
        name = m.group(1)
        if name == "relative":
            self.skip_ws()
            save = self.i
            p = self.read_pitch_word()
            if p is None:
                self.i = save
                self.rel_ref = 3 * 7 + 3          # f: first note behaves as absolute
            else:
                self.rel_ref = (3 + p[2]) * 7 + p[0]
            self.rel_depth = self.depth
        elif name == "absolute":
            self.rel_ref, self.rel_depth = None, None
        elif name == "key":
            self.skip_ws()
            p = self.read_pitch_word()
            self.skip_ws()
            mm = self.match(r"\\([A-Za-z]+)")
            mode = _MODES.get(mm.group(1)) if mm else None
            if p is None or mode is None:
                self.warn("could not read \\key; it will be detected")
                return
            if mm.group(1) not in ("major", "minor"):
                self.warn(f"mode \\{mm.group(1)} treated as {mode}")
            k = KeySig(p[0], p[1], mode)
            if self.key is not None and self.notes and k != self.key:
                self.warn("key change ignored (only one key supported)")
                return
            self.key = k
        elif name == "time":
            self.skip_ws()
            mm = self.match(r"(\d+)\s*/\s*(\d+)")
            if not mm:
                self.warn("could not read \\time")
                return
            num, den = int(mm.group(1)), int(mm.group(2))
            if self.time_set and self.notes and (num, den) != (self.num, self.den):
                self.warn("time signature change ignored")
                return
            self.num, self.den, self.time_set = num, den, True
        elif name == "tempo":
            self.skip_ws()
            if self.s[self.i:self.i + 1] == '"':
                self.skip_string()
                self.skip_ws()
            mm = self.match(r"(\d+\.*)\s*=\s*(\d+)(?:\s*-\s*\d+)?")
            if mm:
                self.tempo_unit, self.tempo_bpm = mm.group(1), int(mm.group(2))
            else:
                self.warn("\\tempo without a metronome mark ignored")
        elif name == "partial":
            self.skip_ws()
            d = self.read_duration()
            if d:
                self.pickup = d
                self.partial_given = True
        elif name in ("major", "minor"):
            self.warn(f"stray \\{name} ignored")
        elif name in _SKIP_BLOCKS:
            self.warn(f"ignored \\{name} block")
            self.skip_block()
        elif name in _ONE_ARG:
            self.skip_ws()
            if self.s[self.i:self.i + 1] == '"':
                self.skip_string()
            else:
                self.match(r"[A-Za-z_.0-9]+")
            if name != "version":
                self.warn(f"ignored \\{name}")
        else:
            self.warn(f"ignored \\{name}")


def parse(text: str) -> Score:
    """Parse LilyPond text (supported subset) into a Score."""
    return _Parser(text).run()


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _atoms(notes: list[Note], meter: Meter, end: float) -> list[tuple[Optional[int], str, float, bool]]:
    """Split notes at barlines into notatable pieces: (midi, dur_str, end_time, tie)."""
    seq: list[tuple[Optional[int], float, float]] = []
    t = 0.0
    for n in sorted(notes, key=lambda x: x.start):
        if n.start > t + EPS:
            seq.append((None, t, n.start - t))
        seq.append((n.midi, n.start, n.dur))
        t = n.end
    if end > t + EPS:
        seq.append((None, t, end - t))
    atoms = []
    for midi, start, dur in seq:
        t, stop = start, start + dur
        pieces = []
        while t < stop - EPS:
            chunk_end = min(stop, meter.bar_end(meter.bar_index(t)))
            for val, s in split_duration(chunk_end - t):
                t += val
                pieces.append([midi, s, t, False])
            t = chunk_end
        if midi is not None:
            for p in pieces[:-1]:
                p[3] = True
        atoms.extend(tuple(p) for p in pieces)
    return atoms


def format_notes(notes: list[Note], key: KeySig, meter: Meter,
                 end: Optional[float] = None, bars_per_line: int = 0) -> str:
    """Notes as an absolute-mode LilyPond string with bar checks, e.g. "c'4 d' | e'1".
    Durations are only written when they change (sticky). Bars are padded with rests."""
    last = max((n.end for n in notes), default=0.0)
    end = meter.end_of_music(max(end or 0.0, last))
    out: list[str] = []
    prev = None
    bars = 0
    for midi, ds, t_end, tie in _atoms(notes, meter, end):
        name = "r" if midi is None else midi_to_lily(midi, key)
        out.append(name + ("" if ds == prev else ds) + ("~" if tie else ""))
        prev = ds
        if meter.bar_pos(t_end) < EPS and t_end < end - EPS:
            bars += 1
            out.append("|\n" if bars_per_line and bars % bars_per_line == 0 else "|")
    text = " ".join(out)
    return text.replace("|\n ", "|\n")


def format_music(notes: list[Note], key: KeySig, meter: Meter, tempo_bpm: int = 100,
                 tempo_unit: str = "4", end: Optional[float] = None) -> str:
    """A self-contained music expression (headers + notes) that `parse` can read back."""
    head = [f"\\key {key.lily()}", f"\\time {meter.num}/{meter.den}",
            f"\\tempo {tempo_unit} = {tempo_bpm}"]
    if meter.pickup > EPS:
        head.append(f"\\partial {duration_string(meter.pickup)}")
    return "{ " + " ".join(head) + " " + format_notes(notes, key, meter, end) + " }"


def chord_symbol(root_pc: int, quality: str, key: KeySig) -> str:
    """Chordmode root + modifier, e.g. 'fis' + ':m'."""
    st, alt = _spelling(key)[root_pc]
    return pitch_name(st, alt), (":" + quality if quality else "")


def format_chords(chords: list[tuple[float, float, int, str]], key: KeySig, meter: Meter) -> str:
    """Chords (start, end, root_pc, quality) as chordmode text with bar checks."""
    out: list[str] = []
    prev = None
    for start, end, root, quality in chords:
        name, mod = chord_symbol(root, quality, key)
        t = start
        while t < end - EPS:
            chunk_end = min(end, meter.bar_end(meter.bar_index(t)))
            for val, s in split_duration(chunk_end - t):
                out.append(name + ("" if s == prev else s) + mod)
                prev = s
                t += val
            t = chunk_end
            if meter.bar_pos(t) < EPS and t < chords[-1][1] - EPS:
                out.append("|")
    return " ".join(out)


def write_score(*, title: str, melody: list[Note], counter: list[Note], key: KeySig,
                meter: Meter, tempo_bpm: int, tempo_unit: str,
                chords: list[tuple[float, float, int, str]], voice_name: str,
                counter_clef: str, melody_clef: str, meta: str) -> str:
    """A complete, compilable LilyPond file with melody, counter-melody and chord names."""
    end = meter.end_of_music(max(n.end for n in melody + counter))
    partial = f"  \\partial {duration_string(meter.pickup)}\n" if meter.pickup > EPS else ""
    common = f"  \\key {key.lily()}\n  \\time {meter.num}/{meter.den}\n"
    mel = format_notes(melody, key, meter, end, bars_per_line=4)
    cnt = format_notes(counter, key, meter, end, bars_per_line=4)
    chd = format_chords(chords, key, meter)
    clef = lambda c: f'"{c}"' if "_" in c else c
    return (
        '\\version "2.24.0"\n'
        f"% meta: {meta}\n\n"
        "\\header {\n"
        f'  title = "{title}"\n'
        f'  subtitle = "Counter-melody for {voice_name}"\n'
        "  tagline = ##f\n"
        "}\n\n"
        "melody = {\n"
        f"  \\clef {clef(melody_clef)}\n{common}"
        f"  \\tempo {tempo_unit} = {tempo_bpm}\n{partial}"
        f"  {mel.replace(chr(10), chr(10) + '  ')}\n"
        '  \\bar "|."\n'
        "}\n\n"
        "counter = {\n"
        f"  \\clef {clef(counter_clef)}\n{common}{partial}"
        f"  {cnt.replace(chr(10), chr(10) + '  ')}\n"
        '  \\bar "|."\n'
        "}\n\n"
        "\\score {\n"
        "  <<\n"
        "    \\new ChordNames \\chordmode {\n"
        "      \\set chordChanges = ##t\n"
        f"{partial.replace('  ', '      ', 1)}"
        f"      {chd}\n"
        "    }\n"
        '    \\new Staff \\with { instrumentName = "Melody" } \\melody\n'
        f'    \\new Staff \\with {{ instrumentName = "{voice_name.capitalize()}" }} \\counter\n'
        "  >>\n"
        "  \\layout { }\n"
        "}\n"
    )
