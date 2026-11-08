import { BasicPitch, noteFramesToTime, outputToNotesPoly } from '@spotify/basic-pitch';
import { basicPitchNotesToMelody } from './basicPitchNotes.js';

/** Input must be mono PCM at 22050 Hz. model is a URL or GraphModel promise. */
export async function transcribeSamples(samples, model, onProgress = () => {}) {
  if (!(samples instanceof Float32Array) || !samples.length || samples.length > 22050 * 61)
    throw new Error('Use a nonempty recording of up to 60 seconds.');
  let energy = 0;
  for (const value of samples) energy += value * value;
  if (Math.sqrt(energy / samples.length) < 0.003) return [];
  const frames = [], onsets = [];
  const engine = new BasicPitch(model);
  await engine.evaluateModel(samples, (f,o) => { frames.push(...f); onsets.push(...o); }, onProgress);
  const events = noteFramesToTime(outputToNotesPoly(frames, onsets, 0.25, 0.25, 11, true, 1047, 65));
  return basicPitchNotesToMelody(events, samples.length / 22050);
}
