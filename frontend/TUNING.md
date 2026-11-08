# Tuning the counter-melody

All soft-rule weights live in one dict, `WEIGHTS`, at the top of `counter.py`.
The search **minimises** total cost, so a **positive** weight is a penalty and a **negative** weight is a bonus.

Hard rules (strong-beat dissonance, parallel 5ths/8ves, voice crossing longer than a beat, leaps over an octave, augmented or diminished leaps, out of range) all cost `hard` (100 000). After the search, a separate validator (`hard_violations`) checks the chosen line again. You can't tune a hard rule away. Only the soft rules below are adjustable.

After any change, run `python -m pytest -q`. Then listen to `out/<name>_both.mid` (made with `python counter.py samples/<name>.ly --midi`).

## What each weight does

### Motion against the melody (scored where the counter moves)
| weight | default | effect |
|---|---|---|
| `contrary` | -3.0 | Bonus when the counter moves opposite to the melody. This is the core of "weaving around" the tune. |
| `oblique` | -1.5 | Bonus when one voice moves while the other holds, which suits complementary rhythm. |
| `similar` | 2.0 | Cost when both voices move the same way. |
| `hidden_perfect` | 6.0 | Cost for similar motion into a 5th or octave when the counter leaps (a "hidden" or "direct" 5th or 8ve). |
| `parallel_imperfect` | 6.0 | Cost for the 3rd parallel 3rd/6th in a row, and for each one after that. This is the anti-"parallel harmony" rule. |

### Harmony and vertical intervals
| weight | default | effect |
|---|---|---|
| `nct_strong` | 14.0 | Counter note outside the chord on a strong beat. |
| `nct_weak` | 2.0 | Small cost for a non-chord tone on a weak beat. The note also gets flagged for the next rule. |
| `nct_unresolved` | 16.0 | A flagged weak-beat note that isn't a passing or neighbour tone (that is, not approached and left by step). |
| `weak_dissonance` | 4.0 | Counter *attacks* a 2nd, 4th, 7th or tritone on a weak beat. |
| `melody_dissonance` | 2.0 | The melody moves onto a dissonance against a held counter note (a melodic passing tone). |
| `doubling` | 5.0 | Counter on the melody's pitch class (an octave) on a strong beat, which thins the sound. |
| `unison_weak` | 30.0 | Counter on the exact same pitch as the melody (only the final note may be a unison). |
| `crossing` | 25.0 | Per beat spent on the wrong side of the melody. Crossing for more than a beat is a hard rule. |

### Shape of the line
| weight | default | effect |
|---|---|---|
| `step` | -1.5 | Bonus for stepwise motion. This is the biggest driver of "singable". |
| `repeat` | 1.0 | Cost for a repeated note. |
| `repeat3` | 10.0 | Cost for the same pitch 3 or more times in a row. |
| `leap` | 3.0 | Cost for a leap bigger than a 4th. |
| `leap_size` | 0.6 | Extra cost per semitone above a 4th. |
| `leap_no_recovery` | 6.0 | A leap of a 4th or more that isn't followed by a step back the other way. |
| `seventh_leap` | 30.0 | Leap of a 7th, which is hard to sing. |
| `oscillation` | 3.0 | Returning straight to the previous note (A-B-A zigzag). |
| `drift` | 1.2 | Pull towards a comfortable centre: halfway between the voice's middle and a 5th from the melody. |
| `range_edge` | 3.0 | Per beat in the top or bottom 2 semitones of the voice range. |
| `cadence_root` / `cadence_third` / `cadence_other` | -12 / -7 / +12 | Final note on the tonic, on the 3rd of I, or on anything else. |
| `rest` | 150.0 | The counter may rest instead of singing. This is an escape hatch that guarantees a solution always exists. |

### Chord inference
| weight | default | effect |
|---|---|---|
| `chord_strong_mult` | 2.0 | Melody notes on strong beats count this many times more when fitting chords. |
| `chord_nonchord` | 0.35 | Penalty for melody notes outside a candidate chord. |
| `chord_root` | 0.07 | Bonus when the chord's root appears in the melody. |
| `chord_split_gain` | 0.25 | How much better two half-bar chords must fit before a bar is split. Lower it for faster harmonic rhythm. |
| `chord_progression` / `chord_authentic` | 0.08 / 0.15 | Bonuses for I-IV, IV-V, ii-V, vi-IV and so on, and for V(7)-I. |
| `chord_first_tonic` / `chord_final_tonic` / `chord_phrase_end` | 0.15 / 0.4 / 0.1 | Start on I, end on I, and land phrase ends (every 4 bars) on I or V. |
| `chord_v7` | 0.1 | V7 must "earn" its 7th from the melody to beat a plain V. |
| `chord_same_empty` | 0.1 | Keep the same chord through bars where the melody rests. |

### Thresholds
| weight | default | effect |
|---|---|---|
| `style_busy_density` | 0.85 | Melody onsets per beat at or above which the style is **calm** (long notes). Below it the style is **active** (8ths plus a motif echo). |
| `quality_min` | 0.7 | Below this quality score, output the safe fallback (held chord tones). |
| `key_conf_min` | 0.6 | Below this Krumhansl correlation (when no `\key` is given), use the fallback. |
| `beam_width` | 50 | Width of the search. Wider is slower and rarely better. |

## Recipes

### "It's too busy"
1. Raise `style_busy_density` to around 0.6 so more melodies get the **calm** style. This is the biggest lever, because the rhythm plan decides how many notes there are.
2. Lower the `oblique` bonus (-1.5 → -0.5). Oblique motion is what rewards the counter for moving while the melody holds.
3. Raise `repeat3` and lower `repeat` (1.0 → 0) so held or repeated notes become cheaper than motion.
4. Raise `nct_weak` and `nct_unresolved` so fewer passing 8ths are worth it.

### "It's too boring / static"
1. Lower `style_busy_density` (for example to 1.1) so more melodies get the **active** style and the motif echo.
2. Make `step` more negative (-1.5 → -3) and raise `repeat` (1 → 3) and `repeat3` (10 → 20).
3. Raise `oscillation` (3 → 6) to stop it ping-ponging between two notes.
4. Lower `drift` (1.2 → 0.5) so the line is allowed to travel further through the range.
5. Lower `chord_split_gain` (0.25 → 0.1) for more chord changes, which give the line more targets.

### "It sounds like parallel harmony (just a 3rd under the tune)"
1. Raise `parallel_imperfect` (6 → 15). This directly punishes runs of parallel 3rds/6ths.
2. Make `contrary` more negative (-3 → -6) and raise `similar` (2 → 5).
3. Lower `style_busy_density` so more tunes get **active** style. The active rhythm puts the counter's onsets where the melody holds, and parallel motion needs both voices to move together.
4. Check the `% meta:` line. If it says `fallback=yes`, you're hearing held chord tones, not the search result. Look at why quality was low.
