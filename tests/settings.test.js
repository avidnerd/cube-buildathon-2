import test from 'node:test';
import assert from 'node:assert/strict';
import { applySettings, basisOf, staleCounters } from '../src/arrangement.js';
import { makeNote, parseNoteEdits } from '../src/noteModel.js';

const project = () => ({
  key: 'G major', tempo: 120, timeSignature: '4/4',
  tracks: [
    { id: 'melody', role: 'melody', notes: [makeNote(60, 0, 1), makeNote(62, 1, 1)],
      recording: [{ midi: 60, start: 0, duration: 0.5 }, { midi: 62, start: 0.5, duration: 0.5 }] },
  ],
});

test('a tempo correction re-reads the recorded rhythm', () => {
  const next = applySettings(project(), { tempo: 60 });
  assert.equal(next.tempo, 60);
  assert.deepEqual(next.tracks[0].notes.map(n => [n.pitch, n.start, n.duration]), [[60, 0, 0.5], [62, 0.5, 0.5]]);
});

test('without raw timing (hand-edited or demo), tempo only changes speed', () => {
  const p = project();
  p.tracks[0].recording = null;
  assert.deepEqual(applySettings(p, { tempo: 60 }).tracks[0].notes, p.tracks[0].notes);
});

test('counters go stale when the melody, key or meter change, not the tempo label', () => {
  const p = project();
  p.tracks.push({ id: 'counter-alto', role: 'counter', voice: 'alto', notes: [], basis: basisOf(p) });
  assert.equal(staleCounters(p).length, 0);
  assert.equal(staleCounters({ ...p, key: 'E minor' }).length, 1);
  assert.equal(staleCounters({ ...p, timeSignature: '3/4' }).length, 1);
  assert.equal(staleCounters(applySettings(p, { tempo: 60 })).length, 1); // rhythm re-read
  assert.equal(staleCounters({ ...p, spelling: 'flats', title: 'x' }).length, 0);
});

test('note editor validates and keeps ornaments of unchanged notes', () => {
  const old = [makeNote(60, 0, 1, { ornaments: ['trill'] })];
  const notes = parseNoteEdits('[{"pitch":60,"start":0,"duration":2},{"pitch":64,"start":2,"duration":1}]', old);
  assert.deepEqual(notes[0].ornaments, ['trill']);
  assert.equal(notes[0].duration, 2);
  assert.equal(notes[1].locked, false);
  for (const bad of ['nope', '[]', '[{"pitch":60.5,"start":0,"duration":1}]', '[{"pitch":60,"start":-1,"duration":1}]',
    '[{"pitch":60,"start":0,"duration":2},{"pitch":62,"start":1,"duration":1}]'])
    assert.throws(() => parseNoteEdits(bad));
});
