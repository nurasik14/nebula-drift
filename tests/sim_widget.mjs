// Headless simulation of widget.html in Node (no dependencies): fakes the DOM, canvas and
// TelegramWidget, plays runs with an autopilot and counts canvas calls per drawn frame.
//   node tests/sim_widget.mjs [runs]
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../widget.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const RUNS = +process.argv[2] || 6;

function makeEnv({ width = 296, tw = true, mode = 'd', answers = [] } = {}) {
  let now = 0, rafQ = [], calls = 0, frameCalls = [], drawnFrames = 0, domWrites = 0, layoutReads = 0, requests = [];
  const pixels = new Set();
  function ctx(canvas, counted) {
    const target = {
      canvas, set font(v) {}, set textAlign(v) {}, set lineCap(v) {},
    };
    return new Proxy(target, {
      get(t, k) {
        if (k === 'canvas') return canvas;
        return (...a) => {
          if (counted) calls++;
          if (k === 'getImageData' || k === 'putImageData') throw new Error('forbidden ' + k);
          if (k === 'createRadialGradient' || k === 'createLinearGradient') return { addColorStop() {} };
        };
      },
      set(t, k, v) {
        if (counted) calls++;
        if (/shadow|globalCompositeOperation|filter/.test(k)) throw new Error('forbidden prop ' + k);
        return true;
      },
    });
  }
  function canvasEl(counted) {
    const el = { _w: 300, _h: 150, clientWidth: width, style: {} };
    Object.defineProperty(el, 'clientWidth', { get() { layoutReads++; return width; } });
    Object.defineProperty(el, 'width', { get() { return el._w; }, set(v) { el._w = v; pixels.add(el); } });
    Object.defineProperty(el, 'height', { get() { return el._h; }, set(v) { el._h = v; pixels.add(el); } });
    const c = ctx(el, counted);
    el.getContext = () => c;
    return el;
  }
  const els = {};
  function el(id) {
    if (!els[id]) {
      if (id === 'c') els[id] = canvasEl(true);
      else {
        const o = { _t: '' };
        for (const p of ['innerHTML', 'textContent', 'className'])
          Object.defineProperty(o, p, { get() { return o['_' + p] || ''; }, set(v) { domWrites++; o['_' + p] = String(v); } });
        els[id] = o;
      }
    }
    return els[id];
  }
  const store = {};
  const handlers = {};
  const TW = tw && {
    isPreview: false, isForward: false, chatData: JSON.stringify({ best: 40, streak: 2 }),
    themeParams: { text_color: '#000000', hint_color: '#707579', button_color: '#3390ec', accent_text_color: '#3390ec', destructive_text_color: '#e53935' },
    HapticFeedback: { impactOccurred() {}, notificationOccurred() {}, selectionChanged() {} },
    onEvent(t, f) { handlers[t] = f; }, ready() {},
    request(d) {
      if (typeof d !== 'string' || !d.length || Buffer.byteLength(d) > 64) throw new TypeError('bad data');
      requests.push(d);
      const a = answers.length ? answers.shift() : { result: JSON.stringify({ t: [['Ann', 90], ['Bo', 50]], n: 2, r: 2, d: 50, b: 50, k: 3 }) };
      return a.code ? Promise.reject(Object.assign(new Error(a.code), { code: a.code })) : Promise.resolve(a);
    },
    openTelegramLink() {},
  };
  const doc = {
    hidden: false,
    getElementById: el,
    createElement: () => canvasEl(false),
    addEventListener(type, f) { this['on' + type] = f; },
  };
  const ctxObj = {
    window: {}, document: doc, Math, JSON, Date, Promise, console,
    devicePixelRatio: 2,
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
    requestAnimationFrame: f => { rafQ.push(f); return rafQ.length; },
    performance: { now: () => now },
  };
  ctxObj.window.TelegramWidget = TW || undefined;
  if (mode) store.m = mode;
  vm.createContext(ctxObj);
  vm.runInContext(script, ctxObj, { filename: 'widget.js' });
  const env = {
    ctx: ctxObj, els, store, handlers, requests,
    get: expr => vm.runInContext(expr, ctxObj),
    tick(ms = 1000 / 60) {
      now += ms;
      const q = rafQ; rafQ = [];
      const before = calls;
      for (const f of q) f(now);
      const n = calls - before;
      if (n) { frameCalls.push(n); drawnFrames++; }
    },
    stats: () => ({ frameCalls, drawnFrames, domWrites, layoutReads, pixels: [...pixels].reduce((s, e) => s + e._w * e._h, 0) }),
    resetStats() { frameCalls = []; drawnFrames = 0; domWrites = 0; },
    tap() { el('c').onpointerdown?.({}); el('c').onclick?.(); },
    down() { el('c').onpointerdown?.({}); },
    click() { el('c').onclick?.(); },
  };
  return env;
}

