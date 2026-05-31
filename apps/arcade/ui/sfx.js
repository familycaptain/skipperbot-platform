// =============================================================================
// Arcade sound effects — procedural Web Audio (no asset files)
// =============================================================================
// Every effect is synthesized at runtime with the Web Audio API, so there are
// no .wav/.mp3 files to ship, it works offline, and it suits the retro/vector
// feel of the games. One shared AudioContext is created lazily; browsers block
// audio until a user gesture, so each game calls resume() from its start
// button handler. Mute state persists in localStorage and is shared across
// games via a tiny subscriber list (so the ArcadeApp header toggle stays in
// sync with every game).

let ctx = null;
let masterGain = null;
let muted = false;
const VOLUME = 0.35;
const listeners = new Set();

try {
  muted = localStorage.getItem("arcade_muted") === "1";
} catch {
  /* localStorage unavailable — default unmuted */
}

function ac() {
  if (ctx) return ctx;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  ctx = new AC();
  masterGain = ctx.createGain();
  masterGain.gain.value = muted ? 0 : VOLUME;
  masterGain.connect(ctx.destination);
  return ctx;
}

/** Call from a user-gesture handler (e.g. the game's Start button). */
export function resume() {
  const c = ac();
  if (c && c.state === "suspended") c.resume();
}

export function isMuted() {
  return muted;
}

export function setMuted(next) {
  muted = !!next;
  try {
    localStorage.setItem("arcade_muted", muted ? "1" : "0");
  } catch {
    /* ignore */
  }
  if (masterGain && ctx) {
    masterGain.gain.setTargetAtTime(muted ? 0 : VOLUME, ctx.currentTime, 0.01);
  }
  listeners.forEach((fn) => fn(muted));
}

export function toggleMuted() {
  setMuted(!muted);
  return muted;
}

/** Subscribe to mute changes; returns an unsubscribe fn. */
export function onMuteChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// ---- primitives -----------------------------------------------------------

function tone({ type = "sine", freq = 440, freqEnd = null, dur = 0.15, gain = 0.4, attack = 0.005, delay = 0 }) {
  const c = ac();
  if (!c || muted) return;
  const t0 = c.currentTime + delay;
  const osc = c.createOscillator();
  const g = c.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (freqEnd != null) {
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, freqEnd), t0 + dur);
  }
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.linearRampToValueAtTime(gain, t0 + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.connect(g);
  g.connect(masterGain);
  osc.start(t0);
  osc.stop(t0 + dur + 0.02);
}

function noise({ dur = 0.3, gain = 0.4, filter = "lowpass", freq = 1000, delay = 0 }) {
  const c = ac();
  if (!c || muted) return;
  const t0 = c.currentTime + delay;
  const n = Math.max(1, Math.floor(c.sampleRate * dur));
  const buf = c.createBuffer(1, n, c.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < n; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / n); // decaying white noise
  const src = c.createBufferSource();
  src.buffer = buf;
  const filt = c.createBiquadFilter();
  filt.type = filter;
  filt.frequency.value = freq;
  const g = c.createGain();
  g.gain.setValueAtTime(gain, t0);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  src.connect(filt);
  filt.connect(g);
  g.connect(masterGain);
  src.start(t0);
  src.stop(t0 + dur);
}

function arpeggio(freqs, { type = "triangle", step = 0.08, dur = 0.13, gain = 0.22 } = {}) {
  freqs.forEach((f, i) => tone({ type, freq: f, dur, gain, delay: i * step }));
}

// ---- named effects (used by the games) ------------------------------------

export const sfx = {
  laser: () => tone({ type: "square", freq: 900, freqEnd: 220, dur: 0.12, gain: 0.16 }),
  thrust: () => noise({ dur: 0.1, gain: 0.05, filter: "lowpass", freq: 480 }),
  explode: () => noise({ dur: 0.45, gain: 0.5, filter: "lowpass", freq: 700 }),
  smallExplode: () => noise({ dur: 0.22, gain: 0.32, filter: "lowpass", freq: 1100 }),
  hit: () => tone({ type: "square", freq: 200, freqEnd: 70, dur: 0.18, gain: 0.3 }),
  pickup: () => arpeggio([660, 990], { type: "sine", step: 0.07, dur: 0.11, gain: 0.24 }),
  place: () => tone({ type: "triangle", freq: 320, freqEnd: 560, dur: 0.1, gain: 0.2 }),
  shoot: () => tone({ type: "triangle", freq: 660, freqEnd: 440, dur: 0.07, gain: 0.12 }),
  wave: () => arpeggio([440, 554, 659], { type: "square", step: 0.08, dur: 0.12, gain: 0.18 }),
  start: () => arpeggio([392, 523, 659], { type: "triangle", step: 0.09, dur: 0.14, gain: 0.22 }),
  win: () => arpeggio([523, 659, 784, 1047], { type: "triangle", step: 0.1, dur: 0.16, gain: 0.22 }),
  gameover: () => arpeggio([330, 262, 196], { type: "sawtooth", step: 0.14, dur: 0.3, gain: 0.24 }),
};
