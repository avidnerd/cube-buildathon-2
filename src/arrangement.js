// Keeps derived parts in step with the melody. A counter-melody is written for
// one exact melody, key and meter; if any of those change (tempo correction,
// note edits, a new key), each counter is rewritten in the same voice.
import { requestCounterMelody } from './counterMelody.js';
import { notesFromSeconds } from './noteModel.js';

export function basisOf(project) {
  const melody = project.tracks.find(t => t.role === 'melody');
  return JSON.stringify([project.key, project.timeSignature, melody?.notes.map(n => [n.pitch, n.start, n.duration])]);
}

export const staleCounters = project => project.tracks.filter(t => t.role === 'counter' && t.basis !== basisOf(project));

/** Rewrite every stale counter-melody. Returns the updated tracks (or throws). */
export async function refreshCounters(project) {
  const melody = project.tracks.find(t => t.role === 'melody');
  const basis = basisOf(project);
  return Promise.all(project.tracks.map(async t => {
    if (t.role !== 'counter' || t.basis === basis) return t;
    const result = await requestCounterMelody(melody.notes, { tempo: project.tempo, timeSignature: project.timeSignature, key: project.key, voice: t.voice });
    return { ...t, notes: result.notes, style: result.style, chords: result.chords, fallback: result.fallback, basis };
  }));
}

/** Apply settings changes. A tempo correction re-reads the recorded rhythm
 * (as the original single-page app did) when the raw timing is available. */
export function applySettings(project, changes) {
  const next = { ...project, ...changes };
  if (changes.tempo && changes.tempo !== project.tempo)
    next.tracks = project.tracks.map(t => (t.role === 'melody' && t.recording ? { ...t, notes: notesFromSeconds(t.recording, changes.tempo) } : t));
  return next;
}