// autopilot: hop when a lit (or soon lit) hazard on the current ring is close ahead and the other ring is clearer
function autopilot(env, reactMs) {
  const E = env.get('E'), A = env.get('A'), dr = env.get('dr'), rg = env.get('rg'), w = M.min(1.7 + env.get('t') * .028, 3.3);
  const P = Math.PI * 2;
  const ah = a => ((a - A) * dr % P + P * 1.5) % P - P / 2;
  const danger = r => {
    let m = 9;
    for (const e of E) if (e.k < 3 && e.r === r) {
      const d = ah(e.a), close = e.k === 1 ? 1.7 : 1;      // comets close faster
      if (d > -e.h) m = M.min(m, (d - e.h) / (w * close));  // seconds until contact
    }
    return m;
  };
  const here = danger(rg), there = danger(1 - rg);
  if (here < reactMs / 1000 + .12 && there > here) env.down();
}
const M = Math;

function playRun(seedMode, policy, maxSec = 240) {
  const env = makeEnv({ mode: seedMode });
  env.tick(); env.tick();
  env.resetStats();
  env.click();
  let frames = 0;
  while (env.get('st') === 1 && frames < maxSec * 60) {
    env.tick();
    if (frames % 2 === 0 && policy) policy(env);   // decisions at 30 Hz
    frames++;
  }
  // let the death animation and game over play out
  for (let i = 0; i < 90; i++) env.tick();
  return { env, secs: frames / 60, sc: env.get('sc'), ph: env.get('ph'), nm: env.get('nm'), st: env.get('st') };
}

let worst = 0, all = [];
const results = [];
for (let i = 0; i < RUNS; i++) {
  const r = playRun(i % 2 ? 'e' : 'd', e => autopilot(e, 180));
  const fc = r.env.stats().frameCalls;
  worst = M.max(worst, ...fc); all.push(...fc);
  results.push(`autopilot ${i % 2 ? 'endless' : 'daily  '}: ${r.secs.toFixed(1)}s phase ${r.ph} score ${r.sc} near ${r.nm} -> state ${r.st}`);
}
const idle = playRun('d', null);
results.push(`no input       : died after ${idle.secs.toFixed(1)}s (score ${idle.sc})`);
console.log(results.join('\n'));
const avg = all.reduce((a, b) => a + b, 0) / all.length;
const sorted = [...all].sort((a, b) => a - b);
console.log(`canvas calls per drawn frame (visible canvas): avg ${avg.toFixed(1)}, p95 ${sorted[M.floor(sorted.length * .95)]}, max ${worst}`);

// frame rate: drawn frames per simulated second while playing / idle
{
  const env = makeEnv({}); env.tick(); env.resetStats();
  for (let i = 0; i < 600; i++) env.tick();
  const idleFps = env.stats().drawnFrames / 10;
  env.click(); env.resetStats();
  let f = 0; for (; f < 120 && env.get('st') === 1; f++) { env.tick(); autopilot(env, 180); }
  const playFps = env.stats().drawnFrames / (f / 60);
  console.log(`fps: idle ${idleFps.toFixed(1)}, playing ${playFps.toFixed(1)}; total canvas pixels ${env.stats().pixels} (limit ${2048 * 2048}); layout reads ${env.stats().layoutReads}`);
}

// daily determinism: two daily runs with no input share the same hazard sequence
{
  const sig = () => { const env = makeEnv({ mode: 'd' }); env.tick(); env.click(); for (let i = 0; i < 180; i++) env.tick(); return JSON.stringify(env.get('E.map(e=>[e.k,e.r,+e.a.toFixed(3)])')); };
  console.log('daily runs identical:', sig() === sig());
}

// requests: hello on load, submit at game over, retry on the next Play tap after a failure
{
  const env = makeEnv({ answers: [{ result: '{"t":[],"n":0,"r":0,"d":0,"b":0,"k":0}' }, { code: 'RATE_LIMITED' }] });
  await Promise.resolve(); env.tick();
  env.click();
  for (let i = 0; i < 60 * 300 && env.get('st') === 1; i++) env.tick();
  for (let i = 0; i < 90; i++) env.tick();
  await new Promise(r => setTimeout(r, 0));
  const status = env.els.y.textContent, pend = env.get('pend');
  env.click();
  await new Promise(r => setTimeout(r, 0));
  console.log('requests:', JSON.stringify(env.requests), '| status after failed submit:', status, '| pending kept:', !!pend, '| pending after retry:', JSON.stringify(env.get('pend')));
  console.log('board line:', JSON.stringify(env.els.l.textContent));
}

// places: no TelegramWidget, preview, forward
{
  const env = makeEnv({ tw: false }); env.tick();
  console.log('plain browser overlay:', env.els.o.innerHTML);
}
