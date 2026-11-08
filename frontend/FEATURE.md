# Melody to sheet music

A standalone React feature and local demo for a single singing voice. Sing or hum into your microphone, then stop to generate sheet music. Audio is analyzed locally in the browser; no backend, API key, or audio upload is used. The timed-note converter is also available separately for team integration.

## Run and test locally

Requires Node.js 22.12+ (or a newer supported release).

```sh
npm install
npm run dev
```

Open the local URL printed by Vite (normally http://127.0.0.1:5173). Click **Start singing**, allow microphone access, sing or hum, and click **Stop & notate**. The score appears after stopping. Recordings stop after 60 seconds or when the tab is hidden. You can also load an example or edit notes under Advanced. Use **Print / Save PDF** to open the browser print dialog, or **Download ABC** to save the notation source.

```sh
npm test
npm run test:integration
npm run build
```

Manual checks: sing three sustained notes in a quiet room, stop, and check that their pitches and relative durations appear. Check microphone denial, cancellation, silence, stopping, and recording a second take. Verify the browser microphone indicator switches off after stopping. If the in-app browser does not support the microphone, open the local URL in Chrome or Safari. Then load the example and look for a G tied across the first bar, a rest, and an F-sharp followed by F-natural. Select bass clef or 3/4. Enter overlapping notes to check validation. Print to inspect the score-only layout. Download ABC and compare it with “View generated notation.”

## Team integration

```jsx
import { melodyToAbc } from './src/melodyToAbc.js';
import { SheetMusic } from './src/SheetMusic.jsx';

const melody = [
  { midi: 60, start: 0, duration: 0.5 },
  { midi: 62, start: 0.5, duration: 0.5 },
];
const { abc, warnings } = melodyToAbc(melody, {
  bpm: 120, meter: '4/4', clef: 'treble', title: 'My melody',
});
// Inside your React component:
return <SheetMusic abc={abc} />;
```

Catch validation errors at your input boundary. `midi` is an integer from 0–127 (60 = C4). `start` and `duration` are seconds relative to the melody start; gaps become rests. The detector must group pitch frames into note events before calling the converter. A frequency alone cannot provide a notated rhythm.

The converter is plain JavaScript and works separately from React. For Next.js, put the renderer behind a client component (`'use client'`). Install `abcjs` in the host app and bring over the converter and renderer; the Vite demo need not be integrated.

## First-version choices

- Tempo is estimated from raw note onsets (60–180 BPM), before quantization. The displayed tempo is quarter-note BPM, including in 6/8. Manual edits accept 20–300 BPM. Half/double-time interpretations remain ambiguous.
- Time signature is estimated among 4/4, 3/4 and 6/8 using phrase length, note emphasis and breaths. The first detected note is treated as the downbeat; pickups, rubato and short phrases can give incorrect estimates. Fewer than four notes default to 4/4.
- Key estimation compares duration-weighted scale coverage and starting/ending pitches across 24 major/natural-minor keys. Sharps/flats follow the selected key; manual key and spelling overrides are available. Relative major/minor, chromatic melodies and modulations are ambiguous. The microphone shows an input level while recording; notes are detected after stopping.
- Quantization to the nearest sixteenth-note boundary. The raw-note converter warns when it rounds timing and rejects zero-tick notes. The microphone path retains raw note timing for analysis and drops notes that collapse to zero ticks at the estimated tempo. The converter then quantizes for notation. Tempo and meter overrides let you correct an estimate.
- One voice, no overlapping notes, chords, triplets, or lyrics. Spotify Basic Pitch detects note events after recording. The adapter keeps pitches C2–C6 and selects the highest-confidence detection where notes overlap to produce a single vocal line. This is not accompaniment separation. Leading silence is trimmed. Short internal breaths (up to 250 ms) extend the preceding note to the next onset, avoiding tiny rests; longer pauses remain rests. This happens before rhythm/key estimation. Repeated notes remain separate after a breath, and trailing silence does not extend the final note. Intentional short rests may also be smoothed; use Advanced to restore them when needed. Notes shorter than about 120 ms are discarded. Repeated pitches need a short breath to separate them. Strong vibrato, slides, background music, and noisy recordings can produce mistakes; this is an editable first draft, not professional transcription.
- Major/minor key signatures, key-aware diatonic spelling, explicit flats/sharps/naturals, and spelling overrides. Pitch is preserved across enharmonic changes.
- Gaps and the unfinished final bar are filled with rests. Long notes split into tied standard/dotted lengths across bar lines. Complex syncopation may need editorial cleanup.
- Up to 4096 notes and 10 minutes per score.
- Rendering uses bundled abcjs; optional Google Fonts fall back to system fonts offline.

## Reference

[J4Joshua/JASS-APP](https://github.com/J4Joshua/JASS-APP) uses a React/Next.js frontend and a Python MIDI/WebSocket backend. Its MIDI pitch representation informed this integration boundary. This implementation is original and does not copy its source or add its chord/recommendation services. Sheet music is rendered with [abcjs](https://docs.abcjs.net/).

No commit or push is performed by the demo. Review this feature with your team before publishing it. The pre-existing deletion of README.md has been left untouched; this guide lives separately to preserve that local change.

## Validation

`npm test` covers notation, musical estimates, and Basic Pitch event adaptation (overlaps, breaths, repeats and invalid detections). `npm run test:integration` loads the real bundled Spotify model and checks generated A4 audio through to notation, plus silence rejection. These tests do not establish real-world singing accuracy; test your own microphone and voice before pushing.

Automatic-analysis tests cover steady tempos with small onset deviations, representative simple/compound phrases, major/minor scale fixtures, flat/sharp spelling and pitch preservation across keys. These deterministic fixtures validate the heuristic implementation, not its accuracy on arbitrary performances.

## Spotify Basic Pitch integration

The app uses `@spotify/basic-pitch` 1.0.1 and TensorFlow.js 3.21.0. MediaRecorder captures audio, Web Audio decodes/resamples it to mono 22050 Hz, and a dedicated worker runs Basic Pitch on the CPU. The worker is terminated after each take or cancellation, releasing model memory. Processing can take a while on slower devices; the UI stays responsive and offers cancellation. No Spotify account or API key is needed.

`predev` and `prebuild` copy the model and Apache-2.0 license from the pinned npm package into `public/models/basic-pitch/`. These generated files are ignored by Git and included in the production build. Deploy all of `dist`, including the models directory. Audio and inference remain local.

Basic Pitch replaces pitch detection and note grouping, not the existing tempo/meter/key heuristics. Those estimates remain editable. The previous custom detector is no longer part of the recording flow.

Source and license: [Spotify Basic Pitch](https://github.com/spotify/basic-pitch-ts), Copyright 2022 Spotify AB, Apache-2.0. The license is copied alongside the model.

Browser integration check: with the dev server running, open `/tests/browser-basic-pitch.html` and press **Run synthetic recording check**. This generates A4 without microphone access, records and decodes it using browser APIs, resamples it, and runs the real worker/model. A passing result contains MIDI 69.
