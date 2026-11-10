// Sheet music overlay (spec 1.3): full score or one part, print to PDF, ABC
// download, the generated notation, and a note editor for fixing the melody.
import React, { useMemo, useState } from 'react';
import { SheetMusic } from '../SheetMusic.jsx';
import { scoreToAbc } from '../melodyToAbc.js';
import { notesToSeconds, parseNoteEdits } from '../noteModel.js';
import { clefFor, keyFromSpec } from '../project.js';
import { Header } from './kit.jsx';

const editable = notes => JSON.stringify(notes.map(n => ({ pitch: n.pitch, start: n.start, duration: n.duration })), null, 1)
  .replace(/\n\s*(?="|\})/g, ' ').replace(/\{ /g, '{');

export function ScoreSheet({ project, setProject, mineId = null, onClose }) {
  const [view, setView] = useState(mineId ? 'mine' : 'full');
  const melody = project.tracks.find(t => t.role === 'melody');
  const [draft, setDraft] = useState(() => (melody ? editable(melody.notes) : '[]'));
  const [editError, setEditError] = useState('');
  const tracks = project.tracks.filter(t => t.notes.length && (view === 'full' || t.id === mineId));
  const { abc, warnings = [], error } = useMemo(() => {
    try {
      return scoreToAbc(tracks.map(t => ({
        name: t.name,
        clef: t.role === 'melody' && project.melodyClef && project.melodyClef !== 'auto' ? project.melodyClef : clefFor(t.notes),
        notes: notesToSeconds(t.notes, project.tempo),
      })), { bpm: project.tempo, meter: project.timeSignature, key: keyFromSpec(project.key), title: project.title, spelling: project.spelling || 'auto' });
    } catch (e) { return { error: e.message }; }
  }, [project, view, mineId]);

  function download() {
    const url = URL.createObjectURL(new Blob([abc], { type: 'text/vnd.abc;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${project.title.replace(/[^\w-]+/g, '-').toLowerCase() || 'score'}.abc`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function applyEdits() {
    try {
      const notes = parseNoteEdits(draft, melody.notes);
      // Hand-edited notes replace the recorded timing, so tempo changes no longer re-read the take.
      setProject(p => ({ ...p, tracks: p.tracks.map(t => (t.role === 'melody' ? { ...t, notes, recording: null } : t)) }));
      setEditError('');
      setDraft(editable(notes));
    } catch (e) { setEditError(e.message); }
  }

  const mine = project.tracks.find(t => t.id === mineId);
  return <section className="sheet" role="dialog" aria-label="Sheet music">
    <Header><button className="ghost txt" onClick={onClose}>Close</button></Header>
    <div className="scroll">
      <div className="top"><div className="t"><h1>Score</h1><p className="meta">{project.key} · {project.tempo} bpm · {project.timeSignature}</p></div></div>
      {mine && <div className="seg" role="group" aria-label="Score view">
        <button aria-pressed={view === 'full'} onClick={() => setView('full')}>Full score</button>
        <button aria-pressed={view === 'mine'} onClick={() => setView('mine')}>{mine.name} only</button>
      </div>}
      {error ? <p className="msg err" role="alert">{error}</p> : <div className="paper"><SheetMusic abc={abc}/></div>}
      {warnings.map(w => <p key={w} className="warn" role="status">{w}</p>)}
      {!error && <div className="actions">
        <button className="chip" onClick={() => window.print()}>Print / PDF</button>
        <button className="chip" onClick={download}>Download ABC</button>
      </div>}
      {melody && setProject && <details>
        <summary>Edit melody notes</summary>
        <p className="hint" style={{ padding: '4px 0 0' }}>pitch is a MIDI number (60 = middle C); start and duration are in beats. Counter-melodies are rewritten to match.</p>
        <div className="field"><textarea spellCheck="false" aria-label="Melody notes" value={draft} onChange={e => setDraft(e.target.value)}/></div>
        {editError && <p className="msg err" role="alert" style={{ margin: '8px 0 0' }}>{editError}</p>}
        <div className="actions" style={{ padding: '8px 0 0' }}>
          <button className="chip" onClick={applyEdits}>Apply changes</button>
          <button className="chip" onClick={() => { setDraft(editable(melody.notes)); setEditError(''); }}>Reset</button>
        </div>
      </details>}
      {abc && <details><summary>View generated notation</summary><pre>{abc}</pre></details>}
    </div>
  </section>;
}
