// Shared 4-Track building blocks. Visual spec: DESIGN.md and design/*.html.
import React, { useMemo, useRef, useState } from 'react';
import { counterText } from '../project.js';

const px = { fill: 'currentColor', shapeRendering: 'crispEdges' };
export const Icon = {
  volume: <svg width="22" height="22" viewBox="0 0 22 22" {...px}><rect x="2" y="8" width="4" height="6"/><rect x="6" y="6" width="2" height="10"/><rect x="8" y="4" width="2" height="14"/><rect x="10" y="2" width="2" height="18"/><rect x="14" y="8" width="2" height="6"/><rect x="18" y="4" width="2" height="14"/></svg>,
  muted: <svg width="22" height="22" viewBox="0 0 22 22" {...px}><rect x="2" y="8" width="4" height="6"/><rect x="6" y="6" width="2" height="10"/><rect x="8" y="4" width="2" height="14"/><rect x="10" y="2" width="2" height="18"/><rect x="14" y="7" width="2" height="2"/><rect x="18" y="7" width="2" height="2"/><rect x="16" y="9" width="2" height="4"/><rect x="14" y="13" width="2" height="2"/><rect x="18" y="13" width="2" height="2"/></svg>,
  person: <svg width="22" height="22" viewBox="0 0 22 22" {...px}><rect x="8" y="2" width="6" height="7"/><rect x="6" y="11" width="10" height="2"/><rect x="4" y="13" width="14" height="7"/></svg>,
  play: <svg width="14" height="14" viewBox="0 0 14 14" {...px}><rect x="2" y="1" width="2" height="12"/><rect x="4" y="3" width="2" height="8"/><rect x="6" y="4" width="2" height="6"/><rect x="8" y="5" width="2" height="4"/><rect x="10" y="6" width="2" height="2"/></svg>,
  stop: <svg width="14" height="14" viewBox="0 0 14 14" {...px}><rect x="2" y="2" width="10" height="10"/></svg>,
  left: <svg width="10" height="12" viewBox="0 0 10 12" {...px}><rect x="6" y="0" width="2" height="12"/><rect x="4" y="2" width="2" height="8"/><rect x="2" y="4" width="2" height="4"/></svg>,
  right: <svg width="10" height="12" viewBox="0 0 10 12" {...px}><rect x="2" y="0" width="2" height="12"/><rect x="4" y="2" width="2" height="8"/><rect x="6" y="4" width="2" height="4"/></svg>,
  plus: <svg width="18" height="18" viewBox="0 0 24 24" {...px}><rect x="10" y="3" width="4" height="18"/><rect x="3" y="10" width="18" height="4"/></svg>,
  gear: <svg width="18" height="18" viewBox="0 0 16 16" {...px}><rect x="7" y="1" width="2" height="2"/><rect x="7" y="13" width="2" height="2"/><rect x="1" y="7" width="2" height="2"/><rect x="13" y="7" width="2" height="2"/><rect x="3" y="3" width="2" height="2"/><rect x="11" y="3" width="2" height="2"/><rect x="3" y="11" width="2" height="2"/><rect x="11" y="11" width="2" height="2"/><rect x="5" y="4" width="6" height="2"/><rect x="5" y="10" width="6" height="2"/><rect x="4" y="5" width="2" height="6"/><rect x="10" y="5" width="2" height="6"/></svg>,
  score: <svg width="18" height="18" viewBox="0 0 16 16" {...px}><rect x="1" y="3" width="14" height="1"/><rect x="1" y="6" width="14" height="1"/><rect x="1" y="9" width="14" height="1"/><rect x="1" y="12" width="14" height="1"/><rect x="9" y="2" width="2" height="9"/><rect x="6" y="9" width="4" height="3"/></svg>,
  record: <svg viewBox="0 0 22 22" {...px}><rect x="7" y="2" width="8" height="12"/><rect x="4" y="10" width="2" height="4"/><rect x="16" y="10" width="2" height="4"/><rect x="5" y="14" width="12" height="2"/><rect x="10" y="16" width="2" height="3"/><rect x="7" y="19" width="8" height="2"/></svg>,
  arrange: <svg viewBox="0 0 22 22" {...px}><rect x="2" y="4" width="18" height="3"/><rect x="2" y="9" width="12" height="3"/><rect x="2" y="14" width="15" height="3"/></svg>,
  parts: <svg viewBox="0 0 22 22" {...px}><rect x="3" y="3" width="2" height="16"/><rect x="10" y="3" width="2" height="16"/><rect x="17" y="3" width="2" height="16"/><rect x="1" y="12" width="6" height="3"/><rect x="8" y="6" width="6" height="3"/><rect x="15" y="10" width="6" height="3"/></svg>,
  split: <svg viewBox="0 0 22 22" {...px}><rect x="2" y="10" width="7" height="2"/><rect x="9" y="4" width="2" height="14"/><rect x="11" y="4" width="9" height="2"/><rect x="11" y="10" width="9" height="2"/><rect x="11" y="16" width="9" height="2"/></svg>,
  karaoke: <svg viewBox="0 0 22 22" {...px}><rect x="13" y="2" width="7" height="7"/><rect x="11" y="8" width="3" height="3"/><rect x="8" y="11" width="3" height="3"/><rect x="5" y="14" width="3" height="3"/><rect x="2" y="17" width="3" height="3"/></svg>,
  practice: <svg viewBox="0 0 22 22" {...px}><rect x="2" y="13" width="3" height="3"/><rect x="5" y="10" width="3" height="3"/><rect x="8" y="12" width="3" height="3"/><rect x="11" y="7" width="3" height="3"/><rect x="14" y="9" width="3" height="3"/><rect x="17" y="5" width="3" height="3"/></svg>,
};

