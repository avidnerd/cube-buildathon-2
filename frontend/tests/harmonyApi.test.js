import test from 'node:test';
import assert from 'node:assert/strict';
import { engineMelody, harmonyBasis, harmonyChoices, takeFromAnalysis, toPcm16 } from '../src/harmonyApi.js';
import { bandFits, playbackOptions } from '../src/playbackSources.js';

const analysis = {
  bpm: 100.4, beat0: 1, beats: Array.from({ length: 20 }, (_, i) => 1 + i * 0.6),
  has_music: true, stems: ['accompaniment', 'vocals'], chords: ['C'], range: { low: 60, high: 67 },
  notes: [
    { pitch: 60, start: 5, duration: 1, t0: 4.02, t1: 4.55, lyric: 'hel', word_start: true },
    { pitch: 64, start: 6, duration: 1, t0: 4.63, t1: 5.1, lyric: 'lo', word_start: false },
  ],
};
const path = (name, backing) => ({
  name, backing, key: { tonic: 'C', mode: 'major' },
  timeline: [{ symbol: 'C' }, { symbol: 'C' }, { symbol: 'G' }],
  parts: {
    classic: { high: [{ pitch: 64, start: 5, duration: 1, lyric: 'hel' }], low: [{ pitch: 55, start: 5, duration: 1 }] },
    satb: { alto: [{ pitch: 57, start: 5, duration: 1 }], tenor: [{ pitch: 53, start: 5, duration: 1 }], bass: [{ pitch: 48, start: 5, duration: 1 }] },
  },
});

test('a take starts at the bar of its first note and keeps real timing', () => {
  const take = takeFromAnalysis(analysis, 'job1', '4/4');
  assert.equal(take.timing.shift, 4);
  assert.equal(take.timing.origin, analysis.beats[4]);
  assert.equal(take.notes[0].start, 1);
  assert.equal(take.notes[0].lyric, 'hel');
  assert.equal(take.bpm, 100);
  assert.equal(take.backend.job, 'job1');
});

test('unedited notes go back to the engine exactly as they came', () => {
  const take = takeFromAnalysis(analysis, 'j', '4/4');
  const track = { ...take, role: 'melody' };
  assert.deepEqual(engineMelody(track, 100), analysis.notes);
});

test('an edited note gets its time from the grid', () => {
  const take = takeFromAnalysis(analysis, 'j', '4/4');
  const notes = [{ ...take.notes[0], pitch: 62 }, take.notes[1]];
  const out = engineMelody({ ...take, notes }, 100);
  assert.equal(out[0].pitch, 62);
  assert.equal(out[0].start, 5);
  assert.ok(Math.abs(out[0].t0 - (take.timing.origin + 60 / 100.4)) < 1e-9);
  assert.equal(out[1], analysis.notes[1]);
});

test('a demo melody without engine timing still produces a request', () => {
  const track = { notes: [{ pitch: 60, start: 2, duration: 1 }] };
  const [n] = engineMelody(track, 120);
  assert.equal(n.t0, 1);
  assert.equal(n.t1, 1.5);
});

test('choices cover each path above and below, plus SATB voices of Plain', () => {
  const choices = harmonyChoices({ paths: [path('Plain', 'band'), path('Twist', 'pad')] }, 4);
  assert.deepEqual(choices.map(c => c.id), [
    'plain-classic-high', 'plain-classic-low', 'twist-classic-high', 'twist-classic-low',
    'plain-satb-alto', 'plain-satb-tenor', 'plain-satb-bass',
  ]);
  assert.equal(choices[0].notes[0].start, 1);
  assert.equal(choices[0].desc, 'C G');
  assert.equal(choices[2].desc, 'C G · new chords');
});

test('stereo audio converts to interleaved 16-bit PCM', () => {
  const buffer = { numberOfChannels: 2, length: 2, getChannelData: c => (c ? [0, -1] : [0.5, 2]) };
  const { pcm, channels } = toPcm16(buffer);
  assert.equal(channels, 2);
  assert.deepEqual([...pcm], [16383, 0, 32767, -32767]);
});

test('the band is silent under reharmonized parts', () => {
  assert.equal(bandFits([{ role: 'harmony', backing: 'band' }]), true);
  assert.equal(bandFits([{ role: 'harmony', backing: 'pad' }]), false);
});

