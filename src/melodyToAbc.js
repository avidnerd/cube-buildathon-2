import { KEYS, keyScale, spellPitch } from './analyzeMelody.js';
const LENGTHS = [16, 12, 8, 6, 4, 3, 2, 1];
const PART_CLEFS = ['treble', 'treble-8', 'bass'];

const letterToken = ({ letter, octave }) => (octave >= 5 ? letter.toLowerCase() : letter)
  + (octave > 5 ? "'".repeat(octave - 5) : ','.repeat(Math.max(0, 4 - octave)));
const accidentalToken = alter => (alter < 0 ? '_'.repeat(-alter) : alter > 0 ? '^'.repeat(alter) : '=');

function validateOptions({ bpm, meter, key, spelling, title }) {
  if (!Number.isFinite(bpm) || bpm < 20 || bpm > 300) throw new Error('Tempo must be between 20 and 300 BPM.');
  if (!['3/4', '4/4', '6/8'].includes(meter)) throw new Error('Choose 3/4, 4/4, or 6/8 time.');
  if (!KEYS.includes(key)) throw new Error('Choose a supported major or minor key.');
  if (!['auto', 'sharps', 'flats'].includes(spelling)) throw new Error('Choose automatic, sharp, or flat spelling.');
  if (typeof title !== 'string') throw new Error('Title must be text.');
}