export function Header({ children }) {
  return <div className="hdr">
    <a className="mark" href="#new" title="Record a new take" aria-label="4-Track: record a new take"><img src="/logo.png" alt=""/></a>
    <span className="right">{children}</span>
  </div>;
}

export function Top({ title, meta, beat, timeSignature, playing, onPlay, canPlay = true, children }) {
  return <div className="top">
    <div className="t"><h1>{title}</h1>{meta && <p className="meta">{meta}</p>}</div>
    {beat !== undefined && <div className="counter" aria-label="Position">{counterText(beat, timeSignature)}</div>}
    {onPlay && <button className="play" aria-label={playing ? 'Stop' : 'Play'} aria-pressed={playing} disabled={!canPlay} onClick={onPlay}>{playing ? Icon.stop : Icon.play}</button>}
    {children}
  </div>;
}

const TABS = [['record', 'Record'], ['split', 'Split'], ['arrange', 'Arrange'], ['parts', 'Parts'], ['karaoke', 'Karaoke']];
const SHARED_TABS = [['karaoke', 'Karaoke'], ['parts', 'Mix'], ['practice', 'Practice']];
export function TabBar({ current, shared = false }) {
  return <nav className="tabbar" aria-label="Main">
    {(shared ? SHARED_TABS : TABS).map(([id, label]) => <a key={id} href={`#${id}`} aria-current={current === id ? 'page' : undefined}>{Icon[id]}{label}</a>)}
  </nav>;
}

export function useToast() {
  const [text, setText] = useState('');
  const [on, setOn] = useState(false);
  const timer = useRef(0);
  const show = message => {
    setText(message); setOn(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOn(false), 2000);
  };
  return [<div key="toast" className={`toast${on ? ' on' : ''}`} role="status">{text}</div>, show];
}

/** The one piano roll. tracks: [{ id, color, notes, dim, variant: 'target'|'preview' }]. */
export function PianoRoll({ tracks, totalBeats, beatsPerBar = 4, beat = null, range, hint }) {
  const pitches = tracks.flatMap(t => t.notes.map(n => n.pitch));
  const [lo, hi] = useMemo(() => {
    if (range) return range;
    if (!pitches.length) return [55, 76];
    const min = Math.min(...pitches), max = Math.max(...pitches);
    const pad = Math.max(2, Math.ceil((14 - (max - min)) / 2));
    return [min - pad, max + pad];
  }, [range, pitches.join(',')]);
  const rows = hi - lo + 1;
  const x = b => `${(b / totalBeats) * 100}%`;
  const lines = [];
  for (let b = 1; b < totalBeats; b++)
    lines.push(<i key={b} className={b % beatsPerBar ? 'beatline' : 'barline'} style={{ left: x(b) }}/>);
  return <div className="roll-wrap">
    {lines}
    {tracks.map(t => t.notes.map((n, i) => n.pitch >= lo && n.pitch <= hi && <i key={`${t.id}-${i}`}
      className={`n${t.variant ? ' ' + t.variant : ''}`}
      style={{
        left: `calc(${x(n.start)} + 1px)`, width: `calc(${x(n.duration)} - 3px)`,
        top: `${((hi - n.pitch) / rows) * 100}%`, height: `calc(${100 / rows}% - 1px)`, minHeight: 4,
        background: t.color, opacity: t.dim ? 0.12 : 1,
      }}/>))}
    {beat !== null && beat >= 0 && <i className="ph" style={{ left: x(Math.min(beat, totalBeats)) }}/>}
    {hint && !pitches.length && <div className="roll-hint">{hint}</div>}
  </div>;
}

/** Vertical fader (0..1) with pointer drag and arrow keys. */
export function Fader({ value, color, dim, label, onChange }) {
  const ref = useRef(null);
  const fromPointer = e => {
    const r = ref.current.getBoundingClientRect();
    onChange(Math.round(Math.max(0, Math.min(1, (r.bottom - e.clientY) / r.height)) * 100) / 100);
  };
  return <div ref={ref} className="fader" role="slider" tabIndex={0} aria-label={`${label} volume`}
    aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}
    onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); fromPointer(e); }}
    onPointerMove={e => e.buttons && fromPointer(e)}
    onKeyDown={e => {
      const step = { ArrowUp: 0.05, ArrowRight: 0.05, ArrowDown: -0.05, ArrowLeft: -0.05 }[e.key];
      if (step) { e.preventDefault(); onChange(Math.round(Math.max(0, Math.min(1, value + step)) * 100) / 100); }
    }}>
    <div className="lvl" style={{ height: `${value * 100}%`, background: color, opacity: dim ? 0.35 : 1 }}/>
    <div className="cap" style={{ bottom: `calc(${value * 100}% - 4px)` }}/>
  </div>;
}