const projectWith = extra => {
  const take = takeFromAnalysis(analysis, 'j', '4/4');
  const melody = { id: 'melody', role: 'melody', ...take };
  return { tempo: 100, tracks: [melody, ...extra(melody)] };
};
const harmonyTrack = basis => ({ id: 'harmony-x', role: 'harmony', backing: 'band', notes: [], part: [{ pitch: 64 }], basis });
const quiet = { mute: {}, solo: null };

test('real voices play at the sung tempo, in sync with the recording', () => {
  const project = projectWith(m => [harmonyTrack(harmonyBasis(m))]);
  const out = playbackOptions(project, project.tracks, { melody: 1 }, quiet);
  assert.equal(out.tempo, 100.4);
  assert.equal(out.tracks[0].audio.lead, true);                  // the lead's own take, tuned by the engine
  assert.equal(out.tracks[0].audio.fallback, '/api/job/j/audio/vocals.wav');
  assert.equal(out.tracks[1].audio.job, 'j');
  assert.equal(out.tracks[1].audio.offset, project.tracks[0].timing.origin);
  assert.equal(out.gains.band, 0.7);
});

test('tone mode plays every part on the synth, with no band', () => {
  const project = projectWith(m => [harmonyTrack(harmonyBasis(m))]);
  const out = playbackOptions(project, project.tracks, { melody: 1 }, quiet, { tones: true });
  assert.deepEqual(out.tracks.map(t => t.audio), [null, null]);
  assert.equal(out.tempo, 100);
  assert.equal(out.gains.band, undefined);
});

test('slowed down, retimed, or out-of-date parts fall back to the synth', () => {
  const project = projectWith(m => [harmonyTrack(harmonyBasis(m))]);
  assert.equal(playbackOptions(project, project.tracks, {}, quiet, { rate: 0.5 }).tracks[0].audio, null);
  assert.equal(playbackOptions({ ...project, tempo: 120 }, project.tracks, {}, quiet).tracks[0].audio, null);
  const stale = projectWith(() => [harmonyTrack('older melody')]);
  assert.equal(playbackOptions(stale, stale.tracks, {}, quiet).tracks[1].audio, null);
});

import { arrangementsFrom, trackFromVoice } from '../src/harmonyApi.js';
import { buildManifest, loadSharedSong, projectFromManifest } from '../src/share.js';
import { hasWords, karaokeLines, lineIndexAt, noteName } from '../src/karaoke.js';

const engineOptions = () => ({
  arrangements: { satb: { label: 'SATB', parts: [{ id: 'soprano', label: 'Soprano' }, { id: 'alto', label: 'Alto' }] }, classic: { label: 'x', parts: [{ id: 'high', label: 'Harmony above' }] } },
  paths: [{ backing: 'pad', timeline: [{ symbol: 'C' }], parts: {
    satb: { soprano: [{ pitch: 60, melody_pitch: 60, start: 4, duration: 1 }], alto: [{ pitch: 55, melody_pitch: 60, start: 4, duration: 1 }] },
    classic: { high: [{ pitch: 64, melody_pitch: 60, start: 4, duration: 1 }] },
  } }],
});

test('arrangements list friendly names first and find which voice is the singer', () => {
  const [classic, satb] = arrangementsFrom(engineOptions(), 4);
  assert.equal(classic.name, '3RD + 4TH');
  assert.equal(satb.name, 'SATB');
  assert.deepEqual(satb.voices.map(v => v.isLead), [true, false]);
  assert.equal(satb.voices[1].notes[0].start, 0);
  assert.equal(trackFromVoice(satb.voices[1], { ...satb, id: 'satb_tenor' }, 'b').id, 'harmony-satb-tenor-alto');
});

const n = (start, lyric, word_start = true, duration = 1) => ({ pitch: 60, start, duration, lyric, raw: { word_start } });

test('karaoke joins syllables, holds melismas and breaks lines at rests', () => {
  const lines = karaokeLines([n(0, 'hel-'), n(1, 'lo', false), n(2, '~', false), n(6, 'world')]);
  assert.equal(lines.length, 2);
  assert.deepEqual(lines[0].syllables.map(s => [s.text, s.space]), [['hel', false], ['lo', false]]);
  assert.equal(lines[0].syllables[1].end, 3);
  assert.equal(lines[1].syllables[0].space, false);
  assert.equal(hasWords(lines), true);
});

test('karaoke breaks at punctuation and shows the upcoming line between lines', () => {
  const lines = karaokeLines([n(0, 'stop,'), n(1, 'go')]);
  assert.equal(lines.length, 2);
  assert.equal(lineIndexAt(lines, 0.5), 0);
  assert.equal(lineIndexAt(lines, 1.5), 1);
  assert.equal(lineIndexAt(lines, 99), 1);
});

