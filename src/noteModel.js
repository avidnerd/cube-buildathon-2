/** Shared note model used between features.
 *
 * Canonical format (what the backend and every feature exchange):
 *   { midi: 60, start: 0, duration: 1 }   // MIDI pitch; start/duration in quarter-note BEATS
 *
 * The recorder and sheet-music renderer work in SECONDS internally
 * (Basic Pitch reports seconds). Convert at the boundary with these helpers.
 * Beats are snapped to the same sixteenth-note grid melodyToAbc() uses, so a
 * melody looks identical in the score before and after a round trip.
 */
const GRID = 4; // subdivisions per beat (sixteenths)
const snap = beats => Math.round(beats * GRID) / GRID;

export function secondsToBeats(notes, bpm) {
  const perSecond = bpm / 60;
  return notes.flatMap(n => {
    const start = snap(n.start * perSecond);
    const end = snap((n.start + n.duration) * perSecond);
    return end > start ? [{ midi: n.midi, start, duration: end - start }] : [];
  });
}

export function beatsToSeconds(notes, bpm) {
  const perBeat = 60 / bpm;
  return notes.map(n => ({ midi: n.midi, start: n.start * perBeat, duration: n.duration * perBeat }));
}
