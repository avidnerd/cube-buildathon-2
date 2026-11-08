// Recording. Two modes:
//  - free (default): just sing. After stopping, tempo, time signature and key
//    are estimated from the notes (src/analyzeMelody.js); all are editable later.
//  - count-in: a bar of clicks at a chosen tempo first (docs/SPEC.md), so the
//    beat grid is known. Optionally keep clicking while you sing.
// While recording, a cheap YIN detector draws a live trace; after stopping,
// Spotify Basic Pitch does the real transcription.
import { useEffect, useRef, useState } from 'react';
import { detectPitch, frequencyToMidi } from './pitch.js';
import { notesFromSeconds } from './noteModel.js';
import { analyzeMelody } from './analyzeMelody.js';

const MAX_SECONDS = 60;
const MIC_ERRORS = {
  NotAllowedError: 'Microphone permission was denied. Allow it in your browser’s site settings, then try again.',
  NotFoundError: 'No microphone found. Connect one and try again.',
  NotReadableError: 'The microphone is busy. Close other recording apps and try again.',
};

function click(ctx, time, accent) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.frequency.value = accent ? 1760 : 1320;
  gain.gain.setValueAtTime(0.0001, time);
  gain.gain.exponentialRampToValueAtTime(0.35, time + 0.002);
  gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.04);
  osc.connect(gain).connect(ctx.destination);
  osc.start(time); osc.stop(time + 0.05);
}

/** status: ready | count | rec | processing.
 * `onTake(take)` gets { notes (spec, beats), seconds, bpm, meter, key, notice }. */
