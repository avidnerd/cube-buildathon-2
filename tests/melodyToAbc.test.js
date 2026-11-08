import test from 'node:test';
import assert from 'node:assert/strict';
import abcjs from 'abcjs';
import { melodyToAbc } from '../src/melodyToAbc.js';
const n = (midi, start, duration) => ({ midi, start, duration });
const body = result => result.abc.split('\n').slice(6).join('\n').trim();

test('quarter notes and final measure padding', () => {
  assert.equal(body(melodyToAbc([n(60, 0, 0.5)])), '=C4 z12 |]');
});
test('preserves initial and internal silence', () => {
  assert.equal(body(melodyToAbc([n(60, 0.5, 0.5), n(62, 1.5, 0.5)])), 'z4 =C4 z4 =D4 |]');
});
test('ties notes crossing bars without tying rests', () => {
  assert.equal(body(melodyToAbc([n(67, 1.5, 1)])), 'z12 =G4- | =G4 z12 |]');
});
test('handles octaves and resets accidentals', () => {
  const result = melodyToAbc([n(66, 0, 0.5), n(65, 0.5, 0.5), n(48, 1, 0.5), n(84, 1.5, 0.5)]);
  assert.equal(body(result), "^F4 =F4 =C,4 =c'4 |]");
  const parsed = abcjs.parseOnly(result.abc)[0];
  assert.equal(parsed.warnings, undefined);
  const notes = parsed.lines.flatMap(l => l.staff?.flatMap(s => s.voices.flat()) || []).filter(e => e.pitches);
  assert.equal(notes[0].pitches[0].accidental, 'sharp');
  assert.equal(notes[1].pitches[0].accidental, 'natural');
});
test('tempo, meter, and bass clef are honored', () => {
  const result = melodyToAbc([n(48, 0, 3)], { bpm: 60, meter: '3/4', clef: 'bass' });
  assert.equal(body(result), '=C,12 |]');
  assert.match(result.abc, /K:C clef=bass/);
  assert.equal(body(melodyToAbc([n(60, 0, 1.5)], { meter: '6/8' })), '=C12 |]');
});
test('sorts without mutating and reports quantization', () => {
  const notes = [n(62, 0.51, 0.49), n(60, 0, 0.49)];
  const copy = structuredClone(notes);
  const result = melodyToAbc(notes);
  assert.deepEqual(notes, copy);
  assert.equal(result.warnings.length, 1);
  assert.equal(body(result), '=C4 =D4 z8 |]');
});
test('rejects malformed, overlapping, too short, and unbounded input', () => {
  for (const notes of [null, [], [null], [n(60.5, 0, 1)], [n(128, 0, 1)], [n(60, -1, 1)], [n(60, 0, 0)], [n(60, 0, Infinity)], [n(60, 600, 1)], [n(60, 0, 0.01)], [n(60, 0, 1), n(62, 0.5, 1)]])
    assert.throws(() => melodyToAbc(notes));
  for (const options of [{ bpm: 0 }, { bpm: NaN }, { meter: '7/8' }, { clef: 'alto' }])
    assert.throws(() => melodyToAbc([n(60, 0, 1)], options));
});
test('title cannot inject ABC headers', () => {
  assert.match(melodyToAbc([n(60, 0, 1)], { title: 'Hello\nK:G\n%%test' }).abc, /T:Hello K:G test\nM:/);
});
test('multi-bar duration is conserved by the notation parser', () => {
  const result = melodyToAbc([n(60, 0, 10)]);
  const parsed = abcjs.parseOnly(result.abc)[0];
  assert.equal(parsed.warnings, undefined);
  const notes = parsed.lines.flatMap(l => l.staff?.flatMap(s => s.voices.flat()) || []).filter(e => e.el_type === 'note');
  assert.equal(notes.reduce((sum, e) => sum + e.duration, 0), 5);
  assert.equal(notes.filter(e => e.pitches?.[0].startTie).length, 4);
});
