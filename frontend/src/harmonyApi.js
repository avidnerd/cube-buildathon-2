// The bridge to the harmony engine (backend/harmony, served by
// backend.harmony.playground.server and proxied at /api by Vite).
//
// The engine keeps every note's real sung time (t0/t1, seconds) next to its
// place on the beat grid. Screens use the note model (beats); each note also
// carries the engine's original as `raw`, so requests and voice renders use
// the singer's exact timing rather than the grid.
import { makeNote, notesEnd } from './noteModel.js';
import { beatsPerBar } from './project.js';

// Empty in development (Vite proxies /api); the public engine address in production.
export const ENGINE = import.meta.env?.VITE_ENGINE_URL ?? '';
// ngrok's free tier shows a browser warning page unless this header is sent.
export const engineHeaders = ENGINE ? { 'ngrok-skip-browser-warning': '1' } : {};

const NOT_RUNNING = 'The harmony engine is offline right now. Please try again in a little while.';

async function call(url, init, fetchImpl = fetch) {
  let response;
  try { response = await fetchImpl(ENGINE + url, { ...init, headers: { ...init?.headers, ...engineHeaders } }); } catch { throw new Error(NOT_RUNNING); }
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    if (response.status >= 500 && !data.error) throw new Error(NOT_RUNNING);
    throw new Error(data.error || `Harmony request failed (${response.status}).`);
  }
  return data;
}

const postJson = (url, body, fetchImpl) => call(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, fetchImpl);

