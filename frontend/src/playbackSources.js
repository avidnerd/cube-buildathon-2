// Decides what each track sounds like: the singer's real voice where the
// engine has it, the synth otherwise.
import { engineMelody, harmonyBasis, stemUrl, timingOf } from './harmonyApi.js';

const BAND_GAIN = 0.7;

/** Real audio only fits at the tempo it was sung. */
function liveTiming(project, melody, rate) {
  if (!melody?.backend?.job || rate !== 1) return null;
  const timing = timingOf(melody, project.tempo);
  return Math.round(timing.bpm) === Math.round(project.tempo) ? timing : null;
}

function sourceFor(track, melody, project, timing) {
  if (!timing) return null;
  const { job } = melody.backend;
  if (track.role === 'melody' && track.leadShift)
    return { key: `${job}/lead/${track.leadShift}/${harmonyBasis(melody)}`, job, melody: engineMelody(melody, project.tempo), part: track.part, offset: timing.origin };
  // The singer's own take, pitch-corrected onto their notes (raw take if the engine can't).
  if (track.role === 'melody')
    return { key: `${job}/lead-tuned/${harmonyBasis(melody)}`, job, melody: engineMelody(melody, project.tempo), lead: true, fallback: stemUrl(job, 'vocals'), offset: timing.origin };
  if (track.role !== 'harmony' || !track.part || track.basis !== harmonyBasis(melody)) return null;
  if (track.part.some(p => p.synth)) return null; // riffs and bass lines are new notes: played as tones
  return { key: `${job}/${track.id}/${track.basis}`, job, melody: engineMelody(melody, project.tempo), part: track.part, offset: timing.origin };
}

/** Does this track list leave the original band usable? New chords would clash with it. */
export const bandFits = tracks => !tracks.some(t => t.role === 'harmony' && t.backing === 'pad');
export const hasBand = project => !!project.tracks.find(t => t.role === 'melody')?.backend?.stems?.includes('accompaniment');

/** A friend's copy: every voice comes from the published files. */
function sharedOptions(project, tracks, gains, mix, rate) {
  const { origin, bpm } = project.sharedTiming;
  const usable = rate === 1 && Math.round(bpm) === Math.round(project.tempo);
  const source = url => (usable && url ? { key: url, url, offset: origin } : null);
  const list = tracks.map(t => ({ ...t, audio: source(t.audioUrl) }));
  const allGains = { ...gains };
  if (usable && project.bandUrl) {
    list.push({ id: 'band', notes: [], audio: source(project.bandUrl) });
    allGains.band = mix.solo ? 0 : gains.band ?? BAND_GAIN;
  }
  return { tracks: list, tempo: usable ? bpm : project.tempo, gains: allGains };
}

/** Options for player.play(): adds voice audio and the band to tracks and gains. */
export function playbackOptions(project, tracks, gains, mix, { rate = 1, tones = false } = {}) {
  if (tones) return { tracks: tracks.map(t => ({ ...t, audio: null })), tempo: project.tempo, gains: { ...gains } };
  if (project.shared) return sharedOptions(project, tracks, gains, mix, rate);
  const melody = project.tracks.find(t => t.role === 'melody');
  const timing = liveTiming(project, melody, rate);
  const list = tracks.map(t => ({ ...t, audio: sourceFor(t, melody, project, timing) }));
  const allGains = { ...gains };
  if (timing && hasBand(project)) {
    const { job } = melody.backend;
    list.push({ id: 'band', notes: [], audio: { key: `${job}/accompaniment`, url: stemUrl(job, 'accompaniment'), offset: timing.origin } });
    allGains.band = bandFits(tracks) && (mix.solo ? mix.solo === 'band' : !mix.mute.band) ? gains.band ?? BAND_GAIN : 0;
  }
  return { tracks: list, tempo: timing ? timing.bpm : project.tempo, gains: allGains };
}
