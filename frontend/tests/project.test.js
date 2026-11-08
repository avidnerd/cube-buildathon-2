import test from 'node:test';
import assert from 'node:assert/strict';
import { clefFor, counterText, keyFromSpec, keyToSpec, projectBeats } from '../src/project.js';
import { karaokeGains, mixGains } from '../src/mix.js';
import { makeNote } from '../src/noteModel.js';

test('key names convert between the spec and the analyzer', () => {
  assert.equal(keyToSpec('G'), 'G major');
  assert.equal(keyToSpec('F#m'), 'F# minor');
  assert.equal(keyFromSpec('Bb minor'), 'Bbm');
  assert.equal(keyFromSpec('Eb major'), 'Eb');
});

test('project length rounds up to whole bars', () => {
  const p = { timeSignature: '4/4', tracks: [{ notes: [makeNote(60, 0, 1), makeNote(62, 4, 1.5)] }] };
  assert.equal(projectBeats(p), 8);
  assert.equal(projectBeats({ timeSignature: '3/4', tracks: [] }), 3);
});

test('tape counter and clef helpers', () => {
  assert.equal(counterText(0, '4/4'), '01.1');
  assert.equal(counterText(5.5, '4/4'), '02.2');
  assert.equal(counterText(3, '3/4'), '02.1');
  assert.equal(clefFor([makeNote(43, 0, 1)]), 'bass');
  assert.equal(clefFor([makeNote(53, 0, 1)]), 'treble-8');
  assert.equal(clefFor([makeNote(67, 0, 1)]), 'treble');
});

test('learning mixes: solo, predominant, missing', () => {
  const tracks = [{ id: 'a' }, { id: 'b' }];
  const base = { volume: {}, mute: {}, solo: null, singing: 'a' };
  assert.deepEqual(mixGains(tracks, { ...base, mode: 'solo' }, { learning: true }), { a: 0.8, b: 0 });
  assert.deepEqual(mixGains(tracks, { ...base, mode: 'pred' }, { learning: true }), { a: 0.8, b: 0.2 });
  assert.deepEqual(mixGains(tracks, { ...base, mode: 'miss' }, { learning: true }), { a: 0, b: 0.8 });
  // Learning modes only apply where asked; mute and solo always apply.
  assert.deepEqual(mixGains(tracks, { ...base, mode: 'solo' }), { a: 0.8, b: 0.8 });
  assert.deepEqual(mixGains(tracks, { ...base, mute: { a: true } }), { a: 0, b: 0.8 });
  assert.deepEqual(mixGains(tracks, { ...base, solo: 'b', mute: { b: true } }), { a: 0, b: 0.8 });
});

test('karaoke lifts your part over a quiet band, only when your part is playing', () => {
  assert.deepEqual(karaokeGains({ a: 0.8, b: 0.2 }, 'a', 'pred'), { a: 1.4, b: 0.2, band: 0.2 });
  assert.deepEqual(karaokeGains({ a: 0, b: 0.8 }, 'a', 'miss'), { a: 0, b: 0.8 });
  assert.deepEqual(karaokeGains({ a: 0.8 }, undefined, 'pred'), { a: 0.8 });
});
