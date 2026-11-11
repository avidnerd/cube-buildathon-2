// Arrange (design/harmony-options.html): layered mix, track rows, option picker.
import React, { useEffect, useRef, useState } from 'react';
import { requestCounterMelody } from '../counterMelody.js';
import { harmonyBasis, harmonyChoices, requestHarmonyOptions, timingOf } from '../harmonyApi.js';
import { bandFits, hasBand, playbackOptions } from '../playbackSources.js';
// Picker order: the mid voices first, since they suit most melodies.
const COUNTER_VOICES = ['alto', 'tenor', 'soprano', 'bass'];
import { loadAudio, player } from '../player.js';
import { TRACK_COLORS, TRACK_COUNT, beatsPerBar, capitalize, makeTrack, projectBeats } from '../project.js';
import { mixGains } from '../mix.js';
import { Header, Icon, PianoRoll, Top } from '../ui/kit.jsx';
import { ScoreSheet } from '../ui/ScoreSheet.jsx';
import { ShareSheet } from '../ui/ShareSheet.jsx';
import { SettingsSheet } from '../ui/SettingsSheet.jsx';
import { basisOf } from '../arrangement.js';

const chordText = chords => (chords?.length ? chords.map(c => c.name).filter((n, i, a) => n !== a[i - 1]).join(' ') : '–');


