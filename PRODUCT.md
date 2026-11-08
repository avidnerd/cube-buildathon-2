# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

Mobile web, designed iPhone-first and opened in Safari. Judges and group members reach it through a shared link or QR code.

## Stack

Undecided. The frontend framework, storage (Firebase or Supabase), transcription engine (Basic Pitch or CREPE), and hosting are open team decisions listed in docs/SPEC.md. Fixed parts of the stack: Tone.js for playback, OpenSheetMusicDisplay for notation, pitchy for live pitch, and a Python/music21 backend.

## Users

Primary: the arranger or leader of an a cappella group. They record a melody, choose harmony lines and counter-melodies, adjust notes, and assign parts to members.

Secondary: group members who open a shared project to learn and practice their assigned part, usually with headphones.

## Product Purpose

Turn one sung phrase into a learnable multi-part arrangement. A singer records a phrase, and the app transcribes it into notes, suggests harmony lines, counter-melodies, and ornaments, shows them as a piano roll and sheet music, scores pitch accuracy, and lets the group share parts. Success means a leader can go from a recorded phrase to parts the group can rehearse in one sitting.

## Positioning

The app starts from the group's own voice, not a backing track or a catalog song. It writes harmonies diatonically in the detected key, keeps each part inside its assigned singer's range, and offers several distinct named harmony options (parallel 3rds, 6ths, chord-tone, drone, contrary motion) instead of one answer.

## Operating Context

- Rehearsal rooms and homes. Practice mode assumes headphones, because playback bleeding into the mic confuses pitch detection.
- Recording uses a count-in and metronome at a chosen tempo.
- Groups learn from standard choir learning-track mixes: solo, predominant, and missing.
- Demo setting: a loud hackathon venue, a headset mic, and judges opening the shared project on their phones from a QR code.

## Capabilities and Constraints

- One note model is the single source of truth. Piano roll, sheet music, playback, sharing, and pitch feedback are all views of it.
- One piano roll component handles display, editing (drag a note to lock it and re-solve), and pitch feedback.
- Features, in build order: recording and transcription with piano roll editing; harmony option cards; sheet music; mixer and sharing; real-time pitch feedback; counter-melody presets (Pad, Echo, Weave, Descant); ornament suggestions.
- The mic requires HTTPS, and audio can only start after a user gesture.
- Terminology: track, part, role (melody, harmony, counter), member range, locked note, option card, mix.

## Brand Commitments

- Name: **4-Track** (replaces the working name "Harmony"). It nods to the home 4-track cassette recorder, and maps to the four parts of an a cappella arrangement.
- Look (user-pinned, 2026-11-08): retro cassette players and 8-bit pixel style. Earlier steers toward a gospel hymn-board look ("too tacky") and ffern.co-style pastels were superseded by this one.
- No logo yet.

## Evidence on Hand

None yet. There are no user recordings, testimonials, or demo projects. A preloaded demo project is planned as a backup. Mockups must label any sample music, names, and scores as sample data.

## Product Principles

- The singer's own voice comes first. Every screen starts from what the group sang.
- Show options, not a single answer. Give each one an audible preview and an honest difficulty rating.
- Fit the people. Parts respect each member's recorded range.
- Music reads as music. Notes, intervals, and parts are shown in forms singers already read.
- The demo must work live. Core flows have to hold up in a noisy room on a phone.