/** AudioBuffer -> interleaved little-endian 16-bit PCM, what /api/analyze takes. */
export function toPcm16(buffer) {
  const channels = Math.min(2, buffer.numberOfChannels);
  const data = Array.from({ length: channels }, (_, c) => buffer.getChannelData(c));
  const pcm = new Int16Array(buffer.length * channels);
  for (let i = 0; i < buffer.length; i++)
    for (let c = 0; c < channels; c++) pcm[i * channels + c] = Math.max(-1, Math.min(1, data[c][i])) * 32767;
  return { pcm, channels };
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

/** Send audio to the engine and wait. Returns { jobId, result }.
 * source: 'mic' (voice only) or 'upload' (separates voice from music).
 * onStage({ stage, done, total }) reports progress; isCancelled() stops waiting. */
export async function analyzeAudio(buffer, { source, bpm, offset, bpb = 4 }, { onStage, isCancelled = () => false } = {}) {
  const { pcm, channels } = toPcm16(buffer);
  const query = new URLSearchParams({ sr: String(buffer.sampleRate), channels: String(channels), source, bpb: String(bpb) });
  if (bpm) { query.set('bpm', String(bpm)); query.set('offset', String(offset ?? 0)); }
  const { job } = await call(`/api/analyze?${query}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: pcm.buffer });
  for (;;) {
    if (isCancelled()) return null;
    const state = await call(`/api/job/${job}`);
    onStage?.({ stage: state.stage, done: state.done_stages.length, total: state.stages.length });
    if (state.done) {
      if (state.error) throw new Error(state.error);
      return { jobId: job, result: state.result };
    }
    await sleep(400);
  }
}

/** Engine analysis -> what a take needs. Beat 0 of the tape is the bar holding
 * the first note, so a long intro doesn't leave empty bars. */
export function takeFromAnalysis(result, jobId, meter) {
  const bar = beatsPerBar(meter);
  const first = Math.min(...result.notes.map(n => n.start));
  const shift = Math.floor(first / bar) * bar;
  const bpm = result.bpm;
  const origin = result.beats?.[shift] ?? (result.beat0 ?? 0) + shift * 60 / bpm;
  return {
    notes: result.notes.map(n => makeNote(n.pitch, n.start - shift, n.duration, { lyric: n.lyric || null, raw: n })),
    bpm: Math.round(bpm),
    timing: { origin, shift, bpm },
    backend: {
      job: jobId,
      beats: result.beats,
      chords: result.chords,
      range: result.range,
      hasMusic: !!result.has_music,
      stems: result.stems ?? [],
    },
  };
}

/** The timing of a melody track: real for engine takes, derived for demos. */
export function timingOf(track, tempo) {
  return track.timing ?? { origin: 0, shift: 0, bpm: tempo };
}

/** Melody notes as the engine expects them. Unedited notes go back exactly as
 * they came; edited ones get times worked out from their place on the grid. */
export function engineMelody(track, tempo) {
  const { origin, shift, bpm } = timingOf(track, tempo);
  const spb = 60 / bpm;
  const octaves = track.leadShift ?? 0;
  return track.notes.map(n => {
    const r = n.raw;
    const pitch = n.pitch - octaves;
    if (r && r.pitch === pitch && r.start - shift === n.start && r.duration === n.duration) return r;
    const t0 = origin + n.start * spb;
    return { pitch, start: n.start + shift, duration: n.duration, t0, t1: t0 + n.duration * spb, lyric: n.lyric || '', word_start: false };
  });
}

/** A part was written for one exact melody. */
export const harmonyBasis = melody => JSON.stringify(melody.notes.map(n => [n.pitch - (melody.leadShift ?? 0), n.start, n.duration]));

function voiceRange(track) {
  const pitches = track.notes.map(n => n.pitch - (track.leadShift ?? 0));
  const low = track.backend?.range?.low ?? Math.min(...pitches);
  const high = track.backend?.range?.high ?? Math.max(...pitches);
  return { low: low - 5, high: high + 5, strongLow: low - 3, strongHigh: high + 3 };
}

/** Ask the engine for harmony options for a melody track. */
export function requestHarmonyOptions(track, settings, fetchImpl) {
  const key = `${track.backend?.job}|${settings.timeSignature}|${harmonyBasis(track)}`;
  if (!optionsCache.has(key)) {
    const pending = fetchHarmonyOptions(track, settings, fetchImpl);
    pending.catch(() => optionsCache.delete(key));
    optionsCache.set(key, pending);
  }
  return optionsCache.get(key);
}

const optionsCache = new Map(); // Split and Arrange ask for the same options

function fetchHarmonyOptions(track, { tempo, timeSignature }, fetchImpl) {
  const { shift, bpm, origin } = timingOf(track, tempo);
  const spb = 60 / bpm;
  const beats = track.backend?.beats ?? Array.from({ length: Math.ceil(notesEnd(track.notes)) + 3 }, (_, i) => origin + (i - shift) * spb);
  return postJson('/api/options', {
    melody: engineMelody(track, tempo),
    chords: track.backend?.chords ?? undefined,
    voice: voiceRange(track),
    beats_per_bar: beatsPerBar(timeSignature),
    beats,
    job: track.backend?.job,
  }, fetchImpl);
}

const SATB_PARTS = ['alto', 'tenor', 'bass'];
/** A part's notes for display: rests (notes this voice leaves out) dropped, timing already moved by the engine. */
const partNotes = (part, shift) => part.filter(p => !p.rest).map(p => makeNote(p.pitch, p.start - shift, p.duration, { lyric: p.lyric || null, ...(p.cents ? { cents: p.cents } : {}) }));
/** Rounds, canons and echoes sing later than the lead; riffs are new notes. Neither is the lead's line. */
const isMoved = part => part.some(p => p.delay || p.rest || p.synth);
const describePath = path => path.timeline.map(s => s.symbol).filter((s, i, a) => s !== a[i - 1]).join(' ');

/** Engine options -> the flat list the Arrange picker cycles through. */
export function harmonyChoices(options, shift = 0) {
  const choice = (path, arrangement, part, label, name) => ({
    kind: 'harmony',
    id: `${path.name}-${arrangement}-${part}`.toLowerCase(),
    label: `${path.name.toUpperCase()} ${label.toUpperCase()}`,
    name,
    style: path.name,
    backing: path.backing,
    chords: path.timeline.map(s => ({ name: s.symbol })),
    desc: `${describePath(path)}${path.backing === 'pad' && path.name !== 'Plain' ? ' · new chords' : ''}`,
    keyName: `${path.key.tonic} ${path.key.mode}`,
    part: path.parts[arrangement][part],
    notes: partNotes(path.parts[arrangement][part], shift),
  });
  const texture = (path, id, info, part) => ({
    kind: 'harmony', id: `${path.name}-${id}-${part.id}`.toLowerCase(),
    label: `${info.label.toUpperCase()} · ${part.label.toUpperCase()}`, name: part.label === info.label ? info.label : `${info.label} ${part.label.toLowerCase()}`,
    style: info.label, backing: path.backing, chords: path.timeline.map(s => ({ name: s.symbol })),
    desc: info.desc, keyName: `${path.key.tonic} ${path.key.mode}`,
    part: path.textures[id][part.id], notes: partNotes(path.textures[id][part.id], shift),
  });
  const out = [];
  for (const path of options.paths) {
    out.push(choice(path, 'classic', 'high', 'above', `${path.name} above`));
    out.push(choice(path, 'classic', 'low', 'below', `${path.name} below`));
  }
  const plain = options.paths.find(p => p.name === 'Plain');
  if (plain) for (const part of SATB_PARTS) out.push(choice(plain, 'satb', part, part, `${part[0].toUpperCase()}${part.slice(1)} (SATB)`));
  if (plain?.textures) for (const [id, info] of Object.entries(options.textures ?? {}))
    for (const part of info.parts) out.push(texture(plain, id, info, part));
  return out;
}

const ARRANGEMENT_INFO = {
  classic: ['3RD + 4TH', '3rd above · 4th below'],
  close: ['TIGHT 3RDS', '3rd above · 3rd below'],
  stack: ['STACKED', '3rd and 5th above'],
  satb: ['SATB', 'Melody on top'],
  satb_tenor: ['SATB TENOR', 'Melody in the tenor'],
  round: ['ROUND', null],
  canon: ['CANON', null],
  echo: ['ECHO', null],
  riff: ['RIFF + BASS', null],
};

/** Engine options -> every arrangement with its voices, for the Split screen. */
export function arrangementsFrom(options, shift = 0) {
  const path = options.paths[0];
  if (!path) return [];
  const known = Object.keys(ARRANGEMENT_INFO);
  const ids = Object.keys(options.arrangements).sort((a, b) => (known.indexOf(a) + 1 || 99) - (known.indexOf(b) + 1 || 99));
  const textures = Object.keys(options.textures ?? {}).filter(id => path.textures?.[id]);
  return [...ids, ...textures].map(id => {
    const isTexture = textures.includes(id);
    const info = isTexture ? options.textures[id] : options.arrangements[id];
    const [name, desc] = ARRANGEMENT_INFO[id] ?? [info.label.toUpperCase(), ''];
    const parts = isTexture ? path.textures[id] : path.parts[id];
    return {
      id, name, desc: desc ?? info.desc ?? '', style: name, backing: path.backing,
      chords: path.timeline.map(s => ({ name: s.symbol })),
      voices: info.parts.map(({ id: voice, label }) => {
        const part = parts[voice];
        // SATB may lift the tune into the voice's range: it's still the singer's line.
        const leadShift = part[0].pitch - part[0].melody_pitch;
        const isLead = !isMoved(part) && leadShift % 12 === 0 && part.every(p => p.pitch - p.melody_pitch === leadShift);
        return { id: voice, label, part, isLead, leadShift: isLead ? leadShift : 0, notes: partNotes(part, shift) };
      }).filter(v => v.notes.length),
    };
  });
}

/** The melody track as recorded, undoing any arrangement it was lifted for. */
export function plainMelody(track) {
  const { leadShift = 0, part, ...rest } = track;
  return { ...rest, name: 'Melody', notes: leadShift ? track.notes.map(n => ({ ...n, pitch: n.pitch - leadShift })) : track.notes };
}

/** The melody track for an arrangement: named for its part, and in that part's octave. */
export function leadForArrangement(track, arrangement) {
  const plain = plainMelody(track);
  const voice = arrangement.voices.find(v => v.isLead);
  if (!voice) return plain;
  if (!voice.leadShift) return { ...plain, name: voice.label };
  return { ...plain, name: voice.label, leadShift: voice.leadShift, part: voice.part, notes: plain.notes.map(n => ({ ...n, pitch: n.pitch + voice.leadShift })) };
}

/** One voice of an arrangement, as a project track. */
export function trackFromVoice(voice, arrangement, basis) {
  return {
    id: `harmony-${arrangement.id.replace(/_/g, '-')}-${voice.id}`, name: voice.label, role: 'harmony', assignedTo: null, audioUrl: null, voice: null,
    notes: voice.notes, part: voice.part, basis, backing: arrangement.backing, style: arrangement.name, chords: arrangement.chords,
  };
}

export const stemUrl = (job, stem) => `${ENGINE}/api/job/${job}/audio/${stem}.wav`;

/** Fetch a WAV: { url } for a stem, { job, melody, part } for the lead's voice singing a part,
 *  or { job, melody, lead: true } for the lead's own take in tune (then `fallback`, a stem, if that fails). */
export async function fetchAudio(source) {
  const isEngine = !source.url || !/^https?:/.test(source.url) || (ENGINE && source.url.startsWith(ENGINE));
  const headers = isEngine ? engineHeaders : {};
  const body = source.lead ? { job: source.job, melody: source.melody, lead: true } : { job: source.job, melody: source.melody, part: source.part };
  let response = source.url
    ? await fetch(source.url, { headers })
    : await fetch(`${ENGINE}/api/render`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) });
  if (!response.ok && source.fallback) response = await fetch(source.fallback, { headers: engineHeaders });
  if (!response.ok) throw new Error(`audio unavailable (${response.status})`);
  return response.arrayBuffer();
}
