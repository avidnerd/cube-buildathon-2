"""Lyrics: hear the words (Whisper), then pin each syllable to a sung note so
the karaoke knows what to sing *when* - for the melody and every harmony part.

    hear_words(vocals, sr) -> list[Word]            # Whisper word timestamps
    attach_lyrics(notes, words) -> notes             # adds "lyric" to each note
    lyrics_from_text(notes, text) -> notes           # user-typed lyrics instead
    lines_from_notes(notes) -> list[line]            # karaoke lines
    lyric_for_harmony(track, melody) -> track        # harmony notes get the same syllables
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

import numpy as np

os.environ.setdefault("USE_TF", "0")      # transformers must not import TensorFlow
os.environ.setdefault("USE_TORCH", "1")

WHISPER_MODEL = "openai/whisper-small"
HOLD = "~"   # melisma: keep singing the previous syllable

_asr = None
_lock = threading.Lock()


@dataclass
class Word:
    text: str
    t0: float
    t1: float


# ---------------------------------------------------------------------------
# Hearing
# ---------------------------------------------------------------------------


def _load():
    global _asr
    with _lock:
        if _asr is None:
            import torch
            from transformers import pipeline
            # Apple GPU in float32 is ~2x faster than CPU here (float16 was slower).
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            try:
                _asr = pipeline("automatic-speech-recognition", model=WHISPER_MODEL, device=device,
                                torch_dtype=torch.float32)
            except Exception:
                _asr = pipeline("automatic-speech-recognition", model=WHISPER_MODEL, device="cpu")
    return _asr


def hear_words(vocals: np.ndarray, sr: int, language: str | None = None) -> list[Word]:
    from backend.harmony.beats import resample

    x = resample(np.asarray(vocals, dtype=np.float64), sr, 16000).astype(np.float32)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < 1e-4:
        return []
    x = x / peak * 0.9
    kw = {"task": "transcribe"}
    if language:
        kw["language"] = language
    long = len(x) > 30 * 16000
    out = _load()({"raw": x, "sampling_rate": 16000}, return_timestamps="word",
                  generate_kwargs=kw, **({"chunk_length_s": 30, "batch_size": 4} if long else {}))

    # Whisper hallucinates in silence ("Thank you."): drop words with no voice under them.
    hop = 160
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, mode="same")[::hop])
    gate = 0.04 * float(np.percentile(rms, 95)) if rms.size else 0.0
    words: list[Word] = []
    for ch in out.get("chunks", []):
        t0, t1 = ch["timestamp"]
        text = ch["text"].strip()
        if not text or t0 is None:
            continue
        t1 = t1 if t1 is not None else t0 + 0.3
        seg = rms[int(t0 * 100): max(int(t0 * 100) + 1, int(t1 * 100))]
        if seg.size and seg.max() < gate:
            continue
        words.append(Word(text, float(t0), float(t1)))
    return words


# ---------------------------------------------------------------------------
# Syllables
# ---------------------------------------------------------------------------

_VOWELS = "aeiouy"


def syllables(word: str) -> list[str]:
    """Rough English syllabification, good enough to spread a word over notes.

    "twinkle" -> ["twin", "kle"], "little" -> ["lit", "tle"], "star" -> ["star"].
    """
    core = re.sub(r"[^A-Za-z']", "", word)
    if len(core) <= 3:
        return [word]
    low = core.lower()
    groups = [m.span() for m in re.finditer(f"[{_VOWELS}]+", low)]
    # Silent final e ("make", "love"), but not "-le" ("little", "table").
    if len(groups) > 1 and low.endswith("e") and groups[-1] == (len(low) - 1, len(low)) and not low.endswith("le"):
        groups = groups[:-1]
    if len(groups) <= 1:
        return [word]
    cuts = []
    for (_, e1), (s2, _) in zip(groups, groups[1:]):
        cons = s2 - e1
        if low.endswith("le") and s2 == len(low) - 1:     # consonant + le: "lit-tle", "twin-kle"
            cuts.append(s2 - 2)
        elif cons >= 2:
            cuts.append(e1 + cons // 2)
        else:
            cuts.append(e1)
    # Map cuts on the letters-only core back onto the original word (keeps punctuation).
    letter_pos = [i for i, ch in enumerate(word) if re.match(r"[A-Za-z']", ch)]
    pieces, prev = [], 0
    for c in cuts:
        if 0 < c < len(letter_pos):
            pieces.append(word[prev: letter_pos[c]])
            prev = letter_pos[c]
    pieces.append(word[prev:])
    return [p for p in pieces if p]


def _spread(word_text: str, n_notes: int) -> list[str]:
    """Syllables of one word over n notes: one each, extra notes hold, extra syllables merge."""
    syl = syllables(word_text)
    if n_notes <= 0:
        return []
    if len(syl) > n_notes:
        syl = syl[: n_notes - 1] + ["".join(syl[n_notes - 1:])]
    out = [s + ("-" if i < len(syl) - 1 else "") for i, s in enumerate(syl)]
    return out + [HOLD] * (n_notes - len(out))


# ---------------------------------------------------------------------------
# Attaching words to notes
# ---------------------------------------------------------------------------


def _best_shift(words: list[Word], on: np.ndarray, max_shift: float = 0.8) -> float:
    """Global time shift for Whisper's words, chosen by two clues:
      1. word starts should land on note onsets;
      2. each word should span about as many onsets as it has syllables.
    Clue 2 resolves the ambiguity when notes are closer together than
    Whisper's error. The first word's stamp is ignored (often 0.0).
    """
    syl = np.array([len(syllables(w.text)) for w in words])
    starts = np.array([w.t0 for w in words])
    best, best_score = 0.0, -np.inf
    for sh in np.arange(-max_shift, max_shift + 1e-9, 0.02):
        t = starts + sh
        d = np.min(np.abs(on[None, :] - t[1:, None]), axis=1) if len(t) > 1 else np.zeros(0)
        hit = np.exp(-0.5 * (d / 0.06) ** 2).sum()
        idx = np.searchsorted(on, t - 0.03)
        spans = np.diff(idx)                    # onsets covered by words 0..n-2
        short = np.maximum(syl[:-1] - spans, 0)  # fewer notes than syllables: bad
        extra = np.maximum(spans - syl[:-1], 0)  # melisma: allowed, mildly
        score = hit - 0.6 * short.sum() - 0.1 * extra.sum() - 0.5 * abs(sh)
        if score > best_score:
            best, best_score = float(sh), score
    return best


def refine_word_times(words: list[Word], onsets: list[float], snap: float = 0.25) -> list[Word]:
    """Whisper's word times are approximate (the first word is often stamped
    0.0, the rest drift by a few hundred ms). The pitch tracker knows exactly
    when each sung note starts, so: remove the overall offset, then snap each
    word start to the nearest note onset, keeping words in order.
    """
    if not words or not onsets:
        return words
    on = np.sort(np.asarray(onsets, dtype=float))

    def nearest(t):
        i = int(np.clip(np.searchsorted(on, t), 1, len(on) - 1)) if len(on) > 1 else 0
        cands = on[max(0, i - 1): i + 1]
        return float(cands[np.argmin(np.abs(cands - t))])

    shift = _best_shift(words, on)

    out: list[Word] = []
    floor = -np.inf
    for k, w in enumerate(words):
        t0 = w.t0 + shift
        if k == 0:
            later = on[on >= floor]
            first_on = float(later[0]) if later.size else t0
            nxt = words[1].t0 + shift if len(words) > 1 else np.inf
            t0 = first_on if first_on < nxt else t0  # first word = first sung onset before word 2
        else:
            n = nearest(t0)
            if abs(n - t0) <= snap:
                t0 = n
        t0 = max(t0, floor + 0.02)
        t1 = max(t0 + 0.05, w.t1 + shift)
        out.append(Word(w.text, t0, t1))
        floor = t0
    for a, b in zip(out, out[1:]):
        if a.t1 > b.t0:                    # no overlaps
            a.t1 = max(a.t0 + 0.02, b.t0 - 0.01)
        elif b.t0 - a.t1 < 0.6 or a is out[0]:  # legato (and word 1's end stamp is unreliable)
            a.t1 = b.t0 - 0.01
    return out


def attach_lyrics(notes: list[dict], words: list[Word]) -> list[dict]:
    """Give each melody note its syllable, using the notes' t0/t1 (seconds).

    Word times are first corrected against the notes' onsets. Then each note
    goes to the word it overlaps most; each word's notes share its syllables.
    Words that landed between notes take the nearest free note.
    """
    notes = [dict(n, lyric="", word_start=False) for n in notes]
    if not notes or not words:
        return notes
    words = refine_word_times(list(words), [n["t0"] for n in notes])
    owner = [-1] * len(notes)
    for i, n in enumerate(notes):
        best, best_ov = -1, 0.0
        for j, w in enumerate(words):
            ov = min(n["t1"], w.t1) - max(n["t0"], w.t0)
            if ov > best_ov:
                best, best_ov = j, ov
        owner[i] = best
    # Words with no note: nearest unowned note, else share the nearest note.
    riders: dict[int, list[int]] = {}  # owner word -> extra words sung on its notes
    for j, w in enumerate(words):
        if j in owner:
            continue
        mid = 0.5 * (w.t0 + w.t1)
        free = [i for i in range(len(notes)) if owner[i] == -1]
        pool = free or range(len(notes))
        i = min(pool, key=lambda i: abs(0.5 * (notes[i]["t0"] + notes[i]["t1"]) - mid))
        if owner[i] == -1:
            owner[i] = j
        else:
            riders.setdefault(owner[i], []).append(j)
    for j, extra in riders.items():  # join sharers in sung order
        group = sorted([j, *extra], key=lambda k: (words[k].t0, k))
        words[j] = Word(" ".join(words[k].text for k in group), words[group[0]].t0, words[group[-1]].t1)
    # Keep owners monotonic (a later note can't belong to an earlier word).
    for i in range(1, len(owner)):
        if owner[i] != -1 and owner[i - 1] != -1 and owner[i] < owner[i - 1]:
            owner[i] = owner[i - 1]
    i = 0
    while i < len(notes):
        j = owner[i]
        if j == -1:
            i += 1
            continue
        k = i
        while k < len(notes) and owner[k] == j:
            k += 1
        for m, syl in zip(range(i, k), _spread(words[j].text, k - i)):
            notes[m]["lyric"] = syl
            notes[m]["word_start"] = m == i
        i = k
    return notes


def lyrics_from_text(notes: list[dict], text: str) -> list[dict]:
    """User-typed lyrics: one syllable per note, in order. "_" holds a note."""
    syls: list[tuple[str, bool]] = []
    for word in text.split():
        if word == "_":
            syls.append((HOLD, False))
            continue
        parts = syllables(word)
        for i, p in enumerate(parts):
            syls.append((p + ("-" if i < len(parts) - 1 else ""), i == 0))
    out = []
    for i, n in enumerate(notes):
        lyric, start = syls[i] if i < len(syls) else ("", False)
        out.append(dict(n, lyric=lyric, word_start=start))
    if len(syls) > len(notes) and out:  # leftover text goes on the last note
        extra = [s for s, _ in syls[len(notes):] if s != HOLD]
        if extra:
            out[-1]["lyric"] += " " + " ".join(extra)
    return out


def lines_from_notes(notes: list[dict], max_chars: int = 42, gap_beats: float = 1.5) -> list[dict]:
    """Group notes into karaoke lines at rests, punctuation, or length."""
    lines: list[dict] = []
    cur: list[int] = []
    chars = 0

    def close():
        if cur:
            lines.append({"notes": list(cur), "start": notes[cur[0]]["start"],
                          "end": notes[cur[-1]]["start"] + notes[cur[-1]]["duration"],
                          "text": join_lyrics(notes[i]["lyric"] for i in cur)})

    for i, n in enumerate(notes):
        if cur:
            prev = notes[cur[-1]]
            gap = n["start"] - (prev["start"] + prev["duration"])
            punct = prev["lyric"].rstrip("-").endswith((".", ",", "!", "?", ";"))
            if gap >= gap_beats or (n.get("word_start") and (punct or chars >= max_chars)):
                close()
                cur, chars = [], 0
        cur.append(i)
        chars += len(n.get("lyric", ""))
    close()
    return lines


def join_lyrics(syls) -> str:
    out = ""
    for s in syls:
        if not s or s == HOLD:
            continue
        if out and not out.endswith("-"):
            out += " "
        out += s
    return out.replace("-", "")


def lyric_for_harmony(track: list[dict], melody: list[dict], pad_vowel: str = "ooh") -> list[dict]:
    """Harmony notes sing the melody's syllables (same rhythm => same words).

    A harmony note that spans several melody notes (pad style) sings a vowel.
    """
    out = []
    for h in track:
        h_end = h["start"] + h["duration"]
        under = [m for m in melody if h["start"] - 1e-6 <= m["start"] < h_end - 1e-6]
        if len(under) == 1 or (under and abs(under[0]["duration"] - h["duration"]) < 1e-6):
            lyric, ws = under[0].get("lyric", ""), under[0].get("word_start", False)
        elif under:
            lyric, ws = pad_vowel, True
        else:
            lyric, ws = "", False
        out.append(dict(h, lyric=lyric, word_start=ws))
    return out
