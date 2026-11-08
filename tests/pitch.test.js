import test from 'node:test';
import assert from 'node:assert/strict';
import { detectPitch, frequencyToMidi, framesToMelody } from '../src/pitch.js';
import { melodyToAbc } from '../src/melodyToAbc.js';
function tone(frequency, rate, harmonics = false) {
  return Float32Array.from({ length: 4096 }, (_, i) => {
    const phase = 2 * Math.PI * frequency * i / rate;
    return 0.2 * Math.sin(phase) + (harmonics ? 0.3 * Math.sin(2 * phase) + 0.1 * Math.sin(3 * phase) : 0);
  });
}
for (const rate of [44100, 48000]) {
  test(`detects low/high pitches and strong harmonics at ${rate}Hz`, () => {
    for (const frequency of [82.41, 130.81, 261.63, 440, 880, 1046.5]) {
      for (const harmonics of [false, true]) {
        const result = detectPitch(tone(frequency, rate, harmonics), rate);
        assert.ok(result.frequency && Math.abs(12 * Math.log2(result.frequency / frequency)) < 0.1, `${frequency}: ${result.frequency}`);
      }
    }
  });
}
test('rejects silence and deterministic noise', () => {
  assert.equal(detectPitch(new Float32Array(4096), 48000).frequency, null);
  let seed = 42;
  const noise = Float32Array.from({ length: 4096 }, () => { seed = (seed * 1664525 + 1013904223) >>> 0; return (seed / 2 ** 32 - 0.5) * 0.5; });
  assert.equal(detectPitch(noise, 48000).frequency, null);
});
test('audio tones become timed score notes with a rest', () => {
  const frames = [];
  for (let i = 0; i < 70; i++) {
    const frequency = i < 10 || (i >= 35 && i < 45) ? null : i < 35 ? 261.63 : 329.63;
    const detected = detectPitch(frequency ? tone(frequency, 48000, true) : new Float32Array(4096), 48000);
    frames.push({ time: i * 0.04, midi: detected.frequency ? frequencyToMidi(detected.frequency) : null });
  }
  const notes = framesToMelody(frames, 2.8, 120);
  assert.deepEqual(notes.map(n => n.midi), [60, 64]);
  assert.equal(notes[0].start, 0);
  assert.ok(notes[1].start > notes[0].duration);
  assert.match(melodyToAbc(notes).abc, /z/);
});
test('suppresses pitch glitches and keeps repeated notes without a short breath rest', () => {
  const frames = Array.from({ length: 50 }, (_, i) => ({ time: i * 0.04, midi: i >= 20 && i < 26 ? null : i === 10 ? 72 : 60 }));
  const notes = framesToMelody(frames, 2, 120);
  assert.deepEqual(notes.map(n => n.midi), [60, 60]);
  assert.equal(notes[1].start, notes[0].duration);
});
test('absorbs a short breath between different pitches before analysis and quantization', () => {
  const frames = Array.from({ length: 50 }, (_, i) => ({ time: i * 0.04, midi: i < 20 ? 60 : i < 25 ? null : 64 }));
  const original = structuredClone(frames);
  for (const bpm of [null, 80, 120, 160]) {
    const notes = framesToMelody(frames, 2, bpm);
    assert.deepEqual(notes.map(n => n.midi), [60, 64]);
    assert.equal(notes[0].start + notes[0].duration, notes[1].start);
    assert.equal(notes[1].start, Math.round(1 / (60 / (bpm ?? 120) / 4)) * (60 / (bpm ?? 120) / 4));
  }
  assert.deepEqual(frames, original);
});
test('does not extend the final note through trailing silence', () => {
  const frames = Array.from({ length: 30 }, (_, i) => ({ time: i * 0.04, midi: i < 20 ? 60 : null }));
  const notes = framesToMelody(frames, 1.2);
  assert.equal(notes.length, 1);
  assert.ok(Math.abs(notes[0].duration - 0.8) < 1e-8);
});
test('silence produces no notes', () => {
  assert.deepEqual(framesToMelody([{ time: 0, midi: null }], 1, 120), []);
});
