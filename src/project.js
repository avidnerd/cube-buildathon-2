// The project document from docs/SPEC.md, plus small helpers the screens share.
import { notesEnd } from './noteModel.js';

export const TRACK_COLORS = ['var(--t1)', 'var(--t2)', 'var(--t3)', 'var(--t4)'];
export const TRACK_COUNT = 4;
const STORAGE_KEY = '4track.project.v1';

export function emptyProject() {
  return {
    title: 'Untitled tape',
    key: null,             // "G major" once a melody is recorded
    tempo: 92,
    timeSignature: '4/4',
    members: [],
    tracks: [],            // see makeTrack()
    spelling: 'auto',      // sheet music: 'auto' (follow key) | 'sharps' | 'flats'
    melodyClef: 'auto',    // sheet music clef for the melody: 'auto' | 'treble' | 'bass'
    notice: '',            // what was estimated about the last take (shown until reviewed)
  };
}

export function makeTrack({ id, name, role, notes, assignedTo = null, voice = null, audioUrl = null }) {
  return { id, name, role, assignedTo, audioUrl, notes, voice };
}

export function loadProject() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && Array.isArray(saved.tracks)) return { ...emptyProject(), ...saved };
  } catch { /* storage unavailable or corrupt: start fresh */ }
  return emptyProject();
}

export function saveProject(project) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(project)); } catch { /* private mode */ }
}

export const beatsPerBar = timeSignature => (timeSignature === '4/4' ? 4 : timeSignature === '3/4' ? 3 : 3);

/** Length of the arrangement in beats, rounded up to whole bars (min one bar). */
export function projectBeats(project) {
  const bar = beatsPerBar(project.timeSignature);
  const end = Math.max(0, ...project.tracks.map(t => notesEnd(t.notes)));
  return Math.max(bar, Math.ceil(end / bar - 1e-6) * bar);
}

/** "G major" <-> "G", "E minor" <-> "Em" (the names src/analyzeMelody.js uses). */
export const keyToSpec = key => (key.endsWith('m') ? `${key.slice(0, -1)} minor` : `${key} major`);
export const keyFromSpec = spec => (spec?.endsWith(' minor') ? `${spec.slice(0, -6)}m` : spec?.replace(/ major$/, '') || 'C');

/** Clef from the range of a part: bass if low, octave-treble for tenor range, else treble. */
export function clefFor(notes) {
  const sorted = notes.map(n => n.pitch).sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)] ?? 64;
  return median < 50 ? 'bass' : median < 57 ? 'treble-8' : 'treble';
}

/** "01.3" (bar.beat), as on the tape counter. */
export function counterText(beat, timeSignature) {
  const bar = beatsPerBar(timeSignature);
  const b = Math.max(0, beat);
  return `${String(Math.floor(b / bar) + 1).padStart(2, '0')}.${Math.floor(b % bar) + 1}`;
}

export const capitalize = s => s.charAt(0).toUpperCase() + s.slice(1);
