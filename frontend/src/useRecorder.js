// Recording. Two modes:
//  - free (default): just sing. After stopping, tempo, time signature and key
//    are estimated from the notes (src/analyzeMelody.js); all are editable later.
//  - count-in: a bar of clicks at a chosen tempo first (docs/SPEC.md), so the
//    beat grid is known. Optionally keep clicking while you sing.
// While recording, a cheap YIN detector draws a live trace; after stopping, the
// harmony engine (backend/harmony) does the real transcription. Song files go
// the same way, through upload().
import { useEffect, useRef, useState } from 'react';
import { detectPitch, frequencyToMidi } from './pitch.js';
import { analyzeAudio, takeFromAnalysis } from './harmonyApi.js';
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
 * `onTake(take)` gets { notes (spec, beats), timing, backend, bpm, meter, key, notice }. */
export function useRecorder({ bpm, meter, beatsPerBar, countIn, clickOn, onTake }) {
  const session = useRef(null);
  const [status, setStatus] = useState('ready');
  const [live, setLive] = useState({ beat: -beatsPerBar, level: 0, frames: [] });
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
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
  }
  useEffect(() => () => { if (session.current) release(session.current); session.current = null; }, []);

  function finish(s, text = '') {
    if (session.current !== s) return;
    session.current = null;
    release(s);
    setStatus('ready'); setMessage(text); setProgress(0);
    setLive(l => ({ ...l, level: 0 }));
  }

  /** Send audio to the harmony engine and turn the answer into a take. */
  async function analyze(s, buffer, { source, bpm: knownBpm, offset, fixedMeter, label }) {
    const bar = fixedMeter ? beatsPerBar : 4;
    const answer = await analyzeAudio(buffer, { source, bpm: knownBpm, offset, bpb: bar }, {
      isCancelled: () => session.current !== s,
      onStage: ({ stage, done, total }) => {
        if (session.current !== s) return;
        setStage(stage || 'Finishing up');
        setProgress(total ? Math.round(done / total * 100) : 0);
      },
    });
    if (!answer || session.current !== s) return;
    const { result, jobId } = answer;
    const seconds = result.notes.map(n => ({ midi: n.pitch, start: n.t0, duration: n.t1 - n.t0 }));
    const estimate = analyzeMelody(seconds);
    const takeMeter = fixedMeter ?? (source === 'upload' ? '4/4' : estimate.meter);
    const take = takeFromAnalysis(result, jobId, takeMeter);
    const what = result.has_music ? 'Voice and band separated, chords heard from the band.' : 'Voice only: chords are worked out from your melody.';
    finish(s);
    takeRef.current({ ...take, meter: takeMeter, key: estimate.key, label,
      notice: `${what} Tempo and key are estimates; you can change them in Settings.` });
  }

  async function transcribe(s) {
    try {
      const blob = new Blob(s.chunks, { type: s.recorder.mimeType });
      if (!blob.size) throw new Error('No audio was captured.');
      const decoded = await s.ctx.decodeAudioData(await blob.arrayBuffer());
      if (session.current !== s) return;
      await analyze(s, decoded, s.countIn
        ? { source: 'mic', bpm, offset: s.downbeatOffset, fixedMeter: meter }
        : { source: 'mic' });
    } catch (error) {
      finish(s, error.message);
    }
  }

  /** A song file: the engine separates the voice, finds the beat and hears the chords. */
  async function upload(file) {
    if (session.current || !file) return;
    const s = { chunks: [], frames: [], countIn: false };
    session.current = s;
    setMessage(''); setStage('Reading the file'); setProgress(0); setStatus('processing');
    try {
      s.ctx = new AudioContext();
      const decoded = await s.ctx.decodeAudioData(await file.arrayBuffer());
      if (session.current !== s) return;
      await analyze(s, decoded, { source: 'upload', label: file.name });
    } catch (error) {
      finish(s, error.name === 'EncodingError' ? 'Could not read that audio file. Try an MP3, M4A or WAV.' : error.message);
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
    setStatus('processing'); setProgress(0); setStage('Sending your take');
    s.recorder.stop();
    s.stream.getTracks().forEach(t => t.stop());
    s.source.disconnect();
  }

  return { status, live, progress, stage, message, start, stop, upload, cancel: () => session.current && finish(session.current) };
}
