// Practice (design/practice.html). Loop and slow-down work now (parts are notes,
// so a slower tempo has no audio artifacts). Live pitch grading is build step 5.
import React, { useState } from 'react';
import { TRACK_COLORS, beatsPerBar } from '../project.js';
import { mixGains } from '../mix.js';
import { Header, PianoRoll, Top } from '../ui/kit.jsx';
import { useLiveGains } from './Arrange.jsx';
import { roleLabel } from './Parts.jsx';

export function PracticeScreen({ project, playback, mix, setMix, go, totalBeats }) {
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(true);
  const tracks = project.tracks;
  const index = tracks.findIndex(t => t.id === mix.singing);
  const mine = tracks[index];
  const gains = mixGains(tracks, mix, { learning: true });
  useLiveGains(playback, gains);

  if (!tracks.length) return <>
    <Header/>
    <div className="scroll"><Top title="Practice" meta="No parts yet"/>
      <div className="blank"><b>Nothing to practise yet</b><p className="meta">Record a melody first.</p></div></div>
    <button className="cta" onClick={() => go('record')}><i className="dot"/>GO TO RECORD</button>
  </>;

  const start = () => playback.play({ tracks, tempo: project.tempo, totalBeats, gains, rate: speed, loop });
  return <>
    <Header/>
    <div className="scroll">
      <Top title="Practice" meta={`${project.key} · ${Math.round(project.tempo * speed)} bpm${loop ? ' · looping' : ''}`}
        beat={playback.beat} timeSignature={project.timeSignature}>
        {mine && <span className="vchip" style={{ background: TRACK_COLORS[index] }}>{mine.name}</span>}
      </Top>
      {!mine && <>
        <p className="label">Pick the part you sing</p>
        <div className="who">{tracks.map((t, i) => <button key={t.id} onClick={() => setMix(m => ({ ...m, singing: t.id }))}>
          <i style={{ background: TRACK_COLORS[i] }}/><span><b>{t.name}</b><small>{roleLabel(t)}</small></span></button>)}</div>
      </>}
      {mine && <section className="panel stage" aria-label="Your target notes">
        <PianoRoll tracks={[{ id: mine.id, notes: mine.notes, variant: 'target' }]} totalBeats={totalBeats}
          beatsPerBar={beatsPerBar(project.timeSignature)} beat={playback.playing ? playback.beat : null}/>
      </section>}
      <div className="loop">
        <button className="chip" aria-pressed={loop} onClick={() => { setLoop(l => !l); playback.stop(); }}>Loop</button>
        <div className="seg" role="group" aria-label="Speed">
          {[0.5, 0.75, 1].map(s => <button key={s} aria-pressed={speed === s} onClick={() => { setSpeed(s); playback.stop(); }}>{s * 100}%</button>)}
        </div>
      </div>
      <div className="note-soon"><b>Pitch feedback is coming</b>Live scoring of your pitch (on pitch / close / off, with habits after each take) is build step 5. For now, sing along with your part at any speed, using headphones.</div>
    </div>
    <button className="cta" disabled={!mine} onClick={() => (playback.playing ? playback.stop() : start())}>
      {playback.playing ? 'STOP' : mine ? `PLAY ${mine.name.toUpperCase()} AT ${speed * 100}%` : 'PICK YOUR PART'}
    </button>
  </>;
}
