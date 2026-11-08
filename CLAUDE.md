# Harmony hackathon app

A web app for a cappella groups. A singer records a phrase, and the app transcribes it, suggests harmony lines, counter-melodies, and ornaments, shows them as a piano roll and sheet music, scores pitch accuracy, and lets the group share parts. This is a hackathon project, so a working demo beats polish.

Full feature spec, data model, and build order: @docs/SPEC.md

## Ground rules

- The note model in docs/SPEC.md is the single source of truth. Every feature reads from and writes to it. Don't create parallel representations of the music.
- Harmony lines, counter-melodies, and chord inference all use one shared search engine with different scoring weights. Add a weight preset rather than a new algorithm.
- Intervals are diatonic: move by scale degrees in the detected key, never by a fixed number of semitones.
- Reuse the one piano roll component for display, editing, and pitch feedback.
- Build in the order listed in docs/SPEC.md, and check off each step there once it works end to end.
- Don't add features beyond the spec without asking. Items under "Open decisions" in the spec need a team decision, so ask before choosing.

## Browser constraints

- Microphone access requires HTTPS (localhost is fine during development).
- Audio can't start until a user gesture, so call Tone.start() from a button handler.
- Practice mode assumes headphones. Without them, playback bleeds into the mic and confuses pitch detection.

## Commands

- `npm install` once (and `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt` for Python tests)
- `npm start`: the app (Vite) plus the Python counter-melody API (`counter_api.py`, port 8001) together
- `npm test`: JavaScript tests. `.venv/bin/python -m pytest -q`: Python tests
- `npm run build`: production build into `dist/`

## Code map

- `src/main.jsx`: app shell, hash routes (#record, #arrange, #parts, #practice), project state, shared playback
- `src/screens/`: one file per screen, built from the `design/*.html` mockups
- `src/ui/kit.jsx`: header, tab bar, the one piano roll, fader. `src/ui/ScoreSheet.jsx`: sheet music overlay
- `src/noteModel.js`, `src/project.js`: the docs/SPEC.md note model and project helpers
- `src/player.js` (Tone.js playback and WAV export), `src/useRecorder.js` (count-in, metronome, Basic Pitch), `src/mix.js` (learning mixes)
