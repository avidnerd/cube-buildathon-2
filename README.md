# Counter-melody generator

Write a melody in LilyPond. This tool writes **one** independent counter-melody that a friend can sing alongside it, and returns a complete LilyPond score.

It's all rule-based counterpoint: no ML, no randomness, and the same input always gives the same output.

## What's the app vs. what's testing only

| part | status | what it is |
|---|---|---|
| `lily.py` | **app** | LilyPond parser and writer (input/output layer) |
| `counter.py` | **app** | Music logic and command-line tool (`--voice`, `--out`, `--text`) |
| `counter.py --midi` → `testing_midi.py` | testing only | Writes `.mid` files so you can *listen* while developing. The app never imports it. |
| `counter.py --rank`, `--style`, `generate(force_fallback=...)` | testing only | Hooks used by the tests |
| `placeholder_ui/` (`server.py`, `index.html`) | testing only | Throwaway piano page for trying the generator by hand. **Not the real UI.** |
| `test_*.py` | testing only | Test suite |
| `requirements-dev.txt` (`mido`, `pytest`) | testing only | The app itself needs only the Python standard library |
| `out/` | testing only | Sample outputs generated from `samples/`, including the `.mid` listening files |
| `samples/` | example inputs | Five public-domain tunes |

## Usage (app)

```
python counter.py samples/twinkle.ly                         # print .ly + bare counter line
python counter.py samples/amazing_grace.ly --voice tenor --out out/
python counter.py --text "\relative c' { c4 d e f | g1 }" --voice tenor
```

| flag | meaning |
|---|---|
| `--voice soprano\|alto\|tenor\|bass` | range and clef of the counter (default alto) |
| `--out DIR` | write `DIR/<name>_counter.ly` |
| `--midi` | *(testing only)* write `<name>_original.mid`, `_counter.mid`, `_both.mid` (piano + clarinet) |
| `--rank N` | *(testing only)* the N-th best line |
| `--style calm\|active` | *(testing only)* override the automatic style |

`TUNING.md` explains every weight in the cost function.

## Testing tools

- **Placeholder UI (testing only):** run `python placeholder_ui/server.py` and open http://localhost:8000. Enter a melody on the piano, press *Generate*, and play both parts.
- **Listening:** `python counter.py samples/twinkle.ly --midi` writes `.mid` files to `out/`.
- **Setup:** `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- **Tests:** `.venv/bin/python -m pytest -q`. The LilyPond compile tests run only if `lilypond` is on your PATH.

## The 30-second pitch (for judges)

1. We parse the melody from LilyPond text and infer its key and chords: Krumhansl's key profiles if no key is given, and a best-fit chord per bar or half bar that favours progressions like I–IV–V–I.
2. We plan a complementary rhythm: wherever the melody holds a long note or rests, the counter-melody moves, and wherever the melody gets busy, the counter-melody holds still.
3. For every note slot, a beam search tries each singable scale tone and scores it with classic counterpoint rules: consonant intervals on strong beats, no parallel fifths or octaves, a reward for contrary motion and stepwise lines, and a penalty for simply shadowing the tune in parallel thirds.
4. When the melody is sparse, we also take a short motif from the tune and echo it in the counter-line a beat or two later, so the two voices talk to each other.
5. Finally, an independent checker re-verifies every hard rule and scores the result, and if anything is doubtful it falls back to a simple, guaranteed-safe line of held chord tones, so the tool never outputs something that sounds wrong.
