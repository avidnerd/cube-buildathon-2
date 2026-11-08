"""Training data: real (lead, harmony) pairs from songs people arranged.

Sources
  * Bach chorales (music21 corpus): soprano = lead, alto = harmony below,
    tenor + bass = the "band".
  * Lakh MIDI: songs with a lead-vocal track and a harmony/backing-vocal
    track that moves with it; every other pitched track = the band.

Each piece becomes training examples for harmonizer.fit_style(): the lead's
notes, the harmony pitch sung under/over each lead note (note-for-note, as the
studio produces), and a *measured* scene built from the band's notes, so the
model learns how harmony relates to what's actually playing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from backend.harmony.dissonance import Scene, partials
from backend.harmony.reharmonize import CANDIDATES, MASKS, Chord, estimate_key

Note = tuple[int, float, float]  # (pitch, t0, t1) seconds


@dataclass
class Piece:
    id: str
    source: str
    lead: list[Note]
    harmony: list[Note]
    band: list[Note]
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Alignment: the harmony pitch sung with each lead note
# ---------------------------------------------------------------------------

def align(lead: Sequence[Note], harmony: Sequence[Note], min_cover: float = 0.5) -> list[int | None]:
    """For each lead note, the harmony pitch sounding with it (None if the
    harmony is resting or moves to a different rhythm there)."""
    hs = sorted(harmony, key=lambda n: n[1])
    starts = np.array([n[1] for n in hs]) if hs else np.zeros(0)
    out: list[int | None] = []
    for p, t0, t1 in lead:
        dur = t1 - t0
        best, cover = None, 0.0
        i = max(0, int(np.searchsorted(starts, t0)) - 4)
        while i < len(hs) and hs[i][1] < t1:
            hp, h0, h1 = hs[i]
            ov = min(t1, h1) - max(t0, h0)
            if ov > cover:
                best, cover = hp, ov
            i += 1
        out.append(best if best is not None and cover >= min_cover * dur else None)
    return out


def rhythm_match(lead: Sequence[Note], harmony: Sequence[Note], tol: float = 0.06) -> float:
    """Share of harmony onsets that coincide with a lead onset (a true vocal
    harmony moves with the lead; a counter-melody doesn't)."""
    if not harmony or not lead:
        return 0.0
    lo = np.sort([n[1] for n in lead])
    hits = 0
    for _, h0, _ in harmony:
        i = int(np.searchsorted(lo, h0))
        near = min(abs(lo[j] - h0) for j in (i - 1, i) if 0 <= j < len(lo))
        hits += near <= tol
    return hits / len(harmony)


# ---------------------------------------------------------------------------
# The band as a measured scene + chords
# ---------------------------------------------------------------------------

class BandIndex:
    def __init__(self, band: Sequence[Note]):
        self.band = sorted(band, key=lambda n: n[1])
        self.starts = np.array([n[1] for n in self.band]) if self.band else np.zeros(0)
        self.max_dur = max((n[2] - n[1] for n in self.band), default=0.0)

    def sounding(self, t0: float, t1: float) -> list[tuple[int, float]]:
        """(pitch, overlap seconds) of band notes overlapping [t0, t1]."""
        lo = int(np.searchsorted(self.starts, t0 - self.max_dur))
        hi = int(np.searchsorted(self.starts, t1))
        out = []
        for p, a, b in self.band[lo:hi]:
            ov = min(b, t1) - max(a, t0)
            if ov > 0:
                out.append((p, ov))
        return out

    def scene(self, t0: float, t1: float, lead_pitch: int) -> Scene:
        snd = self.sounding(t0, t1)
        dur = max(t1 - t0, 1e-3)
        fs, as_ = [], []
        chroma = np.zeros(12)
        for p, ov in snd:
            f, a = partials(440.0 * 2 ** ((p - 69) / 12), 0.5 * ov / dur)
            fs.append(f)
            as_.append(a)
            chroma[p % 12] += ov / dur
        lead_hz = 440.0 * 2 ** ((lead_pitch - 69) / 12)
        lf, la = partials(lead_hz, 1.0)
        fs.append(lf)
        as_.append(la)
        if chroma.max() > 0:
            chroma = chroma / chroma.max()
        chroma[lead_pitch % 12] += 1.0
        return Scene(np.concatenate(fs), np.concatenate(as_), chroma, lead_hz, measured=bool(snd))

    def chord(self, t0: float, t1: float) -> Chord | None:
        w = np.zeros(12)
        for p, ov in self.sounding(t0, t1):
            w[p % 12] += ov * (1.5 if p < 55 else 1.0)  # bass notes say more about the chord
        if w.sum() <= 0 or np.count_nonzero(w) < 2:
            return None
        unit = MASKS / np.linalg.norm(MASKS, axis=1, keepdims=True)
        return CANDIDATES[int(np.argmax(unit @ (w / np.linalg.norm(w))))]


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------

def segments(lead: Sequence[Note], gold: Sequence[int | None], min_len: int = 4, max_len: int = 48):
    """Runs of consecutive lead notes that all have a harmony note."""
    run: list[int] = []
    for i, g in enumerate(gold):
        if g is not None:
            run.append(i)
            if len(run) == max_len:
                yield run
                run = []
        else:
            if len(run) >= min_len:
                yield run
            run = []
    if len(run) >= min_len:
        yield run


def piece_examples(piece: Piece, max_examples: int = 12, max_len: int = 48, compact: bool = False,
                   acappella: bool = False):
    """acappella=True: hide the band and give the model only chord guesses, as
    for a voice-only recording (so the model learns that situation too)."""
    """Training examples (harmonizer.Example) from one piece."""
    from backend.harmony.harmonizer import make_example

    gold = align(piece.lead, piece.harmony)
    pairs = [(n, g) for n, g in zip(piece.lead, gold) if g is not None]
    if len(pairs) < 8:
        return []
    ivs = np.array([g - n[0] for n, g in pairs])
    side = 1 if np.median(ivs) >= 0 else -1
    target = 3.5 if side > 0 else 5.0
    allp = [n[0] for n in piece.lead] + [g for _, g in pairs]
    voice = (min(allp) - 3, max(allp) + 3, min(allp), max(allp))
    prof = np.zeros(12)
    for p, a, b in list(piece.lead) + list(piece.band):
        prof[p % 12] += b - a
    key = estimate_key(prof)
    band = BandIndex(piece.band)
    from backend.harmony.dissonance import chord_scene

    def scene_for(n):
        if not acappella:
            return band.scene(n["t0"], n["t1"], int(n["pitch"]))
        ch = band.chord(n["t0"], n["t1"])
        return chord_scene(list(ch.tones) if ch is not None else [], int(n["pitch"]))

    out = []
    for seg in segments(piece.lead, gold, max_len=max_len):
        mel = [{"pitch": piece.lead[i][0], "t0": piece.lead[i][1], "t1": piece.lead[i][2]} for i in seg]
        g = [gold[i] for i in seg]
        # Out-of-range or chromatic oddities are kept; the lattice always includes the gold note.
        ex = make_example(
            mel, lambda t: band.chord(t - 0.05, t + 0.05), key, voice, side, target, g,
            scene_for=scene_for,
            max_iv=14 if compact else None, compact=compact,
        )
        ex.meta = {"piece": piece.id, "source": piece.source, "side": side}
        out.append(ex)
        if len(out) >= max_examples:
            break
    return out


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def bach_pieces(limit: int | None = None, tempo: float = 80.0) -> Iterable[Piece]:
    from music21 import corpus

    spb = 60.0 / tempo
    seen = set()
    for i, path in enumerate(corpus.getComposer("bach")):
        if limit is not None and len(seen) >= limit:
            break
        try:
            sc = corpus.parse(path)
        except Exception:
            continue
        parts = [p for p in sc.parts]
        if len(parts) != 4:
            continue

        def notes(part) -> list[Note]:
            out = []
            for n in part.flatten().notes:
                if n.isChord:
                    continue
                t0 = float(n.getOffsetInHierarchy(sc)) * spb
                out.append((int(n.pitch.midi), t0, t0 + float(n.quarterLength) * spb))
            return out

        s, a, t, b = (notes(p) for p in parts)
        fp = hashlib.md5(str([n[0] for n in s[:40]]).encode()).hexdigest()  # same melody harmonized twice
        if fp in seen or len(s) < 12:
            continue
        seen.add(fp)
        yield Piece(f"bach:{Path(str(path)).stem}", "bach", s, a, t + b)


_LEAD = re.compile(r"(lead|main|solo)?\s*(vocal|vox|voice|melody|sing)", re.I)
_HARM = re.compile(r"harm|backing|back\s*vo|bgv|\bbvs?\b|choir|(vocal|vox|voice)s?\s*(2|ii|b|two)|chorus\s*vo|second\s*vo|2nd\s*vo|double", re.I)


def lakh_pieces(paths: Iterable[Path], min_rhythm: float = 0.6, verbose: bool = False) -> Iterable[Piece]:
    """Songs with a lead-vocal track and a harmony track that moves with it."""
    import pretty_midi

    seen = set()
    for path in paths:
        try:
            pm = pretty_midi.PrettyMIDI(str(path))
        except Exception:
            continue
        inst = [i for i in pm.instruments if not i.is_drum and len(i.notes) >= 16]
        names = [(i, (i.name or "").strip()) for i in inst]
        harms = [i for i, nm in names if _HARM.search(nm)]
        leads = [i for i, nm in names if _LEAD.search(nm) and not _HARM.search(nm)]
        if not harms or not leads:
            continue
        lead = max(leads, key=lambda i: len(i.notes))
        L = [(int(n.pitch), float(n.start), float(n.end)) for n in lead.notes]
        mono = _monophonic(L)
        fp = hashlib.md5(str([n[0] for n in mono[:60]]).encode()).hexdigest()
        if fp in seen:
            continue
        for h in harms:
            H = _monophonic([(int(n.pitch), float(n.start), float(n.end)) for n in h.notes])
            rm = rhythm_match(mono, H)
            ivs = [abs(g - n[0]) for n, g in zip(mono, align(mono, H)) if g is not None]
            if rm < min_rhythm or len(ivs) < 16 or np.median(ivs) > 12 or np.median(ivs) == 0:
                continue
            band = [(int(n.pitch), float(n.start), float(n.end)) for i in inst if i is not lead and i is not h for n in i.notes]
            seen.add(fp)
            if verbose:
                print(f"  {path.name}: lead '{lead.name}' + harmony '{h.name}' (rhythm {rm:.0%}, median interval {np.median(ivs):.0f})")
            yield Piece(f"lakh:{path.stem}", "lakh", mono, H, band, {"lead": lead.name, "harmony": h.name})
            break


def _monophonic(notes: Sequence[Note]) -> list[Note]:
    """Top note when a vocal track has stray overlaps/chords."""
    out: list[Note] = []
    for p, a, b in sorted(notes, key=lambda n: (n[1], -n[0])):
        if out and a < out[-1][2] - 1e-3:
            if a - out[-1][1] < 0.03:      # same onset: keep the higher note
                continue
            out[-1] = (out[-1][0], out[-1][1], a)
        out.append((p, a, b))
    return [n for n in out if n[2] - n[1] > 0.03]
