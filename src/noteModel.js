/** The note model from docs/SPEC.md, the single source of truth:
 *
 *   { pitch: 67, start: 0, duration: 1.5, locked: false, ornaments: [], lyric: null }
 *
 * `pitch` is a MIDI number; `start` and `duration` are in BEATS.
 *
 * Two edges of the app still speak seconds: Basic Pitch (transcription) and
 * the ABC renderer (sheet music), which use `{ midi, start, duration }` in
 * seconds. Convert only at those edges, with the helpers below.
 */
const GRID = 4; // subdivisions per beat (sixteenths), the same grid melodyToAbc() uses
export const snapBeat = beats => Math.round(beats * GRID) / GRID;

export function makeNote(pitch, start, duration, extra = {}) {
  return { pitch, start, duration, locked: false, ornaments: [], lyric: null, ...extra };
}

/** Basic Pitch output (seconds) -> spec notes (beats), snapped to sixteenths. */
export function notesFromSeconds(events, bpm) {
  const perSecond = bpm / 60;
  const out = [];
  for (const e of [...events].sort((a, b) => a.start - b.start)) {
    let start = Math.max(0, snapBeat(e.start * perSecond));
    const end = snapBeat((e.start + e.duration) * perSecond);
    const previous = out.at(-1);
    if (previous) start = Math.max(start, previous.start + previous.duration);
    if (end > start) out.push(makeNote(e.midi, start, end - start));
  }
  return out;
}

/** Spec notes (beats) -> `{ midi, start, duration }` in seconds, for the ABC renderer. */
export function notesToSeconds(notes, bpm) {
  const perBeat = 60 / bpm;
  return notes.map(n => ({ midi: n.pitch, start: n.start * perBeat, duration: n.duration * perBeat }));
}

export const notesEnd = notes => notes.reduce((end, n) => Math.max(end, n.start + n.duration), 0);

/** Parse and check the editor's JSON. Returns spec notes or throws a readable error. */
export function parseNoteEdits(text, previous = []) {
  let raw;
  try { raw = JSON.parse(text); } catch { throw new Error('Enter valid JSON: a list like [{"pitch": 60, "start": 0, "duration": 1}].'); }
  if (!Array.isArray(raw) || !raw.length) throw new Error('Keep at least one note.');
  const notes = raw.map((n, i) => {
    if (!n || !Number.isInteger(n.pitch) || n.pitch < 0 || n.pitch > 127) throw new Error(`Note ${i + 1}: pitch must be a whole MIDI number from 0 to 127 (60 = middle C).`);
    if (!Number.isFinite(n.start) || n.start < 0 || !Number.isFinite(n.duration) || n.duration <= 0) throw new Error(`Note ${i + 1}: start must be 0 or more and duration above 0 (in beats).`);
    const old = previous.find(p => p.start === n.start && p.pitch === n.pitch);
    return { ...(old || makeNote(n.pitch, n.start, n.duration)), pitch: n.pitch, start: n.start, duration: n.duration };
  }).sort((a, b) => a.start - b.start);
  for (let i = 1; i < notes.length; i++)
    if (notes[i].start < notes[i - 1].start + notes[i - 1].duration - 1e-9) throw new Error(`Notes ${i} and ${i + 1} overlap. The melody is one voice, one note at a time.`);
  return notes;
}
