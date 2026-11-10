// Playback for every view of the project (Tone.js, per docs/SPEC.md).
// Parts are notes, so tempo changes are free: `rate` scales playback speed.
import * as Tone from 'tone';
import { fetchAudio } from './harmonyApi.js';

function voiceSynth() {
  // A soft "ooh"-like tone until we load vocal samples into a Tone.Sampler.
  return new Tone.PolySynth(Tone.Synth, {
    oscillator: { type: 'fattriangle', count: 2, spread: 12 },
    envelope: { attack: 0.06, decay: 0.15, sustain: 0.75, release: 0.35 },
    volume: -10,
  });
}

const gainToDb = gain => (gain <= 0.001 ? -Infinity : Tone.gainToDb(gain));

// Decoded voices, by source key. Rendering a part is slow, so each happens once.
const audioCache = new Map();
export function loadAudio(source) {
  if (!audioCache.has(source.key)) {
    const pending = fetchAudio(source)
      .then(bytes => Tone.getContext().decodeAudioData(bytes))
      .then(decoded => new Tone.ToneAudioBuffer(decoded));
    pending.catch(() => audioCache.delete(source.key)); // a failed render can be retried
    audioCache.set(source.key, pending);
  }
  return audioCache.get(source.key);
}

class Player {
  constructor() {
    this.tracks = new Map(); // id -> { synth, volume, part }
    this.playing = false;
    this.totalBeats = 0;
    this.tempo = 120;
    this.onEnd = null;
    this.session = 0;
  }

  /** Must be called from a user gesture (browsers block audio until then). */
  async unlock() { await Tone.start(); }

  stop() {
    const transport = Tone.getTransport();
    transport.stop();
    transport.cancel();
    this.session++;
    for (const t of this.tracks.values()) {
      if (t.audio) { t.audio.unsync(); t.audio.dispose(); }
      else { t.part.dispose(); t.synth.releaseAll(); t.synth.dispose(); }
      t.volume.dispose();
    }
    this.tracks.clear();
    if (this.playing) { this.playing = false; this.onEnd?.(); }
  }

  /** tracks: [{ id, notes, audio? }], gains: { id: 0..1 }. Plays from `fromBeat`.
   * A track with `audio` plays that recording; if it can't load, its notes play on the synth.
   * Returns false if another play or stop took over while audio was loading. */
  async play({ tracks, tempo, totalBeats, gains = {}, rate = 1, fromBeat = 0, loop = false, onEnd }) {
    await this.unlock();
    this.stop();
    const session = this.session;
    const buffers = await Promise.all(tracks.map(t => (t.audio ? loadAudio(t.audio).catch(() => null) : null)));
    if (session !== this.session) return false;
    const transport = Tone.getTransport();
    this.tempo = tempo * rate;
    this.totalBeats = totalBeats;
    const secondsPerBeat = 60 / this.tempo;
    tracks.forEach((track, index) => {
      const buffer = buffers[index];
      if (!buffer && !track.notes?.length) return;
      const volume = new Tone.Volume(gainToDb(gains[track.id] ?? 1)).toDestination();
      if (buffer) {
        const audio = new Tone.Player(buffer).connect(volume);
        audio.sync().start(0, Math.max(0, track.audio.offset));
        this.tracks.set(track.id, { audio, volume });
        return;
      }
      const synth = voiceSynth().connect(volume);
      const part = new Tone.Part((time, n) => {
        synth.triggerAttackRelease(Tone.Frequency(n.pitch, 'midi').toFrequency(), n.duration * secondsPerBeat * 0.97, time);
      }, track.notes.map(n => [n.start * secondsPerBeat, n])).start(0);
      this.tracks.set(track.id, { synth, volume, part });
    });
    transport.loop = loop;
    transport.loopStart = 0;
    transport.loopEnd = totalBeats * secondsPerBeat;
    if (!loop) transport.scheduleOnce(() => Tone.getDraw().schedule(() => this.stop(), Tone.now()), totalBeats * secondsPerBeat);
    this.onEnd = onEnd;
    this.playing = true;
    transport.start('+0.05', fromBeat * secondsPerBeat);
    return true;
  }

  setGain(id, gain) {
    const t = this.tracks.get(id);
    if (t) t.volume.volume.rampTo(gainToDb(gain), 0.05);
  }

  /** Current position in beats (of the original tempo grid). */
  position() {
    if (!this.playing) return 0;
    return Tone.getTransport().seconds * (this.tempo / 60);
  }
}

export const player = new Player();

/** Render one or more tracks to a WAV Blob (for sharing a single part). */
export async function renderWav({ tracks, tempo, totalBeats }) {
  const secondsPerBeat = 60 / tempo;
  const duration = totalBeats * secondsPerBeat + 0.6;
  const buffer = await Tone.Offline(({ transport }) => {
    for (const track of tracks) {
      const synth = voiceSynth().toDestination();
      new Tone.Part((time, n) => {
        synth.triggerAttackRelease(Tone.Frequency(n.pitch, 'midi').toFrequency(), n.duration * secondsPerBeat * 0.97, time);
      }, track.notes.map(n => [n.start * secondsPerBeat, n])).start(0);
    }
    transport.start(0);
  }, duration, 1, 44100);
  return encodeWav(buffer.get());
}

export function encodeWav(audioBuffer) {
  const samples = audioBuffer.getChannelData(0);
  const rate = audioBuffer.sampleRate;
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (offset, s) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: 'audio/wav' });
}
