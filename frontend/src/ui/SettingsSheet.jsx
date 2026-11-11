// Settings: everything the original single-page app let you correct after
// singing (title, tempo, time signature, key, clef, note spelling).
import React, { useEffect, useState } from 'react';
import { KEYS } from '../analyzeMelody.js';
import { applySettings } from '../arrangement.js';
import { keyFromSpec, keyToSpec } from '../project.js';
import { Header } from './kit.jsx';

function Seg({ label, value, options, onChange }) {
  return <>
    <p className="label">{label}</p>
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, text]) => <button key={v} aria-pressed={value === v} onClick={() => onChange(v)}>{text}</button>)}
    </div>
  </>;
}

export function SettingsSheet({ project, setProject, onClose }) {
  const [tempoText, setTempoText] = useState(String(project.tempo));
  useEffect(() => setTempoText(String(project.tempo)), [project.tempo]);
  const update = changes => setProject(p => applySettings(p, changes));
  function commitTempo(value) {
    const bpm = Math.round(Number(value));
    if (Number.isFinite(bpm) && bpm >= 20 && bpm <= 300) { update({ tempo: bpm }); setTempoText(String(bpm)); }
    else setTempoText(String(project.tempo));
  }
  const step = d => setProject(p => applySettings(p, { tempo: Math.max(20, Math.min(300, p.tempo + d)) }));
  return <section className="sheet" role="dialog" aria-label="Settings">
    <Header><button className="ghost txt" onClick={() => { setProject(p => ({ ...p, notice: '' })); onClose(); }}>Done</button></Header>
    <div className="scroll">
      <div className="top"><div className="t"><h1>Settings</h1></div></div>

      <p className="label">Title</p>
      <div className="field"><input value={project.title} maxLength={100} aria-label="Title"
        onChange={e => setProject(p => ({ ...p, title: e.target.value }))}/></div>

      <p className="label" style={{ paddingTop: 14 }}>Tempo (BPM)</p>
      <div className="field row-field">
        <div className="tempo">
          <button aria-label="Slower" onClick={() => step(-1)}>−</button>
          <input className="bpm" inputMode="numeric" aria-label="Tempo in BPM" value={tempoText}
            onChange={e => setTempoText(e.target.value)} onBlur={e => commitTempo(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && commitTempo(e.target.value)}/>
          <button aria-label="Faster" onClick={() => step(1)}>+</button>
        </div>
      </div>

      <div style={{ paddingTop: 6 }}><Seg label="Time signature" value={project.timeSignature} options={[['4/4', '4/4'], ['3/4', '3/4'], ['6/8', '6/8']]}
        onChange={v => update({ timeSignature: v })}/></div>

      <p className="label" style={{ paddingTop: 14 }}>Key</p>
      <div className="field"><select aria-label="Key" value={keyFromSpec(project.key)} onChange={e => update({ key: keyToSpec(e.target.value) })}>
        {KEYS.map(k => <option key={k} value={k}>{keyToSpec(k)}</option>)}
      </select></div>

      <div style={{ paddingTop: 6 }}><Seg label="Melody clef" value={project.melodyClef || 'auto'} options={[['auto', 'Auto'], ['treble', 'Treble'], ['bass', 'Bass']]}
        onChange={v => update({ melodyClef: v })}/></div>
      <div style={{ paddingTop: 6 }}><Seg label="Note spelling" value={project.spelling || 'auto'} options={[['auto', 'Follow key'], ['sharps', 'Sharps ♯'], ['flats', 'Flats ♭']]}
        onChange={v => update({ spelling: v })}/></div>
    </div>
  </section>;
}
