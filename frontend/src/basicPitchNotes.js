/** Adapt polyphonic Basic Pitch output to a single singing voice.
 * Where detections overlap, keep the highest-confidence event for that interval.
 * This is a melody heuristic, not source separation for accompanied recordings.
 * By default times are shifted so the first note starts at 0. Pass
 * { keepOrigin: true } to keep times relative to the start of the recording
 * (used when a count-in fixes the beat grid).
 */
export function basicPitchNotesToMelody(events, duration, { keepOrigin = false } = {}) {
  const notes = events.filter(n => Number.isInteger(n.pitchMidi) && n.pitchMidi >= 36 && n.pitchMidi <= 84
    && Number.isFinite(n.startTimeSeconds) && Number.isFinite(n.durationSeconds)
    && Number.isFinite(n.amplitude) && n.durationSeconds >= 0.12)
    .map((n, id) => ({ id, midi: n.pitchMidi, start: Math.max(0, n.startTimeSeconds),
      end: Math.min(duration, n.startTimeSeconds + n.durationSeconds), confidence: n.amplitude }))
    .filter(n => n.end > n.start);
  const boundaries = [...new Set(notes.flatMap(n => [n.start, n.end]))].sort((a,b) => a-b);
  const segments = [];
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i], end = boundaries[i+1];
    const winner = notes.filter(n => n.start <= start && n.end >= end)
      .sort((a,b) => b.confidence - a.confidence || a.id - b.id)[0];
    if (!winner) continue;
    const previous = segments.at(-1);
    if (previous?.id === winner.id && Math.abs(previous.end - start) < 1e-7) previous.end = end;
    else segments.push({ ...winner, start, end });
  }
  const stable = segments.filter(n => n.end - n.start >= 0.12);
  for (let i = 0; i < stable.length - 1; i++) {
    const gap = stable[i+1].start - stable[i].end;
    if (gap > 0 && gap <= 0.25 + 1e-7) stable[i].end = stable[i+1].start;
  }
  const origin = keepOrigin ? 0 : stable[0]?.start ?? 0;
  return stable.map(n => ({ midi: n.midi, start: n.start - origin, duration: n.end - n.start }));
}
