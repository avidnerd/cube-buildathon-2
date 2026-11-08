# Spec: Harmony hackathon app

## Overview

A singer records a short phrase. The app transcribes it into notes, then suggests harmony lines, counter-melodies, and ornaments that the group can learn, practice, and share. All analysis runs on recorded phrases (non-live). Only the pitch-feedback view tracks the singer in real time.

## Shared foundation

### Note model (single source of truth)

Every part is a list of notes. Sheet music, playback, sharing, and pitch feedback are all views of this data.

```json
{
  "key": "G major",
  "tempo": 92,
  "timeSignature": "4/4",
  "members": [{ "name": "Maya", "low": 55, "high": 74 }],
  "tracks": [
    {
      "id": "alto-1",
      "name": "Alto harmony",
      "role": "harmony",
      "assignedTo": "Maya",
      "audioUrl": null,
      "notes": [
        { "pitch": 67, "start": 0, "duration": 1.5, "locked": false, "ornaments": ["vibrato"], "lyric": null }
      ]
    }
  ]
}
```

- `pitch`, `low`, and `high` are MIDI numbers. `start` and `duration` are in beats.
- `role` is `melody`, `harmony`, or `counter`.
- `audioUrl` is set only for tracks with a real recording (the original melody, or a friend's recorded part).
- `locked` notes are hard constraints for the search engine.
- `members` holds each singer's range from the range check.

### Recording and cleanup

- Record with a count-in and metronome at a user-chosen tempo, so the beat grid is known.
- Transcribe to notes with Basic Pitch or CREPE (open decision).
- Clean up: smooth the pitch curve, fix octave jumps, merge fragments caused by vibrato or scoops, drop low-confidence notes, and enforce a minimum note length.
- Users fix remaining errors by dragging notes in the piano roll before any other feature runs.
- Detect the key with music21.

### One search engine

Harmony lines, counter-melodies, and chord inference are the same dynamic-programming (Viterbi-style) k-best search with different candidates and scoring weights. New behaviors are new weight presets, not new algorithms.

### One piano roll component

Used for showing harmony options, editing notes, and the pitch-feedback view.

## Feature 1: Harmony options

### Candidates

For each melody note, consider diatonic 3rds, 4ths, 5ths, 6ths, and octaves, above and below, plus tones of the current chord. Exclude 2nds and 7ths except as short passing notes on weak beats.

### Scoring

- Vertical: consonance with the melody note and the current chord.
- Horizontal: singability. Reward steps and penalize large leaps.
- Rules: no parallel 5ths or octaves (unless the style preset allows them), no crossing the melody, and stay within the assigned member's range. music21's voiceLeading module can check these.

### Search

- Find the best-scoring whole line, not the best note at each step. The best line may change interval mid-phrase.
- Use k-best search to return several distinct options.
- Locked notes are hard constraints: every other candidate at that time step gets infinite cost, and the rest of the line re-solves around it.

### Option cards

Each card shows a label, a short description, a play button (plays the line with the melody), a difficulty rating (from leaps and interval changes), and which members' ranges it fits.

- Parallel 3rds: warm, the classic pop and country sound.
- Parallel 6ths: sweeter and more spacious.
- 4ths and 5ths: open and hollow, with a folk or medieval feel.
- Chord-tone: the interval follows the chords. Richest, but hardest to sing.
- Pedal/drone: one held note while the melody moves. Easiest.
- Contrary motion: moves opposite to the melody.

### Building an arrangement

- Users add lines to a stack one at a time. Each new line is checked against the lines already chosen, not just the melody.
- Dragging a note to a new pitch locks it and re-solves the line.
- Transpose to fit: each member sings a scale to record their range, and one button shifts the whole arrangement so every part fits its assigned member.

### Chord inference (internal, not user-facing)

- Harmony and counter-melody depend on the implied chords, and a lone melody can fit several progressions.
- Per beat or bar, score each diatonic chord by how many melody notes are chord tones, weighted by duration and beat strength.
- Run the shared search with transition scores that favor common progressions.
- Optional: a bright vs. moody toggle that weights major vs. minor chords.

### 1.1 and 1.2: Sharing

Mixes (the standard learning-track mixes choirs and barbershop groups use):

- Solo: only your part.
- Predominant: your part loud, everyone else soft.
- Missing: everything except your part.

Shared project page:

- Opens with an "I'm singing..." picker that applies a mix.
- A mixer with volume, mute, and solo for each track.
- Each listener's mix is saved locally and never changes what others hear.

Audio:

- Play generated parts through a Tone.js Sampler loaded with "ooh" or "aah" vocal samples.
- Stretch: pitch-shift the singer's own recording into harmonies. This needs formant preservation (for example, Rubber Band) to avoid sounding robotic.

Mechanics:

- Store projects in Firebase or Supabase (open decision) and share them by a link containing the project ID.
- Single-part audio: render with Tone.Offline, encode as WAV, and share through the Web Share API (native share sheet on phones), with a download fallback.
- Stretch: friends record their own part into the shared project (an asynchronous virtual choir). This requires the latency calibration from 1.5.

### 1.3: Sheet music

- Per part: build a music21 stream, quantize it, run makeNotation (measures, ties, beams), export MusicXML, and render it with OpenSheetMusicDisplay (OSMD).
- Choose the clef from the range: treble, bass, or octave treble for tenors.
- Let users choose the quantize grid: 8ths (clean) or 16ths (detailed).
- During playback, drive OSMD's cursor from the playback clock to highlight the current note.
- Two views: full score, and "my part only" (also the 1.1 share view).
- Export MusicXML and PDF.
- Stretch: typed lyrics split into syllables and assigned one per note, with manual fixes for melismas.

### 1.4: Counter-melody

- Core principle: rhythmic complementarity. Move when the melody holds or rests, and hold when it's busy.
- Chord tones on strong beats, stepwise passing notes on weak beats, mostly contrary motion, no parallel 5ths or octaves, and no unisons with the melody.
- Implemented as weight presets on the shared search engine:
  - Pad: sustained chord tones on "ooh."
  - Echo: repeats the tail of each melody phrase in the rest that follows.
  - Weave: a fully independent line.
  - Descant: a soaring line above the melody.
- A busyness slider controls note density.

### 1.5: Pitch accuracy feedback

- Targets are precomputed. Only the singer's pitch is tracked live, using pitchy (pitch and clarity per frame). Ignore low-clarity frames and smooth the rest.
- View: target notes as bars scrolling past a fixed playhead, with the sung pitch drawn as a line colored green, yellow, or red by how many cents off it is.
- Tolerance levels: ±50 cents (beginner), ±25 (intermediate), ±10 (advanced).
- Require headphones.
- Latency calibration (a clap test) so the pitch line lines up with the targets.
- Scoring skips roughly the first 100 ms of each note to forgive scoops.
- After a take, report habits: flat on long notes, sharp on high notes, drifting over the take.
- Loop a section and slow it down. Parts are notes, so slowing down is just a tempo change.

## Feature 2: Riffs, trills, and accents

### Where to suggest what

- Long held notes: vibrato, a trill, a turn, or a volume swell.
- Phrase endings followed by a rest: a run into the final note, or a fall-off after it.
- Upward leaps of a 4th or more: a scoop or slide into the top note.
- Stepwise approach to a strong beat: a grace note.
- Highest note of a phrase: an accent, with a crescendo leading in.
- Final note of the song: a fermata and a big finish.

### Generating runs

- Inputs: the target note, the time available before it, and the style.
- Scale by style: major pentatonic for pop, minor pentatonic or blues for R&B and gospel.
- Build a mostly descending line that starts above the target and resolves onto it.
- Fit the note count to the available time at a singable speed, and stay inside the singer's range.

### Difficulty and style

- Easy: a grace note or 3-note turn. Medium: a 5–7 note run. Hard: a fast run with blue notes.
- Style presets: classical (trills, turns), R&B and gospel (runs), jazz (scoops, falls), pop (slides, light runs).

### UI

- Suggestion icons appear on the piano roll. Tapping one plays the ornament with one bar of context before and after it.
- Users accept or dismiss each suggestion. Accepted ornaments are stored in the note's `ornaments` field and appear in the sheet music as MusicXML markings (trill, turn, accent, grace notes, fermata, breath mark).
- Playback: a trill rapidly alternates the note with the one above it, vibrato uses the Tone.js Vibrato effect, and slides use portamento.

### Learn-this-riff mode

Play the riff at 50% speed while the singer copies it with pitch feedback scoring each note, then step up to 75% and 100% as they succeed.

### Extras

Suggest breath marks and dynamics (where to swell and where to soften) from the same phrase analysis.

## Tech stack

- Frontend: a web app (framework is an open decision). Web Audio API and getUserMedia for the mic, Tone.js for playback and offline rendering, OpenSheetMusicDisplay for notation, and pitchy for real-time pitch detection.
- Backend: Python (for example, FastAPI) with Basic Pitch or CREPE for transcription, and music21 for key detection, quantization, voice-leading checks, and MusicXML export.
- Storage: Firebase or Supabase.
- Hosting must serve HTTPS.

## Build order

Check off each step once it works end to end.

- [ ] 1. Recording (count-in and metronome), transcription, cleanup, and the piano roll with editing
- [ ] 2. Harmony options with playback
- [ ] 3. Sheet music
- [ ] 4. Mixer and sharing
- [ ] 5. Pitch feedback
- [ ] 6. Counter-melody
- [ ] 7. Ornaments

Stretch goals: friends recording into shared projects, pitch-shifted own-voice harmonies, lyrics, and the bright vs. moody toggle.

## Demo plan

- Show a QR code so judges can open the shared project on their phones and mute or solo parts while the group sings.
- Use a headset mic, since venues are loud.
- Keep a preloaded demo project as a backup in case live recording fails.

## Open decisions

Ask the team before choosing any of these:

- Frontend framework
- Firebase or Supabase
- Basic Pitch or CREPE for transcription
- Hosting platform
