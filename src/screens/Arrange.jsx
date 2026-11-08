// Arrange (design/harmony-options.html): layered mix, track rows, option picker.
import React, { useEffect, useState } from 'react';
import { requestCounterMelody } from '../counterMelody.js';
// Picker order: the mid voices first, since they suit most melodies.
const COUNTER_VOICES = ['alto', 'tenor', 'soprano', 'bass'];
import { player } from '../player.js';
import { TRACK_COLORS, TRACK_COUNT, beatsPerBar, capitalize, makeTrack, projectBeats } from '../project.js';
import { mixGains } from '../mix.js';
import { Header, Icon, PianoRoll, Top } from '../ui/kit.jsx';
import { ScoreSheet } from '../ui/ScoreSheet.jsx';
import { SettingsSheet } from '../ui/SettingsSheet.jsx';
import { basisOf } from '../arrangement.js';

const chordText = chords => (chords?.length ? chords.map(c => c.name).filter((n, i, a) => n !== a[i - 1]).join(' ') : '–');

const COUNTER_DESC = {
  soprano: 'High line that weaves around the tune',
  alto: 'Mid-range line that weaves around the tune',
  tenor: 'Lower line that weaves around the tune',
  bass: 'Low line that weaves around the tune',
};

export function MuteSolo({ id, name, mix, setMix }) {
  const toggleMute = () => setMix(m => ({ ...m, mute: { ...m.mute, [id]: !m.mute[id] }, solo: m.solo === id ? null : m.solo }));
  const toggleSolo = () => setMix(m => ({ ...m, solo: m.solo === id ? null : id }));
  return <span className="ms">
    <button aria-pressed={!!mix.mute[id]} aria-label={`Mute ${name}`} title="Mute" onClick={toggleMute}>M</button>
    <button aria-pressed={mix.solo === id} aria-label={`Solo ${name}`} title="Solo" onClick={toggleSolo}>S</button>
  </span>;
}

/** Keep live gains in step with the mix while something is playing. */
export function useLiveGains(playback, gains) {
  const signature = JSON.stringify(gains);
  useEffect(() => { if (playback.playing) Object.entries(gains).forEach(([id, g]) => player.setGain(id, g)); }, [signature, playback.playing]);
}