/** Validate one monophonic part (seconds) and snap it to sixteenth-note ticks. */
function toTickEvents(notes, tickSeconds, warnings) {
  if (!Array.isArray(notes) || notes.length === 0) throw new Error('Provide at least one melody note.');
  if (notes.length > 4096) throw new Error('Use at most 4096 notes per score.');
  const sorted = notes.map((note, index) => {
    if (!note || !Number.isInteger(note.midi) || note.midi < 0 || note.midi > 127)
      throw new Error(`Note ${index + 1}: MIDI pitch must be an integer from 0 to 127.`);
    if (!Number.isFinite(note.start) || note.start < 0 || !Number.isFinite(note.duration) || note.duration <= 0)
      throw new Error(`Note ${index + 1}: start must be nonnegative and duration must be positive (seconds).`);
    if (note.start + note.duration > 600) throw new Error('Use a melody no longer than 10 minutes.');
    return { ...note };
  }).sort((a, b) => a.start - b.start);
  let previousEnd = 0;
  return sorted.map((note, index) => {
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
}

/** ABC tokens for one voice, grouped into lines of four bars. Pads with rests to
 * `totalTicks` (rounded up to a full bar) so every voice has the same bar count. */
function voiceLines(events, barTicks, key, spelling, totalTicks) {
  const lines = [[]];
  let cursor = 0;
  let bars = 0;
  // Accidentals follow standard notation: write one only when the pitch differs
  // from the key signature, or from an earlier accidental on that line or space
  // in the same bar. Bar lines cancel accidentals.
  const signature = Object.fromEntries(keyScale(key).map(p => [p.letter, p.alter]));
  let inBar = {};
  function token(spelled) {
    const place = letterToken(spelled);
    const current = inBar[place] ?? signature[spelled.letter] ?? 0;
    inBar[place] = spelled.alter;
    return (spelled.alter === current ? '' : accidentalToken(spelled.alter)) + place;
  }
  function emit(spelled, duration) {
    while (duration > 0) {
      const available = Math.min(duration, barTicks - cursor % barTicks);
      const length = LENGTHS.find(value => value <= available);
      duration -= length;
      const pitch = spelled ? token(spelled) : 'z';
      lines.at(-1).push(`${pitch}${length === 1 ? '' : length}${spelled && duration ? '-' : ''}`);
      cursor += length;
      if (cursor % barTicks === 0) {
        inBar = {};
        lines.at(-1).push('|');
        if (++bars % 4 === 0) lines.push([]);
      }
    }
  }
  for (const note of events) {
    emit(null, note.start - cursor);
    emit(spellPitch(note.midi, key, spelling), note.end - note.start);
  }
  emit(null, totalTicks - cursor);
  // Complete the final measure with visible rests.
  if (cursor % barTicks) emit(null, barTicks - cursor % barTicks);
  if (!lines.at(-1).length) lines.pop();
  return lines;
}

const finish = text => text.trim().replace(/\|$/, '|]');
const cleanTitle = title => title.replace(/[\r\n\x00-\x1f]/g, ' ').replace(/%/g, '').slice(0, 100).trim() || 'Singing melody';
const cleanName = name => String(name).replace(/["\r\n\x00-\x1f%\\]/g, '').slice(0, 40);

/** Convert monophonic {midi, start, duration} events (seconds) into ABC notation.
 * Rhythm is snapped to sixteenths; BPM is quarter notes per minute.
 * Returns {abc, warnings}. Does not mutate the supplied melody.
 */
export function melodyToAbc(notes, { bpm = 120, meter = '4/4', clef = 'treble', title = 'Singing melody', key = 'C', spelling = 'auto' } = {}) {
  if (!Array.isArray(notes) || notes.length === 0) throw new Error('Provide at least one melody note.');
  validateOptions({ bpm, meter, key, spelling, title });
  if (!['treble', 'bass'].includes(clef)) throw new Error('Choose treble or bass clef.');
  const warnings = new Set();
  const events = toTickEvents(notes, 60 / bpm / 4, warnings);
  const barTicks = meter === '4/4' ? 16 : 12;
  const lines = voiceLines(events, barTicks, key, spelling, 0);
  const body = finish(lines.map(line => line.join(' ')).join(' \n '));
  return { abc: `X:1\nT:${cleanTitle(title)}\nM:${meter}\nL:1/16\nQ:1/4=${bpm}\nK:${key} clef=${clef}\n${body}\n`, warnings: [...warnings] };
}

/** Multi-staff score, e.g. melody + counter-melody, aligned bar by bar.
 * parts: [{ name, clef: 'treble' | 'treble-8' | 'bass', notes: [{midi, start, duration}] (seconds) }]
 * Each part must be monophonic. Returns {abc, warnings}.
 */
export function scoreToAbc(parts, { bpm = 120, meter = '4/4', title = 'Singing melody', key = 'C', spelling = 'auto' } = {}) {
  if (!Array.isArray(parts) || parts.length === 0) throw new Error('Provide at least one part.');
  if (parts.length > 8) throw new Error('Use at most 8 parts.');
  validateOptions({ bpm, meter, key, spelling, title });
  const warnings = new Set();
  const tickSeconds = 60 / bpm / 4;
  const barTicks = meter === '4/4' ? 16 : 12;
  const prepared = parts.map((part, index) => {
    if (!PART_CLEFS.includes(part?.clef)) throw new Error(`Part ${index + 1}: choose treble, treble-8, or bass clef.`);
    return { ...part, events: toTickEvents(part.notes, tickSeconds, warnings) };
  });
  const totalTicks = Math.max(...prepared.map(p => p.events.at(-1).end));
  const voices = prepared.map(p => voiceLines(p.events, barTicks, key, spelling, totalTicks));
  const ids = prepared.map((_, i) => `P${i + 1}`);
  const header = prepared.map((p, i) => `V:${ids[i]} clef=${p.clef} name="${cleanName(p.name ?? `Part ${i + 1}`)}"`).join('\n');
  const body = [];
  voices[0].forEach((_, line) => {
    voices.forEach((lines, v) => {
      const text = lines[line].join(' ');
      body.push(`[V:${ids[v]}] ${line === lines.length - 1 ? finish(text) : text}`);
    });
  });
  return {
    abc: `X:1\nT:${cleanTitle(title)}\nM:${meter}\nL:1/16\nQ:1/4=${bpm}\n%%score [${ids.join(' ')}]\n${header}\nK:${key}\n${body.join('\n')}\n`,
    warnings: [...warnings],
  };
}
