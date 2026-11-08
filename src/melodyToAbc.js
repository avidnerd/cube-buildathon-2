import { KEYS, spellPitch } from './analyzeMelody.js';
const LENGTHS = [16, 12, 8, 6, 4, 3, 2, 1];

function pitchToken(midi, key, spelling) {
  const { letter, alter, octave } = spellPitch(midi, key, spelling);
  const accidental = alter < 0 ? '_'.repeat(-alter) : alter > 0 ? '^'.repeat(alter) : '=';
  return accidental + (octave >= 5 ? letter.toLowerCase() : letter)
    + (octave > 5 ? "'".repeat(octave - 5) : ','.repeat(Math.max(0, 4 - octave)));
}

/** Convert monophonic {midi, start, duration} events (seconds) into ABC notation.
 * Rhythm is snapped to sixteenths; BPM is quarter notes per minute.
 * Returns {abc, warnings}. Does not mutate the supplied melody.
 */
export function melodyToAbc(notes, { bpm = 120, meter = '4/4', clef = 'treble', title = 'Singing melody', key = 'C', spelling = 'auto' } = {}) {
  if (!Array.isArray(notes) || notes.length === 0) throw new Error('Provide at least one melody note.');
  if (notes.length > 4096) throw new Error('Use at most 4096 notes per score.');
  if (!Number.isFinite(bpm) || bpm < 20 || bpm > 300) throw new Error('Tempo must be between 20 and 300 BPM.');
  if (!['3/4', '4/4', '6/8'].includes(meter)) throw new Error('Choose 3/4, 4/4, or 6/8 time.');
  if (!['treble', 'bass'].includes(clef)) throw new Error('Choose treble or bass clef.');
  if (!KEYS.includes(key)) throw new Error('Choose a supported major or minor key.');
  if (!['auto', 'sharps', 'flats'].includes(spelling)) throw new Error('Choose automatic, sharp, or flat spelling.');
  if (typeof title !== 'string') throw new Error('Title must be text.');
  const sorted = notes.map((note, index) => {
    if (!note || !Number.isInteger(note.midi) || note.midi < 0 || note.midi > 127)
      throw new Error(`Note ${index + 1}: MIDI pitch must be an integer from 0 to 127.`);
    if (!Number.isFinite(note.start) || note.start < 0 || !Number.isFinite(note.duration) || note.duration <= 0)
      throw new Error(`Note ${index + 1}: start must be nonnegative and duration must be positive (seconds).`);
    if (note.start + note.duration > 600) throw new Error('Use a melody no longer than 10 minutes.');
    return { ...note };
  }).sort((a, b) => a.start - b.start);
  const tickSeconds = 60 / bpm / 4;
  const warnings = new Set();
  let previousEnd = 0;
  const events = sorted.map((note, index) => {
    if (index && note.start < previousEnd - 1e-7)
      throw new Error('Notes overlap. Supply one sung pitch at a time.');
    previousEnd = note.start + note.duration;
    const start = Math.round(note.start / tickSeconds);
    const end = Math.round(previousEnd / tickSeconds);
    if (end <= start) throw new Error(`Note ${index + 1} is too short for the sixteenth-note grid at this tempo.`);
    if (Math.abs(start * tickSeconds - note.start) > 1e-7 || Math.abs(end * tickSeconds - previousEnd) > 1e-7)
      warnings.add('Timing was rounded to the nearest sixteenth note.');
    return { midi: note.midi, start, end };
  });
  const barTicks = meter === '4/4' ? 16 : 12;
  const tokens = [];
  let cursor = 0;
  let bars = 0;
  function emit(pitch, duration) {
    while (duration > 0) {
      const available = Math.min(duration, barTicks - cursor % barTicks);
      const length = LENGTHS.find(value => value <= available);
      duration -= length;
      tokens.push(`${pitch}${length === 1 ? '' : length}${pitch !== 'z' && duration ? '-' : ''}`);
      cursor += length;
      if (cursor % barTicks === 0) {
        tokens.push('|');
        if (++bars % 4 === 0) tokens.push('\n');
      }
    }
  }
  for (const note of events) {
    emit('z', note.start - cursor);
    emit(pitchToken(note.midi, key, spelling), note.end - note.start);
  }
  // Complete the final measure with visible rests.
  if (cursor % barTicks) emit('z', barTicks - cursor % barTicks);
  const body = tokens.join(' ').trim().replace(/\|$/, '|]');
  const safeTitle = title.replace(/[\r\n\x00-\x1f]/g, ' ').replace(/%/g, '').slice(0, 100).trim() || 'Singing melody';
  return { abc: `X:1\nT:${safeTitle}\nM:${meter}\nL:1/16\nQ:1/4=${bpm}\nK:${key} clef=${clef}\n${body}\n`, warnings: [...warnings] };
}
