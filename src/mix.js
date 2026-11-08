// Per-listener mix: volume, mute, solo, and the choir learning-track modes (spec 1.1/1.2).

/** Gain per track. Learning-track modes (solo / predominant / missing) apply on Parts and Practice. */
export function mixGains(tracks, mix, { learning = false } = {}) {
  const gains = {};
  for (const t of tracks) {
    let g = mix.volume[t.id] ?? 0.8;
    if (mix.solo ? mix.solo !== t.id : mix.mute[t.id]) g = 0;
    if (learning && mix.singing && tracks.some(x => x.id === mix.singing)) {
      const mine = t.id === mix.singing;
      if (mix.mode === 'solo' && !mine) g = 0;
      if (mix.mode === 'pred' && !mine) g *= 0.25;
      if (mix.mode === 'miss' && mine) g = 0;
    }
    gains[t.id] = g;
  }
  return gains;
}
