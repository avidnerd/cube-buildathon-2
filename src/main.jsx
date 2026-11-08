import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { loadProject, saveProject, projectBeats } from './project.js';
import { player } from './player.js';
import { basisOf, refreshCounters, staleCounters } from './arrangement.js';
import { RecordScreen } from './screens/Record.jsx';
import { ArrangeScreen } from './screens/Arrange.jsx';
import { PartsScreen } from './screens/Parts.jsx';
import { PracticeScreen } from './screens/Practice.jsx';
import { TabBar, useToast } from './ui/kit.jsx';
import './4track.css';
import './app.css';

const SCREENS = ['record', 'arrange', 'parts', 'practice'];
const MIX_KEY = '4track.mix.v1';
const screenFromHash = () => (SCREENS.includes(location.hash.slice(1)) ? location.hash.slice(1) : null);

/** Each listener's mix lives on their own device (spec 1.2). */
function loadMix() {
  try { return { singing: null, mode: 'pred', volume: {}, mute: {}, solo: null, ...JSON.parse(localStorage.getItem(MIX_KEY)) }; }
  catch { return { singing: null, mode: 'pred', volume: {}, mute: {}, solo: null }; }
}

/** One transport for the whole app: play / stop and a live playhead in beats. */
function usePlayback() {
  const [playing, setPlaying] = useState(false);
  const [beat, setBeat] = useState(0);
  const raf = useRef(0);
  const stop = () => { player.stop(); cancelAnimationFrame(raf.current); setPlaying(false); setBeat(0); };
  async function play(options) {
    stop();
    await player.play({ ...options, onEnd: () => { cancelAnimationFrame(raf.current); setPlaying(false); setBeat(0); } });
    setPlaying(true);
    const tick = () => { setBeat(player.position()); raf.current = requestAnimationFrame(tick); };
    tick();
  }
  useEffect(() => () => stop(), []);
  return { playing, beat, play, stop };
}

function App() {
  const [project, setProject] = useState(loadProject);
  const [screen, setScreen] = useState(() => screenFromHash() || (project.tracks.length ? 'arrange' : 'record'));
  const [takes, setTakes] = useState([]);
  const [mix, setMix] = useState(loadMix);
  const playback = usePlayback();
  const [toast, showToast] = useToast();

  useEffect(() => saveProject(project), [project]);

  // Rewrite counter-melodies whose melody, key or meter has changed (debounced).
  const [refreshing, setRefreshing] = useState(false);
  const basis = basisOf(project);
  useEffect(() => {
    if (!staleCounters(project).length) return;
    const timer = setTimeout(async () => {
      setRefreshing(true);
      try {
        const updated = await refreshCounters(project);
        setProject(p => (basisOf(p) !== basis ? p : { ...p, tracks: p.tracks.map(t => updated.find(u => u.id === t.id) ?? t) }));
        showToast('COUNTER-MELODIES UPDATED');
      } catch (e) {
        showToast('COULD NOT UPDATE COUNTER-MELODY');
      } finally { setRefreshing(false); }
    }, 500);
    return () => clearTimeout(timer);
  }, [basis]);
  useEffect(() => { try { localStorage.setItem(MIX_KEY, JSON.stringify(mix)); } catch { /* private mode */ } }, [mix]);
  useEffect(() => {
    const onHash = () => { const s = screenFromHash(); if (s) setScreen(s); };
    addEventListener('hashchange', onHash);
    return () => removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => { if (location.hash.slice(1) !== screen) history.replaceState(null, '', `#${screen}`); playback.stop(); }, [screen]);

  const go = s => { location.hash = s; };
  const shared = { project, setProject, playback, mix, setMix, showToast, go, refreshing, totalBeats: projectBeats(project) };
  return <main className="phone" aria-label="4-Track">
    {screen === 'record' && <RecordScreen {...shared} takes={takes} setTakes={setTakes}/>}
    {screen === 'arrange' && <ArrangeScreen {...shared}/>}
    {screen === 'parts' && <PartsScreen {...shared}/>}
    {screen === 'practice' && <PracticeScreen {...shared}/>}
    {toast}
    <TabBar current={screen}/>
  </main>;
}

createRoot(document.getElementById('root')).render(<App/>);
