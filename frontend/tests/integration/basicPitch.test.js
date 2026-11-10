import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import * as tf from '@tensorflow/tfjs';
import { transcribeSamples } from '../../src/basicPitchEngine.js';
import { melodyToAbc } from '../../src/melodyToAbc.js';

test('real Spotify model transcribes generated A4 audio into a score', async () => {
  await tf.setBackend('cpu'); await tf.ready();
  const root = new URL('../../node_modules/@spotify/basic-pitch/model/', import.meta.url);
  const json = JSON.parse(await readFile(new URL('model.json',root),'utf8'));
  const bytes = await readFile(new URL('group1-shard1of1.bin',root));
  const model = tf.loadGraphModel(tf.io.fromMemory({ modelTopology:json.modelTopology,
    weightSpecs:json.weightsManifest.flatMap(m=>m.weights), weightData:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength) }));
  const samples = Float32Array.from({length:22050*2},(_,i)=> {
    const t=i/22050;
    if (t<.2 || t>1.8) return 0;
    const envelope = Math.min(1,(t-.2)/.03,(1.8-t)/.03);
    return envelope*(.3*Math.sin(2*Math.PI*440*t)+.1*Math.sin(2*Math.PI*880*t));
  });
  const progress=[];
  const notes = await transcribeSamples(samples,model,p=>progress.push(p));
  assert.ok(notes.some(n=>n.midi===69),JSON.stringify(notes));
  assert.equal(progress.at(-1),1);
  assert.doesNotThrow(()=>melodyToAbc(notes));
  assert.deepEqual(await transcribeSamples(new Float32Array(22050),model),[]);
  (await model).dispose();
});
