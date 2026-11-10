// Karaoke lines from the note model. Every part sings the melody's words at the
// melody's moments, so all parts share these lines.

const HOLD = '~'; // the engine's marker for "keep singing the previous syllable"
const MAX_CHARS = 42;
const GAP_BEATS = 1.5;
const endsPhrase = text => /[.,!?;]$/.test(text.replace(/-$/, ''));
const wordStart = n => n.wordStart ?? n.raw?.word_start ?? false;

export function karaokeLines(notes) {
  const lines = [];
  let line = null;
  let chars = 0;
  notes.forEach((n, index) => {
    const end = n.start + n.duration;
    const lyric = n.lyric || '';
    const last = line?.syllables.at(-1);
    if (line && (n.start - line.end >= GAP_BEATS || (wordStart(n) && lyric !== HOLD && last && (endsPhrase(last.raw) || chars >= MAX_CHARS)))) line = null;
    if (!line) { line = { start: n.start, end, syllables: [] }; chars = 0; lines.push(line); }
    line.end = end;
    if (lyric === HOLD && line.syllables.length) { line.syllables.at(-1).end = end; return; }
    if (!lyric || lyric === HOLD) return;
    const previous = line.syllables.at(-1);
    const joined = previous?.raw.endsWith('-');
    line.syllables.push({ text: lyric.replace(/-/g, ''), raw: lyric, space: !!previous && !joined, start: n.start, end, index });
    chars += lyric.length;
  });
  return lines;
}

/** The line to show at a beat: the one being sung, or the next one coming. */
export function lineIndexAt(lines, beat) {
  const i = lines.findIndex(l => beat < l.end);
  return i < 0 ? lines.length - 1 : i;
}

export const hasWords = lines => lines.some(l => l.syllables.length);

const NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
export const noteName = pitch => `${NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
