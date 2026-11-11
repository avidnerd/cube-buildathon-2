// Record (design/record.html): sing freely (tempo, time signature and key are
// guessed afterwards) or with a count-in; live trace, takes, transcription.
import React, { useEffect, useRef, useState } from 'react';
import { useRecorder } from '../useRecorder.js';
import { notesEnd } from '../noteModel.js';
import { beatsPerBar, keyToSpec, makeTrack } from '../project.js';
import { Header, PianoRoll, Top } from '../ui/kit.jsx';

const METERS = ['4/4', '3/4', '6/8'];

export function RecordScreen({ project, setProject, takes, setTakes, showToast, go, blankTake, clearBlankTake }) {
  const [bpm, setBpm] = useState(project.tempo);
  const [meter, setMeter] = useState(project.timeSignature);
  const [countIn, setCountIn] = useState(false);
  const [clickOn, setClickOn] = useState(false);
  const [selected, setSelected] = useState(takes.length - 1);
  useEffect(() => { if (blankTake) { setSelected(-1); clearBlankTake(); } }, [blankTake]);
  const bar = beatsPerBar(meter);
  const fileInput = useRef(null);

  function addTake(take) {
    setSelected(takes.length);
    setTakes(list => [...list, { ...take, id: `take-${Date.now()}` }]);
  }
  const rec = useRecorder({ bpm, meter, beatsPerBar: bar, countIn, clickOn, onTake: addTake });
  const busy = rec.status !== 'ready';
  const take = takes[selected];
  const inUse = take && project.tracks[0]?.takeId === take.id;

  function useTake() {
    // `recording` keeps the raw timing (seconds) so the rhythm can be re-read if the tempo is corrected later.
    const melody = { ...makeTrack({ id: 'melody', name: 'Melody', role: 'melody', notes: take.notes }), recording: take.seconds, takeId: take.id, timing: take.timing, backend: take.backend };
    setProject(p => ({ ...p, key: keyToSpec(take.key), tempo: take.bpm, timeSignature: take.meter, tracks: [melody], notice: take.notice }));
    showToast(`TAKE ${selected + 1} READY TO SPLIT`);
    go('split');
  }

  // What the roll shows: live trace while recording, otherwise the selected take.
  const liveNotes = rec.live.frames.map(f => ({ pitch: f.pitch, start: f.beat, duration: 0.06 }));
  const shownNotes = busy ? liveNotes : take?.notes ?? [];
  const rollBeats = Math.max(bar * 2, Math.ceil((busy ? rec.live.beat : notesEnd(shownNotes)) / bar) * bar);
  const beatIndex = Math.floor(rec.live.beat >= 0 ? rec.live.beat % bar : rec.live.beat + bar);

  let deck;
  if (rec.status === 'count') deck = <><div className="big count">{Math.max(1, Math.ceil(-rec.live.beat))}</div><p className="meta">Count-in</p></>;
  else if (rec.status === 'rec') {
    const secs = Math.max(0, rec.live.beat) * 60 / bpm;
    deck = <><div className="big">{String(Math.floor(secs / 60)).padStart(2, '0')}:{(secs % 60).toFixed(1).padStart(4, '0')}</div><p className="rec"><i/>REC</p></>;
  } else if (rec.status === 'processing') deck = <><div className="big small">{rec.progress}%</div><p className="meta">{rec.stage}</p><div className="progress" style={{ width: 200 }}><i style={{ width: `${rec.progress}%` }}/></div></>;
  else if (take) deck = <><div className="big small">TAKE {selected + 1}</div><p className="meta">{take.notes.length} notes · {take.bpm} BPM · {take.meter} · {keyToSpec(take.key)}{inUse ? ' · in use' : ''}</p></>;
  else deck = <div className="big">READY</div>;

  const levelBars = Math.round(rec.live.level * 16);
  return <>
    <Header>{!busy && <>
      <button className="ghost txt" onClick={() => fileInput.current.click()}>Voice memo</button>
      <input ref={fileInput} type="file" accept="audio/*" hidden aria-label="Upload a voice memo or song"
        onChange={e => { rec.upload(e.target.files[0]); e.target.value = ''; }}/>
    </>}</Header>
    <div className="scroll">
      <Top title={project.title} meta={take ? `Track 1 · melody · take ${selected + 1}` : undefined}/>
      <section className="panel deck" aria-live="polite">
        <div>{deck}</div>
        <div className="beats" aria-hidden="true">{Array.from({ length: bar }, (_, i) =>
          <i key={i} className={(rec.status === 'count' || (rec.status === 'rec' && countIn)) && i === beatIndex ? (i === 0 ? 'on one' : 'on') : ''}/>)}</div>
      </section>
      <section className="panel recroll" aria-label="Notes heard">
        <PianoRoll tracks={[{ id: 'mel', color: 'var(--t1)', notes: shownNotes }]} totalBeats={rollBeats} beatsPerBar={bar}
          beat={rec.status === 'rec' ? rec.live.beat : null} range={busy ? [48, 79] : undefined}
          hint={busy ? 'Your notes appear here as you sing' : undefined}/>
      </section>
      {rec.message && <p className="msg err" role="alert">{rec.message}</p>}
      <div className="settings">
        <button className="chip" aria-pressed={countIn} disabled={busy} onClick={() => setCountIn(c => !c)}>Count-in</button>
        {countIn && <>
          <div className="tempo"><button disabled={busy} aria-label="Slower" onClick={() => setBpm(b => Math.max(40, b - 2))}>−</button>
            <b>{bpm} BPM</b><button disabled={busy} aria-label="Faster" onClick={() => setBpm(b => Math.min(200, b + 2))}>+</button></div>
          <button className="chip" disabled={busy} aria-label={`Time signature ${meter}`} onClick={() => setMeter(m => METERS[(METERS.indexOf(m) + 1) % METERS.length])}>{meter}</button>
          <button className="chip" aria-pressed={clickOn} onClick={() => setClickOn(c => !c)}>Click</button>
        </>}
      </div>
      <div className="level" aria-label="Mic level"><span>Mic</span>{Array.from({ length: 16 }, (_, i) => <i key={i} className={i < levelBars ? 'on' : ''}/>)}</div>
      {takes.length > 0 && <div className="takes"><span className="meta">Takes</span>
        {takes.map((t, i) => <button key={i} className="take" aria-pressed={i === selected} disabled={busy} onClick={() => setSelected(i)}>
          {i + 1}{project.tracks[0]?.takeId === t.id ? ' ★' : ''}</button>)}
        {!busy && <button className="take new" onClick={rec.start} aria-label="Record a new take">+ {takes.length + 1}</button>}
      </div>}
    </div>
    {rec.status === 'ready' && take && !inUse
      ? <button className="cta" onClick={useTake}>USE TAKE {selected + 1}</button>
      : <button className="cta" onClick={rec.status === 'ready' ? rec.start : rec.status === 'processing' ? rec.cancel : rec.stop}>
        {rec.status === 'ready' ? <><i className="dot"/>{take ? 'RECORD AGAIN' : 'RECORD'}</>
          : rec.status === 'processing' ? 'CANCEL' : <><i className="sq"/>{rec.status === 'count' ? 'CANCEL' : 'STOP'}</>}
      </button>}
  </>;
}
