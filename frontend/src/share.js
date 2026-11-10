// Share links. A song is published to Vercel Blob as one WAV per voice plus a
// song.json, so friends get the real voices even when the engine is offline.
import { upload } from '@vercel/blob/client';
import { fetchAudio } from './harmonyApi.js';
import { emptyProject } from './project.js';
import { playbackOptions } from './playbackSources.js';

const NO_MIX = { mute: {}, solo: null };
// Songs always publish to the real site, even from local dev, so links work for friends.
const PUBLIC_SITE = 'https://4track-harmony.vercel.app';
const siteOrigin = () => (['127.0.0.1', 'localhost'].includes(location.hostname) ? PUBLIC_SITE : location.origin);
const SONG_PARAM = /^([a-f0-9]{16})\.([a-z0-9]{8,40})$/;

const manifestUrl = (id, store) => `https://${store}.public.blob.vercel-storage.com/shares/${id}/song.json`;

export function buildManifest(project, urls, timing) {
  return {
    version: 1,
    title: project.title,
    key: project.key,
    tempo: project.tempo,
    timeSignature: project.timeSignature,
    timing,
    bandUrl: urls.band ?? null,
    tracks: project.tracks.map(t => ({
      id: t.id, name: t.name, role: t.role, voice: t.voice ?? null, backing: t.backing ?? null, style: t.style ?? null,
      audioUrl: urls[t.id] ?? null,
      notes: t.notes.map(n => ({ pitch: n.pitch, start: n.start, duration: n.duration, lyric: n.lyric ?? null, wordStart: n.raw?.word_start ?? n.wordStart ?? false })),
    })),
  };
}

export function projectFromManifest(m) {
  return { ...emptyProject(), title: m.title, key: m.key, tempo: m.tempo, timeSignature: m.timeSignature,
    tracks: m.tracks, shared: true, sharedTiming: m.timing, bandUrl: m.bandUrl };
}

/** Upload every voice, then the song. onProgress(done, total). Returns the link. */
export async function publishSong(project, { onProgress } = {}) {
  const id = Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, '0')).join('');
  const put = (name, body, type) => upload(`shares/${id}/${name}`, new Blob([body], { type }), { access: 'public', handleUploadUrl: `${siteOrigin()}/api/blob-upload`, contentType: type });
  const { tracks, tempo } = playbackOptions(project, project.tracks, {}, NO_MIX);
  const sources = tracks.filter(t => t.audio);
  const urls = {};
  let done = 0;
  const total = sources.length + 1;
  onProgress?.(0, total);
  let first = null;
  await Promise.all(sources.map(async t => {
    const uploaded = await put(`${t.id}.wav`, await fetchAudio(t.audio), 'audio/wav');
    urls[t.id] = uploaded.url;
    onProgress?.(++done, total);
  }));
  first = sources[0]?.audio.offset ?? 0;
  const manifest = buildManifest(project, urls, { origin: first, bpm: tempo });
  const { url } = await put('song.json', JSON.stringify(manifest), 'application/json');
  onProgress?.(total, total);
  const store = new URL(url).hostname.split('.')[0];
  return `${siteOrigin()}/?song=${id}.${store}`;
}

/** The `song` parameter of a share link -> a project, or null if there is none. */
export async function loadSharedSong(search = location.search, fetchImpl = fetch) {
  const param = new URLSearchParams(search).get('song');
  if (!param) return null;
  const match = SONG_PARAM.exec(param);
  if (!match) throw new Error('That share link is not valid.');
  const response = await fetchImpl(manifestUrl(match[1], match[2]));
  if (!response.ok) throw new Error('That song could not be found. It may have been removed.');
  return projectFromManifest(await response.json());
}

export const isShareLink = (search = location.search) => new URLSearchParams(search).has('song');
