import test from 'node:test';
import assert from 'node:assert/strict';
import abcjs from 'abcjs';
import { analyzeMelody, spellPitch, KEYS } from '../src/analyzeMelody.js';
import { melodyToAbc } from '../src/melodyToAbc.js';
import { framesToMelody } from '../src/pitch.js';
const scale = (pitches, bpm = 120) => pitches.map((midi,i) => ({ midi, start:i*60/bpm, duration:60/bpm }));
test('estimates steady tempos without relying on preset BPM', () => {
  for (const bpm of [80,100,120,150]) {
    const notes = scale([60,62,64,65,67,69,71,72], bpm);
    // Small onset deviations simulate imperfect singing.
    notes.forEach((n,i) => { n.start += i % 2 * 0.008; n.duration -= 0.01; });
    assert.ok(Math.abs(analyzeMelody(notes).bpm - bpm) <= 1);
  }
});
test('recognizes simple phrase and compound beat groupings', () => {
  assert.equal(analyzeMelody(scale([60,62,64,65,67,69,71,72])).meter, '4/4');
  assert.equal(analyzeMelody(scale([60,62,64,65,67,69,71,72,72])).meter, '3/4');
  let start = 0;
  const notes = [1.5,.5,.5,.5,1.5,.5,.5,.5].map((beats,i) => {
    const note = { midi:60+i%5, start, duration:beats*.5 }; start += note.duration; return note;
  });
  assert.equal(analyzeMelody(notes).meter, '6/8');
});
test('estimates flat, sharp and minor keys from complete scales', () => {
  for (const [pitches,key] of [ [[65,67,69,70,72,74,76,77],'F'], [[67,69,71,72,74,76,78,79],'G'], [[69,71,72,74,76,77,79,81],'Am'] ]) {
    assert.equal(analyzeMelody(scale(pitches)).key,key);
  }
});
test('spells Bb in F, F# in G, and supports explicit enharmonic overrides', () => {
  assert.deepEqual(spellPitch(70,'F'),{pc:10,letter:'B',alter:-1,octave:4});
  assert.equal(spellPitch(66,'G').alter,1);
  assert.equal(spellPitch(70,'F','sharps').letter,'A');
  const result = melodyToAbc(scale([70,71,70]), { key:'F' });
  assert.match(result.abc,/K:F clef=treble/);
  assert.match(result.abc,/\nB4 =B4 _B4/); // Bb is in the key signature; the natural and the restored flat are marked
  assert.equal(abcjs.parseOnly(result.abc)[0].warnings,undefined);
});
test('every spelling preserves MIDI pitch, including B# octave crossings', () => {
  const naturals = { C:0,D:2,E:4,F:5,G:7,A:9,B:11 };
  for (const key of KEYS) for (let midi=24; midi<=96; midi++) {
    const {letter,alter,octave} = spellPitch(midi,key);
    assert.equal((octave+1)*12+naturals[letter]+alter,midi);
  }
  assert.equal(spellPitch(60,'C#').octave,3);
});
test('keeps raw recording timing for estimation before quantizing', () => {
  const frames = Array.from({length:15},(_,i)=>({time:.04*i,midi:60}));
  const raw = framesToMelody(frames,.6);
  assert.ok(Math.abs(raw[0].duration-.6)<1e-8);
  assert.match(analyzeMelody(raw).notice,/Short melody/);
  assert.equal(analyzeMelody([]).meter,'4/4');
});
