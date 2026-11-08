// Tests for the glue between the sheet-music app and the counter-melody generator.
import test from 'node:test';
import assert from 'node:assert/strict';
import abcjs from 'abcjs';
import { scoreToAbc } from '../src/melodyToAbc.js';
import { secondsToBeats, beatsToSeconds } from '../src/noteModel.js';
import { requestCounterMelody } from '../src/counterMelody.js';
const n = (midi, start, duration) => ({ midi, start, duration });

test('seconds <-> beats round-trips on the sixteenth grid', () => {
  const seconds = [n(60, 0, 0.5), n(62, 0.51, 0.49), n(64, 1, 0.01)];
  const beats = secondsToBeats(seconds, 120);
  assert.deepEqual(beats, [n(60, 0, 1), n(62, 1, 1)]);   // too-short note dropped, timing snapped
  assert.deepEqual(beatsToSeconds(beats, 120), [n(60, 0, 0.5), n(62, 0.5, 0.5)]);
});

test('two-part score aligns bars and parses cleanly', () => {
  const melody = [n(60, 0, 0.5), n(62, 0.5, 0.5), n(64, 1, 0.5), n(65, 1.5, 0.5), n(67, 2, 2)];
  const counter = [n(52, 0, 1), n(55, 1, 1)];
  const { abc } = scoreToAbc([
    { name: 'Melody', clef: 'treble', notes: melody },
    { name: 'Counter "x"', clef: 'treble-8', notes: counter },
  ], { bpm: 120, key: 'C' });
  assert.match(abc, /V:P2 clef=treble-8 name="Counter x"/);
  const parsed = abcjs.parseOnly(abc)[0];
  assert.equal(parsed.warnings, undefined);
  const staves = parsed.lines.filter(l => l.staff);
  assert.ok(staves.every(l => l.staff.length === 2));
  // Both voices fill the same number of beats (padding rests on the shorter one).
  const total = staff => staves.flatMap(l => l.staff[staff].voices.flat()).filter(e => e.el_type === 'note')
    .reduce((sum, e) => sum + e.duration, 0);
  assert.equal(total(0), total(1));
  assert.equal(total(0), 2);
});

test('scoreToAbc validates parts', () => {
  assert.throws(() => scoreToAbc([]));
  assert.throws(() => scoreToAbc([{ clef: 'alto', notes: [n(60, 0, 1)] }]));
  assert.throws(() => scoreToAbc([{ clef: 'treble', notes: [n(60, 0, 1), n(62, 0.5, 1)] }]));
});

test('requestCounterMelody sends beats and returns seconds', async () => {
  let sent;
  const fakeFetch = async (url, init) => {
    sent = { url, body: JSON.parse(init.body) };
    return { ok: true, status: 200, json: async () => ({ counter: [n(55, 0, 2)], voice: 'alto', clef: 'treble' }) };
  };
  const result = await requestCounterMelody([n(60, 0, 0.5), n(62, 0.5, 0.5)], { bpm: 120, meter: '4/4', key: 'C', voice: 'alto' }, fakeFetch);
  assert.equal(sent.url, '/api/counter');
  assert.deepEqual(sent.body.notes, [n(60, 0, 1), n(62, 1, 1)]);
  assert.deepEqual(result.counter, [n(55, 0, 1)]);
  assert.deepEqual(result.counterBeats, [n(55, 0, 2)]);
});

test('requestCounterMelody explains a missing server', async () => {
  await assert.rejects(requestCounterMelody([n(60, 0, 1)], { bpm: 120, meter: '4/4', key: 'C' },
    async () => { throw new TypeError('fetch failed'); }), /npm run api/);
  await assert.rejects(requestCounterMelody([n(60, 0, 1)], { bpm: 120, meter: '4/4', key: 'C' },
    async () => ({ ok: false, status: 400, json: async () => ({ error: 'Unknown voice' }) })), /Unknown voice/);
});
