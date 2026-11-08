// Lightweight melody-only estimates: beat grouping and enharmonic spelling
// are interpretations, not uniquely recoverable properties of a sound wave.
export const KEYS = ['C','G','D','A','E','B','F#','Db','Ab','Eb','Bb','F',
  'Am','Em','Bm','F#m','C#m','G#m','Ebm','Bbm','Fm','Cm','Gm','Dm'];
const NATURAL = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const LETTERS = 'CDEFGAB';
export function keyScale(key) {
  const tonic = (NATURAL[key[0]] + (key[1] === '#' ? 1 : key[1] === 'b' ? -1 : 0) + 12) % 12;
  const intervals = key.endsWith('m') ? [0,2,3,5,7,8,10] : [0,2,4,5,7,9,11];
  return intervals.map((interval, i) => {
    const letter = LETTERS[(LETTERS.indexOf(key[0]) + i) % 7];
    const pc = (tonic + interval) % 12;
    const alter = ((pc - NATURAL[letter] + 18) % 12) - 6;
    return { pc, letter, alter };
  });
}
export function spellPitch(midi, key = 'C', preference = 'auto') {
  let spelling = preference === 'auto' ? keyScale(key).find(p => p.pc === midi % 12) : null;
  if (!spelling) {
    const flats = preference === 'flats' || (preference === 'auto' && keyScale(key).some(p => p.alter < 0));
    const name = (flats ? ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B'] : ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'])[midi % 12];
    spelling = { letter: name[0], alter: name[1] === 'b' ? -1 : name[1] === '#' ? 1 : 0 };
  }
  return { ...spelling, octave: (midi - NATURAL[spelling.letter] - spelling.alter) / 12 - 1 };
}
export function analyzeMelody(notes) {
  if (!notes.length) return { bpm: 120, meter: '4/4', key: 'C', notice: 'Sing a melody to estimate its rhythm and key.' };
  const origin = notes[0].start;
  const intervals = notes.slice(1).map((n, i) => n.start - notes[i].start).filter(t => t > 0.1);
  // Prefer a quarter-note pulse matching common onset intervals, while allowing
  // eighths, sixteenths and held notes. The prior resolves half/double-time ties.
  const tempos = [];
  for (let bpm = 60; bpm <= 180; bpm++) {
    const beat = 60 / bpm;
    let score = 0;
    for (const interval of intervals) {
      const beats = interval / beat;
      const gridError = Math.abs(beats * 4 - Math.round(beats * 4));
      score += gridError ** 2 * 5 + Math.min(...[0.5,1,1.5,2,3,4].map(v => Math.abs(beats - v))) * 0.15;
      score += Math.abs(Math.log2(beats)) * 0.06;
    }
    for (const note of notes) {
      const beats = (note.start - origin) / beat;
      score += (beats * 4 - Math.round(beats * 4)) ** 2 * 0.3;
    }
    score += Math.abs(Math.log2(bpm / 110)) * 0.03;
    tempos.push({ bpm, score });
  }
  tempos.sort((a,b) => a.score - b.score);
  const bpm = intervals.length >= 2 ? tempos[0].bpm : 120;
  const beat = 60 / bpm;
  // Compare simple/compound groupings using phrase length, sustained-note
  // accents and breaths. A pickup or rubato performance can defeat this model.
  const total = (notes.at(-1).start + notes.at(-1).duration - origin) / beat;
  const meters = [{ meter: '4/4', length: 4 }, { meter: '3/4', length: 3 }, { meter: '6/8', length: 3 }].map(candidate => {
    const remainder = total % candidate.length;
    let score = Math.min(remainder, candidate.length - remainder) * 0.25;
    for (let i = 0; i < notes.length; i++) {
      const position = (notes[i].start - origin) / beat;
      const subdivision = candidate.meter === '6/8' ? 1.5 : 1;
      const distance = Math.abs(position / subdivision - Math.round(position / subdivision));
      const weight = Math.min(2, notes[i].duration / beat);
      score += distance * weight * 0.15;
      if (i && notes[i].start - notes[i-1].start - notes[i-1].duration > beat * 0.35) {
        const phase = position % candidate.length;
        score += Math.min(phase, candidate.length - phase) * 0.3;
      }
    }
    return { ...candidate, score: score + (candidate.meter === '4/4' ? 0 : 0.05) };
  }).sort((a,b) => a.score - b.score);
  const histogram = Array(12).fill(0);
  notes.forEach(n => { histogram[n.midi % 12] += n.duration; });
  const duration = notes.reduce((sum,n) => sum + n.duration, 0);
  const rankedKeys = KEYS.map(key => {
    const scale = keyScale(key);
    const inside = scale.reduce((sum,p) => sum + histogram[p.pc], 0) / duration;
    const tonic = scale[0].pc;
    const score = inside * 5 + histogram[tonic] / duration * 0.8
      + (notes.at(-1).midi % 12 === tonic ? 0.35 : 0)
      + (notes[0].midi % 12 === tonic ? 0.1 : 0)
      - scale.filter(p => p.alter).length * 0.008;
    return { key, score };
  }).sort((a,b) => b.score - a.score);
  const distinct = new Set(notes.map(n => n.midi % 12)).size;
  return {
    bpm, meter: notes.length < 4 ? '4/4' : meters[0].meter, key: rankedKeys[0].key,
    notice: `${notes.length < 6 ? 'Short melody: ' : ''}Tempo and time signature are estimates; half/double tempo or another beat grouping may fit. ${distinct < 4 ? 'Few pitches make the key uncertain. ' : ''}Sharps/flats follow the estimated key. You can adjust all three below.`,
  };
}