export function useRecorder({ bpm, meter, beatsPerBar, countIn, clickOn, onTake }) {
  const session = useRef(null);
  const [status, setStatus] = useState('ready');
  const [live, setLive] = useState({ beat: -beatsPerBar, level: 0, frames: [] });
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('');
  const clickRef = useRef(clickOn);
  clickRef.current = clickOn;
  const takeRef = useRef(onTake);
  takeRef.current = onTake;

  function release(s) {
    clearInterval(s.timer);
    if (s.recorder?.state === 'recording') s.recorder.stop();
    s.stream?.getTracks().forEach(t => t.stop());
    s.source?.disconnect();
    if (s.ctx && s.ctx.state !== 'closed') s.ctx.close().catch(() => {});
    s.worker?.terminate();
  }
  useEffect(() => () => { if (session.current) release(session.current); session.current = null; }, []);

  function finish(s, text = '') {
    if (session.current !== s) return;
    session.current = null;
    release(s);
    setStatus('ready'); setMessage(text); setProgress(0);
    setLive(l => ({ ...l, level: 0 }));
  }

  async function transcribe(s) {
    try {
      const blob = new Blob(s.chunks, { type: s.recorder.mimeType });
      if (!blob.size) throw new Error('No audio was captured.');
      const decoded = await s.ctx.decodeAudioData(await blob.arrayBuffer());
      if (session.current !== s) return;
      const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * 22050), 22050);
      const src = offline.createBufferSource();
      src.buffer = decoded; src.connect(offline.destination); src.start();
      const samples = (await offline.startRendering()).getChannelData(0);
      if (session.current !== s) return;
      s.ctx.close().catch(() => {});
      s.worker = new Worker(new URL('./basicPitch.worker.js', import.meta.url), { type: 'module' });
      s.worker.onmessage = ({ data }) => {
        if (session.current !== s) return;
        if (data.type === 'progress') setProgress(Math.round(data.progress * 100));
        else if (data.type === 'complete') {
          // Count-in: shift so beat 0 is the first downbeat. Free: Basic Pitch already trimmed leading silence.
          const seconds = !s.countIn ? data.notes : data.notes.map(n => ({ ...n, start: n.start - s.downbeatOffset }))
            .filter(n => n.start + n.duration > 0.05)
            .map(n => (n.start < 0 ? { ...n, duration: n.duration + n.start, start: 0 } : n));
          const estimate = analyzeMelody(seconds);
          const take = s.countIn
            ? { bpm, meter, key: estimate.key, notice: 'Key is an estimate; you can change it in Settings.' }
            : { bpm: estimate.bpm, meter: estimate.meter, key: estimate.key, notice: estimate.notice.replace('You can adjust all three below.', 'You can adjust all three in Settings.') };
          const notes = seconds.length ? notesFromSeconds(seconds, take.bpm) : [];
          if (notes.length < seconds.length) take.notice += ' Very brief notes were left off the timing grid.';
          finish(s, notes.length ? '' : 'No clear notes heard. Sing a little louder, closer to the mic.');
          if (notes.length) takeRef.current({ ...take, notes, seconds });
        } else if (data.type === 'error') finish(s, `Transcription failed: ${data.message}`);
      };
      s.worker.onerror = () => finish(s, 'Could not run Basic Pitch. Refresh the page and try again.');
      const modelUrl = new URL(`${import.meta.env.BASE_URL}models/basic-pitch/model.json`, window.location.origin).href;
      s.worker.postMessage({ samples, modelUrl, keepOrigin: s.countIn }, [samples.buffer]);
    } catch (error) {
      finish(s, `Could not transcribe this take: ${error.message}`);
    }
  }

  async function start() {
    if (session.current) return;
    const s = { chunks: [], frames: [], countIn };
    session.current = s;
    setMessage(''); setStatus(countIn ? 'count' : 'rec');
    setLive({ beat: countIn ? -beatsPerBar : 0, level: 0, frames: [] });
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw new Error('Recording needs Chrome or Safari on localhost or HTTPS.');
      s.ctx = new AudioContext();
      await s.ctx.resume();
      s.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
      if (session.current !== s) { s.stream.getTracks().forEach(t => t.stop()); return; }
      s.source = s.ctx.createMediaStreamSource(s.stream);
      const analyser = s.ctx.createAnalyser(); analyser.fftSize = 2048;
      s.source.connect(analyser);
      const buffer = new Float32Array(analyser.fftSize);
      s.recorder = new MediaRecorder(s.stream);
      s.recorder.ondataavailable = e => { if (session.current === s && e.data.size) s.chunks.push(e.data); };
      s.recorder.onstop = () => { if (session.current === s) transcribe(s); };
      s.recorder.start(250);
      const recordStart = s.ctx.currentTime;
      const spb = 60 / bpm;
      const t0 = recordStart + 0.15;
      s.downbeat = countIn ? t0 + beatsPerBar * spb : recordStart;
      s.downbeatOffset = s.downbeat - recordStart;
      let nextClick = 0;
      s.timer = setInterval(() => {
        if (session.current !== s) return;
        const now = s.ctx.currentTime;
        // Schedule clicks a little ahead: always during the count-in, then only if Click is on.
        while (countIn && t0 + nextClick * spb < now + 0.2) {
          if (nextClick < beatsPerBar || clickRef.current) click(s.ctx, t0 + nextClick * spb, nextClick % beatsPerBar === 0);
          nextClick++;
        }
        const beat = (now - s.downbeat) / spb;
        analyser.getFloatTimeDomainData(buffer);
        let energy = 0; for (const v of buffer) energy += v * v;
        const level = Math.min(1, Math.sqrt(energy / buffer.length) * 6);
        if (beat >= 0) {
          setStatus(st => (st === 'count' ? 'rec' : st));
          const { frequency } = detectPitch(buffer, s.ctx.sampleRate);
          if (frequency) s.frames.push({ beat, pitch: frequencyToMidi(frequency) });
        }
        setLive({ beat, level, frames: s.frames });
        if (now - s.downbeat > MAX_SECONDS || document.hidden) stop();
      }, 50);
    } catch (error) {
      finish(s, MIC_ERRORS[error.name] || error.message || 'Could not start the microphone.');
    }
  }

  function stop() {
    const s = session.current;
    if (!s) return;
    // Stopping during the count-in (or before the mic started) cancels the take.
    if (!s.recorder || s.recorder.state !== 'recording' || s.ctx.currentTime < s.downbeat + 0.3) { finish(s, s.countIn ? '' : 'That was too short to transcribe.'); return; }
    clearInterval(s.timer);
    setStatus('processing'); setProgress(0);
    s.recorder.stop();
    s.stream.getTracks().forEach(t => t.stop());
    s.source.disconnect();
  }

  return { status, live, progress, message, start, stop, cancel: () => session.current && finish(session.current) };
}
