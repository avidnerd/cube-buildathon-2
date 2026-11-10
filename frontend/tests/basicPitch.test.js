import test from 'node:test';
import assert from 'node:assert/strict';
import { basicPitchNotesToMelody } from '../src/basicPitchNotes.js';
import { melodyToAbc } from '../src/melodyToAbc.js';
const event = (pitchMidi, startTimeSeconds, durationSeconds, amplitude = .8) => ({pitchMidi,startTimeSeconds,durationSeconds,amplitude});
test('Basic Pitch adapter trims leading silence and smooths breaths', () => {
  const input = [event(60,.5,.5),event(64,1.2,.5)];
  const before = structuredClone(input);
  const notes = basicPitchNotesToMelody(input,2);
  assert.equal(notes[0].start,0);
  assert.equal(notes[0].duration,notes[1].start);
  assert.deepEqual(input,before);
  assert.doesNotThrow(() => melodyToAbc(notes));
});
test('overlapping detections become one voice using confidence', () => {
  const notes = basicPitchNotesToMelody([event(60,0,1,.9),event(72,0,1,.3),event(64,.8,.8,.95)],2);
  assert.deepEqual(notes.map(n=>n.midi),[60,64]);
  assert.equal(notes[0].duration,.8);
  assert.doesNotThrow(() => melodyToAbc(notes));
});
test('keeps repeated notes and long rests; rejects glitches and invalid events', () => {
  const notes = basicPitchNotesToMelody([event(60,0,.5),event(60,.7,.5),event(64,1.6,.5),event(80,2.2,.05),event(100,2.4,.2),event(NaN,3,.5)],3);
  assert.deepEqual(notes.map(n=>n.midi),[60,60,64]);
  assert.equal(notes[0].duration,.7);
  assert.ok(notes[2].start > notes[1].start + notes[1].duration);
  assert.deepEqual(basicPitchNotesToMelody([],3),[]);
});
