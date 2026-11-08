# Harmony model card

`harmony_net.npz` is the learned scorer used by the studio to choose harmony
notes (`neural.py`, decoded as a CRF over the note lattice in `harmonizer.py`).
It runs in plain numpy; training uses PyTorch.

## What it learns

Given the lead's notes (and the band, when there is one), it picks one harmony
note per lead note, on the lead's exact timing. For every candidate it sees the
interval to the lead, key-relative pitch classes, what the band is playing
relative to the candidate, the melody's contour, note length and phrase
position, plus the hand-built features (measured clash, chord tones, scale-degree
pairing...). A CRF scores whole lines so motion is learned too.

Hard rules applied on top: an upper part never goes below the lead (unison is
allowed), a lower part never above it; candidates are limited to ±14
semitones around the lead (the training window).

## Training data

| source | songs | what is used |
|---|---|---|
| [Lakh MIDI Dataset](https://colinraffel.com/projects/lmd/) (Colin Raffel, CC-BY 4.0) | 1,877 (of 2,319 mined) | songs with a lead-vocal track and a harmony/backing-vocal track that moves with it (≥60% shared onsets, within an octave); other pitched tracks = the band |
| Bach chorales via [music21](https://web.mit.edu/music21/) (BSD) | 288 | soprano = lead, alto = harmony, tenor + bass = the band |

Every song is used twice: with its band, and "a cappella" (band hidden, only
guessed chords), so voice-only recordings are in-distribution. Songs are split
train / validation / test by song; the numbers below are on 333 songs never
seen in training.

## Accuracy (exact harmony note vs. the real arrangement, unseen songs)

| | always a diatonic 3rd | hand-written rules | learned model |
|---|---|---|---|
| pop, with band | 32.8% | 24.7% | **51.8%** |
| pop, voice only | 32.8% | – | **47.4%** |
| Bach, with band | 26.1% | 12.7% | **62.1%** |
| Bach, voice only | 26.1% | – | **43.6%** |

On one user's a cappella take of a pop song (their own written harmony as
reference), the base model alone matched 50% of notes; with their fixes as a
per-song layer, 89%, and fixes generalized to an untaught phrase of the same
song (43–64% → 67–93%). Applying one song's fixes to other songs *hurt*
(52% → 36%), so the studio applies fixes only to the song they were made on.

Exact-match understates quality: a melody usually has several good harmony
lines, and only the arranger's exact choice counts as a hit.

## Known limits

- Larger leaps than the hand-built model (mostly between phrases).
- Pop data comes from MIDI transcriptions: track names are noisy and some
  "harmony" tracks are doubled leads or counter-melodies that survived the filters.
- Retrain with the scripts in `training/` (set HARMONY_DATA to a data folder): mine Lakh (`corpus.lakh_pieces`), build
  examples (`corpus.piece_examples`, `compact=True`, with and without `acappella`),
  then `neural.train`.