test('takes with no words are reported and notes are named', () => {
  assert.equal(hasWords(karaokeLines([{ pitch: 60, start: 0, duration: 1, lyric: null }])), false);
  assert.equal(noteName(60), 'C4');
  assert.equal(noteName(70), 'Bb4');
});

test('a share keeps the music and drops engine internals', () => {
  const project = { title: 'T', key: 'C major', tempo: 100, timeSignature: '4/4', tracks: [{ id: 'melody', name: 'Melody', role: 'melody', part: [1], backend: { job: 'j' }, notes: [{ pitch: 60, start: 0, duration: 1, lyric: 'la', raw: { t0: 1, word_start: true } }] }] };
  const m = buildManifest(project, { melody: 'https://x/m.wav', band: 'https://x/b.wav' }, { origin: 1, bpm: 100.4 });
  assert.deepEqual(m.tracks[0].notes[0], { pitch: 60, start: 0, duration: 1, lyric: 'la', wordStart: true });
  assert.equal(m.tracks[0].backend, undefined);
  const song = projectFromManifest(m);
  const out = playbackOptions(song, song.tracks, { melody: 1 }, quiet);
  assert.equal(out.tempo, 100.4);
  assert.equal(out.tracks[0].audio.url, 'https://x/m.wav');
  assert.equal(out.tracks[0].audio.offset, 1);
  assert.equal(out.tracks[1].id, 'band');
  assert.equal(playbackOptions(song, song.tracks, {}, quiet, { rate: 0.5 }).tracks[0].audio, null);
});

test('share links are validated before anything is fetched', async () => {
  assert.equal(await loadSharedSong('?x=1', () => { throw new Error('no fetch'); }), null);
  await assert.rejects(loadSharedSong('?song=../../evil', () => { throw new Error('no fetch'); }), /not valid/);
  const seen = [];
  const song = await loadSharedSong('?song=0123456789abcdef.storeabc123', async url => { seen.push(url); return { ok: true, json: async () => ({ title: 'T', tracks: [], timing: {} }) }; });
  assert.equal(seen[0], 'https://storeabc123.public.blob.vercel-storage.com/shares/0123456789abcdef/song.json');
  assert.equal(song.shared, true);
});

import { leadForArrangement, plainMelody } from '../src/harmonyApi.js';

const lifted = () => {
  const part = analysis.notes.map(n => ({ pitch: n.pitch + 24, melody_pitch: n.pitch, start: n.start, duration: n.duration }));
  const other = analysis.notes.map((n, i) => ({ pitch: n.pitch + 3 + i, melody_pitch: n.pitch, start: n.start, duration: n.duration }));
  const take = takeFromAnalysis(analysis, 'j', '4/4');
  const options = { arrangements: { satb: { label: 'SATB', parts: [{ id: 'soprano', label: 'Soprano' }, { id: 'alto', label: 'Alto' }] } }, paths: [{ backing: 'pad', timeline: [], parts: { satb: { soprano: part, alto: other } } }] };
  return { melody: { id: 'melody', role: 'melody', name: 'Melody', ...take }, satb: arrangementsFrom(options, 4)[0] };
};

test('a melody lifted by octaves counts as the singer, and keeps four tracks', () => {
  const { satb } = lifted();
  assert.deepEqual(satb.voices.map(v => [v.isLead, v.leadShift]), [[true, 24], [false, 0]]);
});

test('the lifted lead sings its octave but still talks to the engine as recorded', () => {
  const { melody, satb } = lifted();
  const lead = leadForArrangement(melody, satb);
  assert.equal(lead.name, 'Soprano');
  assert.equal(lead.notes[0].pitch, 84);
  assert.equal(harmonyBasis(lead), harmonyBasis(melody));
  assert.deepEqual(engineMelody(lead, 100), analysis.notes);
  const project = { tempo: 100, tracks: [lead] };
  const [track] = playbackOptions(project, project.tracks, {}, quiet).tracks;
  assert.equal(track.audio.url, undefined);
  assert.equal(track.audio.part[0].pitch, 84);
});

test('choosing another arrangement restores the recorded melody', () => {
  const { melody, satb } = lifted();
  const back = plainMelody(leadForArrangement(melody, satb));
  assert.equal(back.name, 'Melody');
  assert.equal(back.notes[0].pitch, 60);
  assert.equal(back.leadShift, undefined);
  assert.equal(back.part, undefined);
});
