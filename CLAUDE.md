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

Not set up yet. When you scaffold the project, add the dev, test, and build commands here.
