/** YIN-style normalized difference pitch estimator for a single voice. */
export function detectPitch(samples, sampleRate) {
  let energy = 0;
  for (const value of samples) energy += value * value;
  const rms = Math.sqrt(energy / samples.length);
  if (rms < 0.012) return { frequency: null, rms };
  const stride = Math.max(1, Math.floor(sampleRate / 16000));
  const data = new Float32Array(Math.floor(samples.length / stride));
  for (let i = 0; i < data.length; i++) {
    for (let j = 0; j < stride; j++) data[i] += samples[i * stride + j] / stride;
  }
  const rate = sampleRate / stride;
  const maxLag = Math.min(Math.floor(rate / 65), Math.floor(data.length / 2));
  const minLag = Math.floor(rate / 1100);
  const window = data.length - maxLag;
  const difference = new Float32Array(maxLag + 1);
  let sum = 0;
  for (let lag = 1; lag <= maxLag; lag++) {
    let value = 0;
    for (let i = 0; i < window; i++) value += (data[i] - data[i + lag]) ** 2;
    sum += value;
    difference[lag] = sum ? value * lag / sum : 1;
  }
  for (let lag = Math.max(2, minLag); lag < maxLag; lag++) {
    if (difference[lag] >= 0.15) continue;
    while (lag + 1 < maxLag && difference[lag + 1] < difference[lag]) lag++;
    const left = difference[lag - 1], center = difference[lag], right = difference[lag + 1];
    const denominator = left - 2 * center + right;
    const refined = lag + (denominator ? (left - right) / (2 * denominator) : 0);
    const frequency = rate / refined;
    return { frequency: frequency >= 65 && frequency <= 1100 ? frequency : null, rms };
  }
  return { frequency: null, rms };
}

export function frequencyToMidi(frequency) {
  return Math.round(69 + 12 * Math.log2(frequency / 440));
}
export function noteName(midi) {
  return ['C', 'C♯/D♭', 'D', 'D♯/E♭', 'E', 'F', 'F♯/G♭', 'G', 'G♯/A♭', 'A', 'A♯/B♭', 'B'][midi % 12] + (Math.floor(midi / 12) - 1);
}

/** Frame times are relative seconds. Trim leading silence, reject brief glitches,
 * absorb short breaths, and optionally snap boundaries to the score grid. */
export function framesToMelody(frames, endTime, bpm = null) {
  if (bpm !== null && (!Number.isFinite(bpm) || bpm < 20 || bpm > 300)) throw new Error('Choose a tempo between 20 and 300 BPM before recording.');
  const smoothed = frames.map((frame, i) => {
    if (frame.midi === null) return frame;
    const neighborhood = frames.slice(Math.max(0, i - 2), i + 3).map(f => f.midi);
    if (neighborhood.includes(null)) return frame;
    return { ...frame, midi: neighborhood.sort((a, b) => a - b)[Math.floor(neighborhood.length / 2)] };
  });
  const runs = [];
  for (let i = 0; i < smoothed.length; i++) {
    const frame = smoothed[i];
    const end = Math.min(smoothed[i + 1]?.time ?? endTime, frame.time + 0.08);
    const previous = runs.at(-1);
    if (previous && previous.midi === frame.midi && frame.time - previous.end < 0.001) previous.end = end;
    else runs.push({ midi: frame.midi, start: frame.time, end });
  }
  const stable = runs.filter(run => run.midi !== null && run.end - run.start >= 0.12);
  const merged = [];
  for (const run of stable) {
    const previous = merged.at(-1);
    if (previous && previous.midi === run.midi && run.start - previous.end <= 0.08) previous.end = run.end;
    else merged.push({ ...run });
  }
  // Notate the intended phrase, rather than every brief loss of voicing.
  // Extend the preceding note through breaths of up to 250 ms. Keep the next
  // onset fixed (including repeated pitches), and leave longer rests untouched.
  // Do this before rhythm/key estimation so breaths do not distort durations.
  for (let i = 0; i < merged.length - 1; i++) {
    const gap = merged[i + 1].start - merged[i].end;
    if (gap > 0 && gap <= 0.25 + 1e-7) merged[i].end = merged[i + 1].start;
  }
  const origin = merged[0]?.start ?? 0;
  if (bpm === null) return merged.map(run => ({ midi: run.midi, start: run.start - origin, duration: run.end - run.start }));
  const tick = 60 / bpm / 4;
  return merged.flatMap(run => {
    const start = Math.round((run.start - origin) / tick) * tick;
    const end = Math.round((run.end - origin) / tick) * tick;
    return end > start ? [{ midi: run.midi, start, duration: end - start }] : [];
  });
}
