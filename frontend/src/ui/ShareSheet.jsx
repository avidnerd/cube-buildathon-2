// Publish the chosen harmonies and hand back a link for friends.
import React, { useState } from 'react';
import { publishSong } from '../share.js';
import { Header } from './kit.jsx';

export function ShareSheet({ project, setProject, onClose, showToast }) {
  const [state, setState] = useState({ status: 'idle' });

  async function publish() {
    setState({ status: 'uploading', done: 0, total: 1 });
    try {
      const link = await publishSong(project, { onProgress: (done, total) => setState({ status: 'uploading', done, total }) });
      setState({ status: 'ready', link });
    } catch (error) {
      setState({ status: 'error', message: `Could not publish this song: ${error.message}` });
    }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(state.link); showToast('LINK COPIED'); }
    catch { showToast('SELECT THE LINK TO COPY IT'); }
  }
  async function send() {
    try { await navigator.share({ title: project.title, text: `Sing ${project.title} with me`, url: state.link }); }
    catch (error) { if (error.name !== 'AbortError') copy(); }
  }

  return <section className="sheet" role="dialog" aria-label="Share with friends">
    <Header><button className="ghost txt" onClick={onClose}>Done</button></Header>
    <div className="scroll">
      <div className="top"><div className="t"><h1>Share</h1><p className="meta">Friends pick a part and sing along. No account needed.</p></div></div>
      <p className="label">Title</p>
      <div className="field"><input value={project.title} maxLength={100} aria-label="Title" disabled={state.status === 'uploading'}
        onChange={e => setProject(p => ({ ...p, title: e.target.value }))}/></div>
      <p className="label" style={{ paddingTop: 14 }}>Going out</p>
      <div className="who">{project.tracks.map(t => <div key={t.id} className="going"><b>{t.name}</b></div>)}</div>
      <p className="hint">Anyone with the link can hear these voices.</p>
      {state.status === 'uploading' && <div className="progress" style={{ margin: '14px 20px 0' }}><i style={{ width: `${state.done / state.total * 100}%` }}/></div>}
      {state.status === 'error' && <p className="msg err" role="alert">{state.message}</p>}
      {state.status === 'ready' && <>
        <p className="label" style={{ paddingTop: 14 }}>Your link</p>
        <div className="field"><input readOnly value={state.link} aria-label="Share link" onFocus={e => e.target.select()}/></div>
        <div className="actions share-actions">
          <button className="chip" onClick={copy}>Copy</button>
          {typeof navigator.share === 'function' && <button className="chip" onClick={send}>Send</button>}
          <a className="chip" href={state.link} target="_blank" rel="noreferrer">Open</a>
        </div>
      </>}
    </div>
    {state.status !== 'ready' && <button className="cta sheet-cta" disabled={state.status === 'uploading'} onClick={publish}>
      {state.status === 'uploading' ? `UPLOADING ${state.done} OF ${state.total}` : 'CREATE LINK'}
    </button>}
  </section>;
}
