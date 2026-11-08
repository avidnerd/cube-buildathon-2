import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { emptyProject, loadProject, saveProject, projectBeats } from './project.js';
import { player } from './player.js';
import { basisOf, refreshCounters, staleCounters } from './arrangement.js';
import { isShareLink, loadSharedSong } from './share.js';
import { RecordScreen } from './screens/Record.jsx';
import { SplitScreen } from './screens/Split.jsx';
import { KaraokeScreen } from './screens/Karaoke.jsx';
import { ArrangeScreen } from './screens/Arrange.jsx';
import { PartsScreen } from './screens/Parts.jsx';
import { PracticeScreen } from './screens/Practice.jsx';
import { TabBar, useToast } from './ui/kit.jsx';
import './4track.css';
import './app.css';

const SCREENS = ['record', 'split', 'arrange', 'parts', 'practice', 'karaoke'];
const MIX_KEY = '4track.mix.v1';
const screenFromHash = () => {
  const hash = location.hash.slice(1);
  if (hash === 'new') return 'record'; // the logo: start a new take
  return SCREENS.includes(hash) ? hash : null;
};

/** Each listener's mix lives on their own device (spec 1.2). */
function loadMix() {
  try { return { singing: null, mode: 'pred', volume: {}, mute: {}, solo: null, ...JSON.parse(localStorage.getItem(MIX_KEY)) }; }
  catch { return { singing: null, mode: 'pred', volume: {}, mute: {}, solo: null }; }
}

/** One transport for the whole app: play / stop and a live playhead in beats. */
function usePlayback() {
  const [playing, setPlaying] = useState(false);
  const [beat, setBeat] = useState(0);
  const [preparing, setPreparing] = useState(false); // waiting for voices to render
  const raf = useRef(0);
  const stop = () => { player.stop(); cancelAnimationFrame(raf.current); setPlaying(false); setPreparing(false); setBeat(0); };
  async function play(options) {
    stop();
    setPreparing(true);
    const started = await player.play({ ...options, onEnd: () => { cancelAnimationFrame(raf.current); setPlaying(false); setBeat(0); } });
    if (!started) return; // stopped, or replaced by a newer play, while loading
    setPreparing(false);
    setPlaying(true);
    const tick = () => { setBeat(player.position()); raf.current = requestAnimationFrame(tick); };
    tick();
  }
  useEffect(() => () => stop(), []);
  return { playing, preparing, beat, play, stop };
}

function App() {
  const opensShare = useRef(isShareLink()).current;
  const [project, setProject] = useState(() => (opensShare ? emptyProject() : loadProject()));
  const [shareState, setShareState] = useState(opensShare ? 'loading' : null); // loading | ready | error text
  const [screen, setScreen] = useState(() => (opensShare ? 'karaoke' : screenFromHash() || (project.tracks.length ? 'arrange' : 'record')));
  const [takes, setTakes] = useState([]);
  const [blankTake, setBlankTake] = useState(false);
  const [mix, setMix] = useState(loadMix);
  const playback = usePlayback();
  const [toast, showToast] = useToast();

  useEffect(() => { if (!opensShare) saveProject(project); }, [project]); // a friend's copy never replaces their own tape
  useEffect(() => {
    if (!opensShare) return;
    loadSharedSong()
      .then(song => { setProject(song); setMix(m => ({ ...m, singing: null, solo: null, mute: {}, volume: {} })); setShareState('ready'); })
      .catch(error => setShareState(error.message));
  }, []);

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
    const onHash = () => {
      if (location.hash === '#new') {
        if (opensShare) { location.href = '/#new'; return; } // a friend starts their own song
        history.replaceState(null, '', '#record');
        setBlankTake(true);
      }
      const s = screenFromHash();
      if (s) setScreen(s);
    };
    addEventListener('hashchange', onHash);
    return () => removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => { if (location.hash.slice(1) !== screen) history.replaceState(null, '', `#${screen}`); playback.stop(); }, [screen]);

  const go = s => { location.hash = s; };
  const shared = { project, setProject, playback, mix, setMix, showToast, go, refreshing, totalBeats: projectBeats(project) };
  if (opensShare && shareState !== 'ready') return <main className="phone" aria-label="4-Track">
    <div className="blank" style={{ marginTop: 120 }}><b>{shareState === 'loading' ? 'Loading the song…' : 'Song not found'}</b>
      <p className="meta">{shareState === 'loading' ? 'Getting everyone’s parts.' : shareState}</p></div>
  </main>;
  return <main className="phone" aria-label="4-Track">
    {screen === 'record' && <RecordScreen {...shared} takes={takes} setTakes={setTakes} blankTake={blankTake} clearBlankTake={() => setBlankTake(false)}/>}
    {screen === 'split' && <SplitScreen {...shared}/>}
    {screen === 'karaoke' && <KaraokeScreen {...shared}/>}
    {screen === 'arrange' && <ArrangeScreen {...shared}/>}
    {screen === 'parts' && <PartsScreen {...shared}/>}
    {screen === 'practice' && <PracticeScreen {...shared}/>}
    {toast}
    <TabBar current={screen} shared={opensShare}/>
  </main>;
}

createRoot(document.getElementById('root')).render(<App/>);
