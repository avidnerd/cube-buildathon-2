import { secondsToBeats, beatsToSeconds } from './noteModel.js';

export const COUNTER_VOICES = ['soprano', 'alto', 'tenor', 'bass'];

/** Ask the Python generator (counter_api.py, proxied at /api by Vite) for a
 * counter-melody. `melody` is in seconds, as produced by the recorder.
 * Returns the API result with `counter` converted back to seconds. */
export async function requestCounterMelody(melody, { bpm, meter, key, voice = 'alto' }, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl('/api/counter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: secondsToBeats(melody, bpm), bpm, meter, key, voice }),
    });
  } catch {
    throw new Error('Could not reach the counter-melody server. Start it with "npm run api" (or use "npm start").');
  }
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    if (response.status >= 500 && !data.error)
      throw new Error('The counter-melody server is not running. Start it with "npm run api" (or use "npm start").');
    throw new Error(data.error || `Counter-melody request failed (${response.status}).`);
  }
  return { ...data, counterBeats: data.counter, counter: beatsToSeconds(data.counter, bpm) };
}
