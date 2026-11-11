// Karaoke: pick your part and sing it, with the words lighting up on the
// singer's real timing. Also where friends land from a share link.
import React, { useMemo } from 'react';
import { TRACK_COLORS, beatsPerBar } from '../project.js';
import { karaokeGains, mixGains } from '../mix.js';
import { playbackOptions } from '../playbackSources.js';
import { karaokeLines, lineIndexAt, noteName } from '../karaoke.js';
import { Header, PianoRoll, Top } from '../ui/kit.jsx';
import { useLiveGains } from './Arrange.jsx';
import { subLabel } from './Parts.jsx';

const COUNT_IN_BEATS = 4;

function Line({ line, beat, live }) {
  if (!line.syllables.length) return <>♪</>;
  return line.syllables.map(s => <React.Fragment key={s.index}>{s.space ? ' ' : ''}
    <span className={live && beat >= s.end ? 'sung' : live && beat >= s.start ? 'now' : ''}>{s.text}</span></React.Fragment>);
}

export function KaraokeScreen({ project, playback, mix, setMix, go, totalBeats }) {
  const tracks = project.tracks;
  const melody = tracks.find(t => t.role === 'melody');
  const index = tracks.findIndex(t => t.id === mix.singing);
  const mine = tracks[index];
  const lines = useMemo(() => karaokeLines(melody?.notes ?? []), [melody?.notes]);
  const mode = mix.mode === 'miss' ? 'miss' : 'pred';
  const gains = karaokeGains(mixGains(tracks, { ...mix, mode, solo: null, mute: {} }, { learning: true }), mine?.id, mode);
  const options = playbackOptions(project, tracks, gains, { mute: {}, solo: null });
  useLiveGains(playback, options.gains);

  if (!melody) return <>
    <Header/>
    <div className="scroll"><Top title="Karaoke" meta="No song yet"/>
      <div className="blank"><b>Nothing to sing yet</b><p className="meta">Record a melody first.</p></div></div>
    <button className="cta" onClick={() => go('record')}><i className="dot"/>GO TO RECORD</button>
  </>;

  const beat = playback.playing ? playback.beat : 0;
  const current = lineIndexAt(lines, beat);
  const line = lines[current];
  const next = lines[current + 1];
  const until = playback.playing && line ? Math.ceil(line.start - beat) : 0;
  const windowNotes = mine && line ? mine.notes.filter(n => n.start < line.end && n.start + n.duration > line.start).map(n => ({ ...n, start: n.start - line.start })) : [];
  const singingNow = mine?.notes.find(n => beat >= n.start && beat < n.start + n.duration);
  const start = () => playback.play({ ...options, totalBeats });

  return <>
    <Header>{project.shared && <a className="ghost txt" href="/">Make your own</a>}</Header>
    <div className="scroll">
      <Top title={project.shared ? project.title : 'Karaoke'} meta={playback.preparing ? 'Loading the voices…' : mine ? `Singing ${mine.name}` : 'Pick the part you sing'}
        beat={playback.beat} timeSignature={project.timeSignature}/>
      <p className="label">I'm singing</p>
      <div className="who">{tracks.map((t, i) => <button key={t.id} aria-pressed={mix.singing === t.id}
        style={mix.singing === t.id ? { background: TRACK_COLORS[i] } : undefined}
        onClick={() => { playback.stop(); setMix(m => ({ ...m, singing: t.id })); }}>
        <i style={{ background: TRACK_COLORS[i] }}/><span><b>{t.name}</b>{subLabel(t) && <small>{subLabel(t)}</small>}</span></button>)}
      </div>
      {mine && <>
        <section className="panel kara" aria-live="off" aria-label="Lyrics">
          <div className="kara-now">{until > 0 && until <= COUNT_IN_BEATS ? <span className="count">{until}</span> : <span className="pitch">{singingNow ? noteName(singingNow.pitch) : ''}</span>}</div>
          <p className="kara-line">{line ? <Line line={line} beat={beat} live={playback.playing}/> : ''}</p>
          <p className="kara-next">{next ? <Line line={next} beat={0} live={false}/> : ''}</p>
        </section>
        <section className="panel kara-roll" aria-label="Your notes for this line">
          {line && <PianoRoll tracks={[{ id: mine.id, color: TRACK_COLORS[index], notes: windowNotes }]} totalBeats={Math.max(1, line.end - line.start)}
            beatsPerBar={beatsPerBar(project.timeSignature)} beat={playback.playing ? beat - line.start : null}/>}
        </section>
        <div className="loop"><div className="seg" role="group" aria-label="Guide">
          <button aria-pressed={mode === 'pred'} onClick={() => setMix(m => ({ ...m, mode: 'pred' }))}>Guide on</button>
          <button aria-pressed={mode === 'miss'} onClick={() => setMix(m => ({ ...m, mode: 'miss' }))}>My part off</button>
        </div></div>
      </>}
    </div>
    <button className="cta" disabled={!mine || playback.preparing} onClick={() => (playback.playing ? playback.stop() : start())}>
      {playback.playing ? 'STOP' : playback.preparing ? 'LOADING…' : mine ? 'SING' : 'PICK YOUR PART'}
    </button>
  </>;
}
