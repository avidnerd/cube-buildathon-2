// Split: every way the engine can split the melody into harmonies. Listen to
// each arrangement, or to one voice of it, then pick the one to keep.
import React, { useEffect, useState } from 'react';
import { arrangementsFrom, harmonyBasis, leadForArrangement, requestHarmonyOptions, timingOf, trackFromVoice } from '../harmonyApi.js';
import { playbackOptions } from '../playbackSources.js';
import { projectBeats } from '../project.js';
import { Header, Icon, Top } from '../ui/kit.jsx';

const OPEN_MIX = { mute: {}, solo: null };
const VOICE_GAIN = 0.8;

export function SplitScreen({ project, setProject, playback, showToast, go }) {
  const melody = project.tracks.find(t => t.role === 'melody');
  const basis = melody ? harmonyBasis(melody) : '';
  const [engine, setEngine] = useState(null);
  const [chosen, setChosen] = useState(project.arrangement ?? 'classic');
  const [listening, setListening] = useState(null); // { arrangement, voice }

  useEffect(() => {
    if (!melody || project.shared) return;
    let current = true;
    setEngine({ loading: true });
    requestHarmonyOptions(melody, { tempo: project.tempo, timeSignature: project.timeSignature })
      .then(data => {
        if (!current) return;
        setEngine({ arrangements: arrangementsFrom(data, timingOf(melody, project.tempo).shift) });
        const found = data.paths[0]?.key;
        if (found) setProject(p => ({ ...p, key: `${found.tonic} ${found.mode}` }));
      })
      .catch(error => current && setEngine({ error: error.message }));
    return () => { current = false; };
  }, [basis, project.timeSignature]);

  if (!melody) return <>
    <Header/>
    <div className="scroll"><Top title={project.title} meta="No melody yet"/>
      <div className="blank"><b>Nothing to split yet</b><p className="meta">Record a melody first.</p></div></div>
    <button className="cta" onClick={() => go('record')}><i className="dot"/>GO TO RECORD</button>
  </>;

  const isListening = (arrangement, voice) => playback.playing && listening?.arrangement === arrangement && listening?.voice === voice;

  function listen(arrangement, voice = null) {
    setChosen(arrangement.id);
    if (isListening(arrangement.id, voice?.id ?? null)) { playback.stop(); return; }
    setListening({ arrangement: arrangement.id, voice: voice?.id ?? null });
    const harmony = arrangement.voices.filter(v => !v.isLead).map(v => trackFromVoice(v, arrangement, basis));
    const lead = leadForArrangement(melody, arrangement);
    const tracks = !voice ? [lead, ...harmony] : voice.isLead ? [lead] : [trackFromVoice(voice, arrangement, basis)];
    const gains = Object.fromEntries(tracks.map(t => [t.id, VOICE_GAIN]));
    const options = playbackOptions(project, tracks, gains, OPEN_MIX);
    if (voice) options.gains.band = 0;
    playback.play({ ...options, totalBeats: projectBeats({ ...project, tracks }) });
  }

  function keep() {
    const arrangement = engine.arrangements.find(a => a.id === chosen);
    const harmony = arrangement.voices.filter(v => !v.isLead).map(v => trackFromVoice(v, arrangement, basis));
    setProject(p => ({ ...p, arrangement: chosen, tracks: [leadForArrangement(p.tracks.find(t => t.role === 'melody'), arrangement), ...harmony] }));
    showToast(`${arrangement.name} KEPT`);
    go('arrange');
  }

  const picked = engine?.arrangements?.find(a => a.id === chosen);
  return <>
    <Header/>
    <div className="scroll">
      <Top title="Split" meta={playback.preparing ? 'Loading voices…' : undefined}/>
      {engine?.loading && <div className="blank"><b>Writing harmonies…</b></div>}
      {engine?.error && <p className="msg err" role="alert">{engine.error}</p>}
      <section className="arrs" aria-label="Arrangements">
        {engine?.arrangements?.map(a => <article key={a.id} className={`arr${a.id === chosen ? ' on' : ''}`}>
          <div className="arr-head">
            <button className="nm" aria-pressed={a.id === chosen} onClick={() => setChosen(a.id)}>{a.name}<small>{a.desc}</small></button>
            <button className="play" aria-label={`Listen to ${a.name}`} aria-pressed={isListening(a.id, null)} onClick={() => listen(a)}>{isListening(a.id, null) ? Icon.stop : Icon.play}</button>
          </div>
          <div className="voices" role="group" aria-label={`Voices of ${a.name}`}>
            {a.voices.map(v => <button key={v.id} aria-pressed={isListening(a.id, v.id)} onClick={() => listen(a, v)}>{v.label}{v.isLead ? ' (you)' : ''}</button>)}
          </div>
        </article>)}
      </section>
    </div>
    <button className="cta" disabled={!picked} onClick={keep}>{picked ? `USE ${picked.name}` : 'WRITING…'}</button>
  </>;
}