export function ArrangeScreen({ project, setProject, playback, mix, setMix, showToast, go, refreshing }) {
  const melody = project.tracks.find(t => t.role === 'melody');
  const [picking, setPicking] = useState(null);       // { slot, index, editing }
  const [cache, setCache] = useState({});             // voice -> { loading, result, error }
  const [score, setScore] = useState(false);
  const [settings, setSettings] = useState(false);
  const bar = beatsPerBar(project.timeSignature);

  // Generated lines depend on the melody, key, tempo and meter.
  useEffect(() => setCache({}), [melody?.notes, project.key, project.timeSignature]);

  const options = picking ? [
    ...COUNTER_VOICES.filter(v => !project.tracks.some((t, i) => i !== picking.slot && t.voice === v)).map(v => ({ kind: 'counter', voice: v })),
    { kind: 'harmony' },
  ] : [];
  const option = options[picking?.index ?? 0];
  const entry = option?.kind === 'counter' ? cache[option.voice] : null;

  useEffect(() => {
    if (!melody || option?.kind !== 'counter' || cache[option.voice]) return;
    const voice = option.voice;
    setCache(c => ({ ...c, [voice]: { loading: true } }));
    requestCounterMelody(melody.notes, { tempo: project.tempo, timeSignature: project.timeSignature, key: project.key, voice })
      .then(result => setCache(c => ({ ...c, [voice]: { result } })))
      .catch(error => setCache(c => ({ ...c, [voice]: { error: error.message } })));
  }, [option?.kind, option?.voice, cache]);

  const preview = picking && entry?.result ? { id: 'preview', notes: entry.result.notes } : null;
  const visible = project.tracks.map((t, i) => (picking?.slot === i ? null : t)).filter(Boolean);
  const playTracks = [...visible, ...(preview ? [preview] : [])];
  const gains = { ...mixGains(visible, mix), ...(preview ? { preview: 0.8 } : {}) };
  useLiveGains(playback, gains);
  const totalBeats = projectBeats({ ...project, tracks: playTracks });

  if (!melody) return <>
    <Header/>
    <div className="scroll">
      <Top title={project.title} meta="No melody yet"/>
      <div className="blank"><b>Nothing on the tape</b><p className="meta">Record a phrase (or load the demo) and it will show up here as track 1.</p></div>
    </div>
    <button className="cta" onClick={() => go('record')}><i className="dot"/>GO TO RECORD</button>
  </>;

  const isOn = id => (mix.solo ? mix.solo === id : !mix.mute[id]);

  function openPicker(slot) {
    const voice = project.tracks[slot]?.voice;
    const list = COUNTER_VOICES.filter(v => !project.tracks.some((t, i) => i !== slot && t.voice === v));
    setPicking({ slot, index: Math.max(0, list.indexOf(voice)) });
  }
  function keep() {
    const { voice } = option;
    const { result } = entry;
    const track = { ...makeTrack({ id: `counter-${voice}`, name: `${capitalize(voice)} counter`, role: 'counter', voice, notes: result.notes }),
      style: result.style, chords: result.chords, fallback: result.fallback, basis: basisOf(project) };
    setProject(p => {
      const tracks = [...p.tracks];
      tracks[picking.slot] = track;
      return { ...p, tracks };
    });
    showToast(`${voice.toUpperCase()} COUNTER ON TRACK ${picking.slot + 1}`);
    setPicking(null);
  }
  function remove(slot) {
    setProject(p => ({ ...p, tracks: p.tracks.filter((_, i) => i !== slot) }));
    setPicking(null);
  }

  const rows = [];
  for (let i = 0; i < TRACK_COUNT; i++) {
    const t = project.tracks[i];
    const color = TRACK_COLORS[i];
    if (picking?.slot === i) {
      const desc = option.kind === 'harmony' ? 'Parallel 3rds, 6ths, drone… · coming soon'
        : entry?.loading ? 'Writing a line…' : entry?.error ? entry.error
          : entry?.result ? `${COUNTER_DESC[option.voice]} · ${entry.result.style === 'calm' ? 'calm' : 'active'}${entry.result.fallback ? ' · safe' : ''} · chords ${chordText(entry.result.chords)}` : '';
      rows.push(<div key={i} className="trk" style={{ background: color }}>
        <div className="row"><span className="nm">{t ? t.name : `Track ${i + 1}`}<small>Choose a line</small></span>
          {t && t.role !== 'melody' && <button className="x" aria-label="Remove track" onClick={() => remove(i)}>⌫</button>}
          <button className="x" aria-label="Close picker" onClick={() => setPicking(null)}>×</button></div>
        <div className="pick">
          <button className="arrow" aria-label="Previous option" onClick={() => setPicking(p => ({ ...p, index: (p.index - 1 + options.length) % options.length }))}>{Icon.left}</button>
          <div className="mid" aria-live="polite">
            <b>{option.kind === 'harmony' ? 'HARMONY' : `${option.voice.toUpperCase()} COUNTER`}</b>
            <span>{desc}</span>
            <span className="dots" aria-label={`Option ${picking.index + 1} of ${options.length}`}>{options.map((_, k) => <i key={k} className={k === picking.index ? 'on' : ''}/>)}</span>
          </div>
          <button className="arrow" aria-label="Next option" onClick={() => setPicking(p => ({ ...p, index: (p.index + 1) % options.length }))}>{Icon.right}</button>
        </div>
      </div>);
    } else if (t) {
      const small = t.role === 'melody' ? `Your recording · ${project.key}`
        : refreshing && t.basis !== basisOf(project) ? 'Rewriting to match the melody…'
          : `${t.style === 'calm' ? 'Calm' : 'Active'}${t.fallback ? ' (safe)' : ''} · chords ${chordText(t.chords)}`;
      rows.push(<div key={i} className={`trk${isOn(t.id) ? '' : ' off'}`} style={{ background: color }}>
        <div className="row">
          {t.role === 'melody' ? <span className="nm">{t.name}<small>{small}</small></span>
            : <button className="nm" onClick={() => openPicker(i)} aria-label={`Change ${t.name}`}>{t.name}<small>{small}</small></button>}
          <MuteSolo id={t.id} name={t.name} mix={mix} setMix={setMix}/>
        </div>
      </div>);
    } else if (i === project.tracks.length && !picking) {
      rows.push(<button key={i} className="empty" onClick={() => openPicker(i)}>
        <span className="nm">Add a part<small>Counter-melody now · harmony soon</small></span>{Icon.plus}</button>);
    }
  }

  let cta;
  if (picking) {
    if (option.kind === 'harmony') cta = <button className="cta" disabled>HARMONY: COMING SOON</button>;
    else if (entry?.result) cta = <button className="cta" onClick={keep}>KEEP {option.voice.toUpperCase()} COUNTER</button>;
    else cta = <button className="cta" disabled>{entry?.error ? 'TRY ANOTHER VOICE' : 'WRITING…'}</button>;
  } else cta = <button className="cta" onClick={() => go('parts')}>SHARE THE PARTS</button>;

  const togglePlay = () => (playback.playing ? playback.stop() : playback.play({ tracks: playTracks, tempo: project.tempo, totalBeats, gains }));
  return <>
    <Header>
      <button className="ghost" aria-label="Settings" title="Tempo, key, time signature…" onClick={() => setSettings(true)}>{Icon.gear}</button>
      <button className="ghost" aria-label="Sheet music" title="Sheet music" onClick={() => setScore(true)}>{Icon.score}</button>
    </Header>
    <div className="scroll">
      <Top title={project.title} meta={`${project.key} · ${project.tempo} bpm · ${project.timeSignature}`} beat={playback.beat} timeSignature={project.timeSignature}
        playing={playback.playing} onPlay={togglePlay}/>
      {project.notice && <p className="msg" role="status" style={{ marginTop: 0, marginBottom: 12 }}>Tempo, time signature and key were guessed from your singing. <button className="link" onClick={() => setSettings(true)}>Check them in Settings</button>.</p>}
      <section className="panel mix" aria-label="All tracks layered">
        <PianoRoll totalBeats={totalBeats} beatsPerBar={bar} beat={playback.playing ? playback.beat : 0}
          tracks={[...project.tracks.map((t, i) => (picking?.slot === i ? null : { id: t.id, color: TRACK_COLORS[i], notes: t.notes, dim: !isOn(t.id) })).filter(Boolean),
            ...(preview ? [{ id: 'preview', color: TRACK_COLORS[picking.slot], notes: preview.notes, variant: 'preview' }] : [])]}/>
      </section>
      <section className="tracks" aria-label="Tracks">{rows}</section>
    </div>
    {cta}
    {score && <ScoreSheet project={project} setProject={setProject} onClose={() => setScore(false)}/>}
    {settings && <SettingsSheet project={project} setProject={setProject} onClose={() => setSettings(false)}/>}
  </>;
}
