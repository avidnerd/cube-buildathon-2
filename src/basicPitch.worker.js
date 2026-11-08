import * as tf from '@tensorflow/tfjs';
import { transcribeSamples } from './basicPitchEngine.js';

self.onmessage = async ({ data }) => {
  try {
    // CPU runs in this dedicated worker, keeping cancel and the UI responsive.
    await tf.setBackend('cpu');
    await tf.ready();
    const notes = await transcribeSamples(data.samples, data.modelUrl,
      progress => self.postMessage({ type: 'progress', progress }), { keepOrigin: !!data.keepOrigin });
    self.postMessage({ type: 'complete', notes });
  } catch (error) {
    self.postMessage({ type: 'error', message: error.message || 'Basic Pitch could not transcribe this recording.' });
  }
};