export function MuteSolo({ id, name, mix, setMix }) {
  const toggleMute = () => setMix(m => ({ ...m, mute: { ...m.mute, [id]: !m.mute[id] }, solo: m.solo === id ? null : m.solo }));
  const toggleSolo = () => setMix(m => ({ ...m, solo: m.solo === id ? null : id }));
  return <span className="ms">
    <button aria-pressed={!!mix.mute[id]} aria-label={`Mute ${name}`} title={mix.mute[id] ? 'Unmute' : 'Mute'} onClick={toggleMute}>{mix.mute[id] ? Icon.muted : Icon.volume}</button>
    <button aria-pressed={mix.solo === id} aria-label={`Solo ${name}`} title="Solo" onClick={toggleSolo}>{Icon.person}</button>
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
  const [engine, setEngine] = useState(null);         // harmony options: { loading, choices, error }
  const [score, setScore] = useState(false);
  const [settings, setSettings] = useState(false);
  const [sharing, setSharing] = useState(false);
  const bar = beatsPerBar(project.timeSignature);

  // Generated lines depend on the melody, key, tempo and meter.
  useEffect(() => setCache({}), [melody?.notes, project.key, project.timeSignature]);
  const basis = melody ? harmonyBasis(melody) : '';
  const engineRequest = useRef(null); // only the latest request may answer
  useEffect(() => { engineRequest.current = null; setEngine(null); }, [basis, project.timeSignature]);

  // The engine's harmonies come first in the picker; they are what the app is for.
  const optionsFor = slot => [
    ...(engine?.choices?.filter(c => !project.tracks.some((t, i) => i !== slot && t.id === `harmony-${c.id}`))
      ?? [{ kind: 'status' }]),
    ...COUNTER_VOICES.filter(v => !project.tracks.some((t, i) => i !== slot && t.voice === v)).map(v => ({ kind: 'counter', voice: v })),
  ];
  const options = picking ? optionsFor(picking.slot) : [];
  const option = options[Math.min(picking?.index ?? 0, options.length - 1)];
  const entry = option?.kind === 'counter' ? cache[option.voice] : null;

  useEffect(() => {
    if (!melody || !picking || engine) return;
    setEngine({ loading: true });
    const request = {};
    engineRequest.current = request;
    const current = () => engineRequest.current === request;
    requestHarmonyOptions(melody, { tempo: project.tempo, timeSignature: project.timeSignature })
      .then(data => {
        if (!current()) return;
        setEngine({ choices: harmonyChoices(data, timingOf(melody, project.tempo).shift) });
        const found = data.paths[0]?.key;
        if (found) setProject(p => ({ ...p, key: `${found.tonic} ${found.mode}` }));
      })
      .catch(error => { if (current()) setEngine({ error: error.message }); });
  }, [!!picking, engine, basis]);

  useEffect(() => {
    if (!melody || option?.kind !== 'counter' || cache[option.voice]) return;
    const voice = option.voice;
    setCache(c => ({ ...c, [voice]: { loading: true } }));
    requestCounterMelody(melody.notes, { tempo: project.tempo, timeSignature: project.timeSignature, key: project.key, voice })
      .then(result => setCache(c => ({ ...c, [voice]: { result } })))
      .catch(error => setCache(c => ({ ...c, [voice]: { error: error.message } })));
  }, [option?.kind, option?.voice, cache]);

  const preview = !picking ? null
    : option?.kind === 'harmony' ? { id: 'preview', role: 'harmony', notes: option.notes, part: option.part, backing: option.backing, basis }
      : entry?.result ? { id: 'preview', notes: entry.result.notes } : null;
  const visible = project.tracks.map((t, i) => (picking?.slot === i ? null : t)).filter(Boolean);
  const playTracks = [...visible, ...(preview ? [preview] : [])];
  const gains = { ...mixGains(visible, mix), ...(preview ? { preview: 0.8 } : {}) };
  useLiveGains(playback, gains);
  const totalBeats = projectBeats({ ...project, tracks: playTracks });
  const playOptions = playbackOptions(project, playTracks, gains, mix);

  // Start rendering this voice as soon as it's previewed, so Play is immediate.
  const previewSource = playOptions.tracks.find(t => t.id === 'preview')?.audio;
  useEffect(() => { if (previewSource) loadAudio(previewSource).catch(() => {}); }, [previewSource?.key]);

  if (!melody) return <>
    <Header/>
    <div className="scroll">
      <Top title={project.title} meta="No melody yet"/>
      <div className="blank"><b>Nothing on the tape</b><p className="meta">Record a melody to start.</p></div>
    </div>
    <button className="cta" onClick={() => go('record')}><i className="dot"/>GO TO RECORD</button>
  </>;

  const isOn = id => (mix.solo ? mix.solo === id : !mix.mute[id]);

  function openPicker(slot) {
    setPicking({ slot, index: 0 });
  }
  function placeTrack(track, toast) {
    setProject(p => {
      const tracks = [...p.tracks];
      tracks[picking.slot] = track;
      return { ...p, tracks };
    });
    showToast(toast);
    setPicking(null);
  }
  function keepHarmony() {
    const { id, name, style, backing, chords, notes, part } = option;
    placeTrack({ ...makeTrack({ id: `harmony-${id}`, name, role: 'harmony', notes }), style, backing, chords, part, basis },
      `${name.toUpperCase()} ON TRACK ${picking.slot + 1}`);
  }
  function keep() {
    const { voice } = option;
    const { result } = entry;
    const track = { ...makeTrack({ id: `counter-${voice}`, name: `${capitalize(voice)} counter`, role: 'counter', voice, notes: result.notes }),
      style: result.style, chords: result.chords, fallback: result.fallback, basis: basisOf(project) };
    placeTrack(track, `${voice.toUpperCase()} COUNTER ON TRACK ${picking.slot + 1}`);
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
      const desc = option.kind === 'harmony' ? option.desc
        : option.kind === 'status' ? (engine?.error || 'Loading…')
        : entry?.loading ? 'Writing a line…' : entry?.error ? entry.error
          : entry?.result ? `${entry.result.style === 'calm' ? 'calm' : 'active'}${entry.result.fallback ? ' · safe' : ''} · chords ${chordText(entry.result.chords)}` : '';
      rows.push(<div key={i} className="trk" style={{ background: color }}>
        <div className="row"><span className="nm">{t ? t.name : `Track ${i + 1}`}</span>
          {t && t.role !== 'melody' && <button className="x" aria-label="Remove track" onClick={() => remove(i)}>⌫</button>}
          <button className="x" aria-label="Close picker" onClick={() => setPicking(null)}>×</button></div>
        <div className="pick">
          <button className="arrow" aria-label="Previous option" onClick={() => setPicking(p => ({ ...p, index: (p.index - 1 + options.length) % options.length }))}>{Icon.left}</button>
          <div className="mid" aria-live="polite">
            <b>{option.kind === 'harmony' ? option.label : option.kind === 'status' ? 'HARMONY' : `${option.voice.toUpperCase()} COUNTER`}</b>
            <span>{desc}</span>
            <span className="dots" aria-label={`Option ${options.indexOf(option) + 1} of ${options.length}`}>{options.map((_, k) => <i key={k} className={options[k] === option ? 'on' : ''}/>)}</span>
          </div>
          <button className="arrow" aria-label="Next option" onClick={() => setPicking(p => ({ ...p, index: (p.index + 1) % options.length }))}>{Icon.right}</button>
        </div>
      </div>);
    } else if (t) {
      const small = t.role === 'melody' ? `Your recording · ${project.key}`
        : t.role === 'harmony' ? (t.basis === basis ? `${t.style} · chords ${chordText(t.chords)}` : 'Melody changed · tap to pick again')
        : refreshing && t.basis !== basisOf(project) ? 'Updating…'
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
        <span className="nm">Add a part</span>{Icon.plus}</button>);
    }
  }

  let cta;
  if (picking) {
    if (option.kind === 'harmony') cta = <button className="cta" onClick={keepHarmony}>KEEP {option.label}</button>;
    else if (option.kind === 'status') cta = <button className="cta" disabled>{engine?.error ? 'TRY A COUNTER-MELODY' : 'THINKING…'}</button>;
    else if (entry?.result) cta = <button className="cta" onClick={keep}>KEEP {option.voice.toUpperCase()} COUNTER</button>;
    else cta = <button className="cta" disabled>{entry?.error ? 'TRY ANOTHER VOICE' : 'WRITING…'}</button>;
  } else if (project.tracks.length > 1) cta = <button className="cta" onClick={() => setSharing(true)}>SHARE WITH FRIENDS</button>;
  else cta = <button className="cta" onClick={() => go('split')}>CHOOSE YOUR HARMONIES</button>;

  const togglePlay = () => (playback.playing ? playback.stop() : playback.play({ ...playOptions, totalBeats }));
  const bandOn = bandFits(playTracks);
  const showBand = hasBand(project);
  return <>
    <Header>
      <button className="ghost" aria-label="Settings" title="Tempo, key, time signature…" onClick={() => setSettings(true)}>{Icon.gear}</button>
      <button className="ghost" aria-label="Sheet music" title="Sheet music" onClick={() => setScore(true)}>{Icon.score}</button>
    </Header>
    <div className="scroll">
      <Top title={project.title} meta={playback.preparing ? 'Rendering voices…' : `${project.key} · ${project.tempo} bpm · ${project.timeSignature}`} beat={playback.beat} timeSignature={project.timeSignature}
        playing={playback.playing} onPlay={togglePlay}/>
      <section className="panel mix" aria-label="All tracks layered">
        <PianoRoll totalBeats={totalBeats} beatsPerBar={bar} beat={playback.playing ? playback.beat : 0}
          tracks={[...project.tracks.map((t, i) => (picking?.slot === i ? null : { id: t.id, color: TRACK_COLORS[i], notes: t.notes, dim: !isOn(t.id) })).filter(Boolean),
            ...(preview ? [{ id: 'preview', color: TRACK_COLORS[picking.slot], notes: preview.notes, variant: 'preview' }] : [])]}/>
      </section>
      <section className="tracks" aria-label="Tracks">{rows}
        {showBand && <div className={`trk${bandOn && (mix.solo ? mix.solo === 'band' : !mix.mute.band) ? '' : ' off'}`} style={{ background: 'var(--cream)' }}>
          <div className="row"><span className="nm">Band{!bandOn && <small>Off with new chords</small>}</span>
            <MuteSolo id="band" name="Band" mix={mix} setMix={setMix}/></div>
        </div>}
      </section>
    </div>
    {cta}
    {score && <ScoreSheet project={project} setProject={setProject} onClose={() => setScore(false)}/>}
    {sharing && <ShareSheet project={project} setProject={setProject} showToast={showToast} onClose={() => setSharing(false)}/>}
    {settings && <SettingsSheet project={project} setProject={setProject} onClose={() => setSettings(false)}/>}
  </>;
}
