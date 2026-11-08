import React, { useEffect, useRef, useState } from 'react';

export function SingRecorder({ onMelody, onBusy }) {
  const session = useRef(null);
  const [status, setStatus] = useState('idle');
  const [message, setMessage] = useState('Ready when you are.');
  const [live, setLive] = useState({ level: 0, elapsed: 0 });
  const [progress, setProgress] = useState(0);
  function release(recording) {
    clearInterval(recording.timer);
    if (recording.recorder?.state === 'recording') recording.recorder.stop();
    recording.stream?.getTracks().forEach(track => track.stop());
    recording.source?.disconnect();
    if (recording.context?.state !== 'closed') recording.context?.close().catch(() => {});
    recording.worker?.terminate();
    recording.chunks = [];
  }
  useEffect(() => () => {
    const recording = session.current;
    session.current = null;
    if (recording) release(recording);
  }, []);
  function finish(recording, text) {
    if (session.current !== recording) return;
    session.current = null;
    release(recording);
    onBusy(false); setStatus('idle'); setMessage(text);
    setLive({ level: 0, elapsed: 0 });
  }
  async function transcribe(recording) {
    if (session.current !== recording) return;
    try {
      const blob = new Blob(recording.chunks, { type: recording.recorder.mimeType });
      recording.chunks = [];
      if (!blob.size) throw new Error('No audio captured. Try recording again.');
      const decoded = await recording.context.decodeAudioData(await blob.arrayBuffer());
      if (session.current !== recording) return;
      if (decoded.duration > 61) throw new Error('Recording exceeded 60 seconds. Please try a shorter melody.');
      const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * 22050), 22050);
      const source = offline.createBufferSource();
      source.buffer = decoded; source.connect(offline.destination); source.start();
      const resampled = await offline.startRendering();
      if (session.current !== recording) return;
      await recording.context.close();
      const samples = resampled.getChannelData(0);
      const worker = new Worker(new URL('./basicPitch.worker.js', import.meta.url), { type: 'module' });
      recording.worker = worker;
      worker.onmessage = ({ data }) => {
        if (session.current !== recording) return;
        if (data.type === 'progress') {
          setProgress(Math.round(data.progress * 100));
          setMessage('Basic Pitch is finding the notes in your recording…');
        } else if (data.type === 'complete') {
          try {
            if (data.notes.length) onMelody(data.notes);
            finish(recording, data.notes.length ? `${data.notes.length} notes transcribed with Spotify Basic Pitch.`
              : 'No clear notes found. Try singing a little louder in a quiet room.');
          } catch (error) { finish(recording, error.message); }
        } else if (data.type === 'error') finish(recording, `Transcription failed: ${data.message} Please try again.`);
      };
      worker.onerror = () => finish(recording, 'Could not run Basic Pitch. Refresh the page and try again.');
      const modelUrl = new URL(`${import.meta.env.BASE_URL}models/basic-pitch/model.json`, window.location.origin).href;
      worker.postMessage({ samples, modelUrl }, [samples.buffer]);
    } catch (error) {
      finish(recording, `Could not transcribe this recording: ${error.message}`);
    }
  }
  function stop() {
    const recording = session.current;
    if (!recording) return;
    if (!recording.recorder || recording.recorder.state !== 'recording') {
      finish(recording, 'Cancelled.'); return;
    }
    clearInterval(recording.timer);
    setStatus('processing'); setProgress(0); setLive({ level: 0, elapsed: 0 });
    setMessage('Preparing audio and loading Basic Pitch…');
    recording.recorder.stop();
    recording.stream.getTracks().forEach(track => track.stop());
    recording.source.disconnect();
  }
  async function start() {
    if (session.current) return;
    const recording = { chunks: [] };
    session.current = recording;
    setStatus('requesting'); onBusy(true); setMessage('Allow microphone access to begin.');
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw new Error('Recording requires a supported browser on localhost or HTTPS. Try Chrome or Safari.');
      recording.context = new AudioContext();
      await recording.context.resume();
      if (session.current !== recording) return;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false });
      if (session.current !== recording) { stream.getTracks().forEach(track => track.stop()); return; }
      recording.stream = stream;
      recording.source = recording.context.createMediaStreamSource(stream);
      const analyser = recording.context.createAnalyser(); analyser.fftSize = 2048;
      recording.source.connect(analyser);
      const buffer = new Float32Array(analyser.fftSize);
      recording.recorder = new MediaRecorder(stream);
      recording.recorder.ondataavailable = event => {
        if (session.current === recording && event.data.size) recording.chunks.push(event.data);
      };
      recording.recorder.onstop = () => transcribe(recording);
      recording.recorder.onerror = () => finish(recording, 'Audio recording failed. Check your microphone and try again.');
      recording.recorder.start(250);
      recording.start = performance.now();
      setStatus('recording'); setMessage('Sing or hum, then press Stop & notate.');
      stream.getAudioTracks()[0].onended = () => {
        if (session.current === recording && recording.recorder.state === 'recording') stop();
      };
      recording.timer = setInterval(() => {
        if (session.current !== recording) return;
        const elapsed = (performance.now() - recording.start) / 1000;
        if (elapsed >= 60 || document.hidden || recording.context.state !== 'running') { stop(); return; }
        analyser.getFloatTimeDomainData(buffer);
        let energy = 0; for (const value of buffer) energy += value * value;
        setLive({ level: Math.min(1, Math.sqrt(energy / buffer.length) * 5), elapsed });
      }, 80);
    } catch (error) {
      const messages = {
        NotAllowedError: 'Microphone permission was denied. Allow it in your browser’s site settings, then try again.',
        NotFoundError: 'No microphone found. Connect one and try again.',
        NotReadableError: 'The microphone is unavailable. Check system settings or close other recording apps.',
      };
      finish(recording, messages[error.name] || error.message || 'Could not start the microphone.');
    }
  }
  return <div className="recorder">
    <div className="live-note"><strong>{status === 'recording' ? 'Listening' : status === 'processing' ? `${progress}%` : '♫'}</strong><span>{status === 'recording' ? `${live.elapsed.toFixed(1)}s / 60s` : 'SPOTIFY BASIC PITCH'}</span></div>
    {status === 'processing' ? <progress max="100" value={progress} aria-label="Transcription progress"/> : <meter min="0" max="1" value={live.level} aria-label="Microphone level"/>}
    <button type="button" className={status === 'recording' ? 'stop-recording' : ''} onClick={status === 'idle' ? start : stop}>
      {status === 'idle' ? '● Start singing' : status === 'recording' ? '■ Stop & notate' : 'Cancel'}
    </button>
    <p role="status">{message}</p>
    <p className="caption">Sing one voice without accompaniment. Basic Pitch analyzes your recording after you stop. Short breaths are smoothed over. Audio stays on your device.</p>
  </div>;
}
