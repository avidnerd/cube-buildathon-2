// Parts (design/parts.html): "I'm singing" picker, learning mixes, mixer, send my part.
import React, { useState } from 'react';
import { renderWav } from '../player.js';
import { TRACK_COLORS, capitalize } from '../project.js';
import { mixGains } from '../mix.js';
import { playbackOptions } from '../playbackSources.js';
import { Fader, Header, Icon, Top } from '../ui/kit.jsx';
import { ScoreSheet } from '../ui/ScoreSheet.jsx';
import { ShareSheet } from '../ui/ShareSheet.jsx';
import { MuteSolo, useLiveGains } from './Arrange.jsx';

export const roleLabel = t => (t.role === 'melody' ? 'Melody' : t.role === 'counter' ? `${capitalize(t.voice)} counter` : 'Harmony');

export function PartsScreen({ project, setProject, playback, mix, setMix, showToast, go, totalBeats }) {
  const [score, setScore] = useState(false);
  const [sending, setSending] = useState(false);
  const [sharing, setSharing] = useState(false);
  const tracks = project.tracks;
  const singing = tracks.find(t => t.id === mix.singing) || null;
  const gains = mixGains(tracks, mix, { learning: true });
  useLiveGains(playback, gains);

  if (!tracks.length) return <>
    <Header/>
    <div className="scroll"><Top title={project.title} meta="No parts yet"/>
      <div className="blank"><b>No parts to learn yet</b><p className="meta">Record a melody first, then add parts in Arrange.</p></div></div>
    <button className="cta" onClick={() => go('record')}><i className="dot"/>GO TO RECORD</button>
  </>;

  async function send() {
    if (!singing) return;
    setSending(true);
    try {
      const blob = await renderWav({ tracks: [singing], tempo: project.tempo, totalBeats });
      const name = `${project.title} - ${singing.name}.wav`.replace(/[\\/:*?"<>|]+/g, '');
      const file = new File([blob], name, { type: 'audio/wav' });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: `${singing.name} · ${project.title}` });
      } else {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        showToast(`${singing.name.toUpperCase()} SAVED AS WAV`);
      }
    } catch (e) {
      if (e.name !== 'AbortError') showToast('COULD NOT EXPORT THE PART');
    } finally { setSending(false); }
  }

  const togglePlay = () => (playback.playing ? playback.stop() : playback.play({ ...playbackOptions(project, tracks, gains, mix), totalBeats }));
  return <>
    <Header><a className="ghost txt" href="#practice">Practice</a><button className="ghost" aria-label="Sheet music" title="Sheet music" onClick={() => setScore(true)}>{Icon.score}</button></Header>
    <div className="scroll">
      <Top title={project.title} meta={`${tracks.length} part${tracks.length === 1 ? '' : 's'} · ${project.key}`} beat={playback.beat}
        timeSignature={project.timeSignature} playing={playback.playing} onPlay={togglePlay}/>
      <p className="label">I'm singing</p>
      <div className="who">{tracks.map((t, i) => <button key={t.id} aria-pressed={mix.singing === t.id}
        style={mix.singing === t.id ? { background: TRACK_COLORS[i] } : undefined}
        onClick={() => setMix(m => ({ ...m, singing: m.singing === t.id ? null : t.id }))}>
        <i style={{ background: TRACK_COLORS[i] }}/><span><b>{t.name}</b><small>{t.assignedTo || roleLabel(t)}</small></span></button>)}
      </div>
      <p className="label" style={{ paddingTop: 14 }}>Mix</p>
      <div className="seg" role="group" aria-label="Learning mix">
        {[['solo', 'Solo'], ['pred', 'Predominant'], ['miss', 'Missing']].map(([id, label]) =>
          <button key={id} aria-pressed={mix.mode === id} disabled={!singing} onClick={() => setMix(m => ({ ...m, mode: id }))}>{label}</button>)}
      </div>
      {!singing && <p className="saved">Pick the part you sing to use a learning mix.</p>}
      <div className="mixer">{tracks.map((t, i) => {
        const value = mix.volume[t.id] ?? 0.8;
        return <div key={t.id} className={`ch${gains[t.id] < value - 1e-6 ? ' dim' : ''}`}>
          <Fader value={value} color={TRACK_COLORS[i]} dim={gains[t.id] < value - 1e-6} label={t.name}
            onChange={v => setMix(m => ({ ...m, volume: { ...m.volume, [t.id]: v } }))}/>
          <span className="nm">{t.name.split(' ')[0]}</span>
          <span className="pct">{Math.round(gains[t.id] * 100)}%</span>
          <MuteSolo id={t.id} name={t.name} mix={mix} setMix={setMix}/>
        </div>;
      })}</div>
      <p className="saved">Your mix is saved on this device only. Others hear their own.</p>
      {!project.shared && <div className="share">
        <div><b>Share the tape</b><p className="meta">Friends get a link to pick a part and sing.</p></div>
        <button className="chip" style={{ marginLeft: 'auto' }} onClick={() => setSharing(true)}>Share</button>
      </div>}
    </div>
    <button className="cta" disabled={!singing || sending} onClick={send}>
      {sending ? 'RENDERING…' : singing ? `SEND ${singing.name.toUpperCase()} PART` : 'PICK YOUR PART'}
    </button>
    {score && <ScoreSheet project={project} setProject={setProject} mineId={singing?.id} onClose={() => setScore(false)}/>}
    {sharing && <ShareSheet project={project} setProject={setProject} showToast={showToast} onClose={() => setSharing(false)}/>}
  </>;
}
