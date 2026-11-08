import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { melodyToAbc, scoreToAbc } from './melodyToAbc.js';
import { COUNTER_VOICES, requestCounterMelody } from './counterMelody.js';
import { SheetMusic } from './SheetMusic.jsx';
import { SingRecorder } from './SingRecorder.jsx';
import { analyzeMelody, KEYS } from './analyzeMelody.js';
import './style.css';

const sample = [
  { midi: 60, start: 0, duration: 0.5 },
  { midi: 62, start: 0.5, duration: 0.5 },
  { midi: 64, start: 1, duration: 0.5 },
  { midi: 67, start: 1.5, duration: 1 },
  { midi: 66, start: 2.75, duration: 0.25 },
  { midi: 65, start: 3, duration: 0.5 },
  { midi: 64, start: 3.5, duration: 0.5 },
  { midi: 60, start: 4, duration: 2 },
];
function App() {
  const [input, setInput] = useState('[]');
  const [bpm, setBpm] = useState(120);
  const [meter, setMeter] = useState('4/4');
  const [clef, setClef] = useState('treble');
  const [title, setTitle] = useState('My sung melody');
  const [key, setKey] = useState('C');
  const [spelling, setSpelling] = useState('auto');
  const [analysisNotice, setAnalysisNotice] = useState('Tempo, time signature and key will be estimated when you finish singing.');
  const [busy, setBusy] = useState(false);
  const [counterVoice, setCounterVoice] = useState('alto');
  const [counter, setCounter] = useState(null);
  const [counterStatus, setCounterStatus] = useState({ loading: false, error: '' });
  // A counter-melody belongs to one exact melody/tempo/meter/key; drop it when they change.
  useEffect(() => { setCounter(null); setCounterStatus({ loading: false, error: '' }); }, [input, bpm, meter, key]);
  function transcribe(notes) {
    const estimate = analyzeMelody(notes);
    setBpm(estimate.bpm); setMeter(estimate.meter); setKey(estimate.key); setSpelling('auto');
    const tick = 60 / estimate.bpm / 4;
    const usable = notes.filter(n => Math.round((n.start + n.duration) / tick) > Math.round(n.start / tick));
    setAnalysisNotice(estimate.notice + (usable.length < notes.length ? ' Very brief notes were omitted from the timing grid.' : ''));
    setInput(JSON.stringify(usable, null, 2));
  }
  let result, error, melodyNotes;
  try {
    melodyNotes = JSON.parse(input);
    if (!Array.isArray(melodyNotes) || melodyNotes.length) {
      const options = { bpm: Number(bpm), meter, title, key, spelling };
      result = counter
        ? scoreToAbc([{ name: 'Melody', clef, notes: melodyNotes }, { name: `Counter (${counter.voice})`, clef: counter.clef, notes: counter.counter }], options)
        : melodyToAbc(melodyNotes, { ...options, clef });
    }
  }
  catch (e) { error = e instanceof SyntaxError ? 'Enter valid JSON: an array of melody notes.' : e.message; }
  async function generateCounter() {
    setCounterStatus({ loading: true, error: '' });
    try {
      const generated = await requestCounterMelody(melodyNotes, { bpm: Number(bpm), meter, key, voice: counterVoice });
      if (!generated.counter.length) throw new Error('The generator could not find a singable line for this melody.');
      setCounter(generated);
      setCounterStatus({ loading: false, error: '' });
    } catch (e) { setCounterStatus({ loading: false, error: e.message }); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([result.abc], { type: 'text/vnd.abc;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = 'singing-melody.abc'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <main>
    <header><span className="eyebrow">SINGING LAB / FEATURE 01</span><h1>Give your melody<br/><em>a place on the page.</em></h1><p>Sing a melody. See it become sheet music.</p></header>
    <div className="workspace">
      <section className="controls"><h2>01 / Sing your melody</h2><SingRecorder onBusy={setBusy} onMelody={transcribe}/><fieldset disabled={busy}>
        <label>Score title<input value={title} onChange={e => setTitle(e.target.value)} maxLength={100}/></label>
        <p className="notice" role="status">{analysisNotice}</p><div className="settings"><label>Tempo (BPM)<input type="number" min="20" max="300" value={bpm} onChange={e => setBpm(e.target.value)}/></label>
          <label>Time signature<select value={meter} onChange={e => setMeter(e.target.value)}>{['4/4','3/4','6/8'].map(m => <option key={m}>{m}</option>)}</select></label>
          <label>Clef<select value={clef} onChange={e => setClef(e.target.value)}><option value="treble">Treble</option><option value="bass">Bass</option></select></label></div>
        <div className="key-settings"><label>Key (estimated)<select value={key} onChange={e => setKey(e.target.value)}>{KEYS.map(k => <option key={k} value={k}>{k.endsWith('m') ? k.slice(0, -1) + ' minor' : k + ' major'}</option>)}</select></label>
        <label>Note spelling<select value={spelling} onChange={e => setSpelling(e.target.value)}><option value="auto">Follow key</option><option value="sharps">Prefer sharps ♯</option><option value="flats">Prefer flats ♭</option></select></label></div>
        <details><summary>Advanced: edit detected notes</summary><label htmlFor="melody">Melody JSON</label><textarea id="melody" spellCheck="false" value={input} onChange={e => setInput(e.target.value)}/></details>
        <button className="secondary" onClick={() => { transcribe(sample); setClef('treble'); setTitle('A little melody'); }}>Load example</button></fieldset>
      </section>
      <section className="preview"><div className="preview-heading"><h2>02 / Your sheet music</h2><span className="badge">LIVE PREVIEW</span></div>
        {error ? <p className="error" role="alert">{error}</p> : !result ? <div className="empty-score"><span>♫</span><h3>Your melody starts here</h3><p>Press Start singing, allow your microphone, and sing or hum a few notes. Press Stop &amp; notate to see your score.</p></div> : <><div className="paper"><SheetMusic abc={result.abc}/></div><div className="actions"><button onClick={() => window.print()}>Print / Save PDF</button><button className="secondary" onClick={download}>Download ABC</button></div>
          <div className="counter-panel"><h2>03 / Counter-melody</h2>
            <p>Writes an independent line that weaves around your melody: it moves when you hold a note and holds when you move.</p>
            <div className="counter-controls"><label>Counter voice<select value={counterVoice} disabled={counterStatus.loading || busy} onChange={e => { setCounterVoice(e.target.value); setCounter(null); }}>{COUNTER_VOICES.map(v => <option key={v} value={v}>{v[0].toUpperCase() + v.slice(1)}</option>)}</select></label>
              <button onClick={generateCounter} disabled={counterStatus.loading || busy}>{counterStatus.loading ? 'Writing…' : counter ? 'Regenerate' : 'Add counter-melody'}</button>
              {counter && <button className="secondary" onClick={() => setCounter(null)}>Remove</button>}</div>
            {counterStatus.error && <p className="error" role="alert">{counterStatus.error}</p>}
            {counter && <p className="notice" role="status">{counter.key} · {counter.style === 'calm' ? 'calm, held line' : 'active line'}{counter.echo ? ' with a motif echo' : ''}{counter.fallback ? ' · safe fallback (held chord tones)' : ''} · chords: {counter.chords.map(c => c.name).join(' ')}</p>}
          </div>
          {result.warnings.map(w => <p role="status" className="notice" key={w}>{w}</p>)}<details><summary>View generated notation</summary><pre>{result.abc}</pre></details></>}
        <p className="caption">One voice · Estimated rhythm &amp; key · Sixteenth-note timing<br/>Short breaths are smoothed over. Longer pauses become rests.</p>
      </section>
    </div><footer>A first draft of your melody · Best with clear, sustained notes in a quiet room.</footer>
  </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
