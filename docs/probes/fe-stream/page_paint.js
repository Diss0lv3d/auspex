// Layer 3 of the F1 stream probe: what the page paints, and when.
//
// Evaluate this in the chat page (Playwright `browser_evaluate`) AFTER sign-in
// and BEFORE a turn is sent; click Send; after the turn's done frame, evaluate
// `window.__paint.summary()`. It wraps the page's own `handleEvent` (a global
// function declaration in auspex/static/index.html, so the read loop calls the
// wrapper) and the stream reader, and stamps:
//   - each network chunk as the page's read loop receives it;
//   - each SSE frame as handleEvent starts on it, and how long it ran;
//   - the next animation frame after it (performance.now() inside rAF, i.e.
//     when the browser runs its rendering steps), which is when it can paint.
// Only kinds and lengths are kept, never the text. Safe to evaluate again
// before each turn: the page's originals are wrapped once, and each
// evaluation starts a fresh record (and a fresh chat session).
(() => {
  if (window.__paint) window.__paint.stop = true;
  const m = { t0: null, chunks: [], events: [], frames: [], longtasks: [], pending: [], stop: false };
  window.__paint = m;
  sessionId = null;  // the page's own global: each measured turn starts a new chat

  if (!window.__paintOrig) {
    window.__paintOrig = { read: ReadableStreamDefaultReader.prototype.read, handle: window.handleEvent };
    ReadableStreamDefaultReader.prototype.read = async function () {
      const r = await window.__paintOrig.read.call(this);
      if (r.value) window.__paint.chunks.push([performance.now(), r.value.length]);
      return r;
    };
    document.getElementById("send").addEventListener(
      "click", () => { window.__paint.t0 = performance.now(); }, { capture: true });
  }

  window.handleEvent = function (ev, wrap) {
    const a = performance.now();
    const out = window.__paintOrig.handle(ev, wrap);
    const kind = Object.keys(ev)[0];
    const n = typeof ev[kind] === "string" ? ev[kind].length : 0;
    m.events.push([a, performance.now() - a, kind, n]);
    m.pending.push(m.events.length - 1);
    return out;
  };

  const tick = () => {
    if (m.pending.length) { m.frames.push([performance.now(), m.pending.slice()]); m.pending.length = 0; }
    if (!m.stop) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) m.longtasks.push([e.startTime, e.duration]);
    }).observe({ type: "longtask" });
  } catch (e) { /* not supported: longtasks stay empty */ }

  const pct = (xs, p) => {
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b);
    return +s[Math.min(s.length - 1, Math.round((p / 100) * (s.length - 1)))].toFixed(2);
  };
  const gaps = (xs) => xs.slice(1).map((x, i) => x - xs[i]);

  m.summary = () => {
    m.stop = true;
    const ev = m.events;
    const r = ev.filter((e) => e[2] === "reasoning");
    const c = ev.filter((e) => e[2] === "content");
    const lag = [];
    for (const [t, idxs] of m.frames) for (const i of idxs) lag.push(t - ev[i][0]);
    const rChars = r.reduce((s, e) => s + e[3], 0);
    const rSpan = r.length > 1 ? (r[r.length - 1][0] - r[0][0]) / 1000 : 0;
    const cHandle = c.map((e) => e[1]);
    return {
      events: ev.length, chunks: m.chunks.length, painted_frames: m.frames.length,
      first_reasoning_ms: r.length && m.t0 !== null ? +(r[0][0] - m.t0).toFixed(1) : null,
      first_answer_ms: c.length && m.t0 !== null ? +(c[0][0] - m.t0).toFixed(1) : null,
      turn_ms: ev.length && m.t0 !== null ? +(ev[ev.length - 1][0] - m.t0).toFixed(1) : null,
      reasoning_frames: r.length, reasoning_chars: rChars,
      reasoning_rate_cps: rSpan ? +(rChars / rSpan).toFixed(1) : null,
      max_reasoning_gap_ms: pct(gaps(r.map((e) => e[0])), 100),
      answer_frames: c.length, answer_chars: c.reduce((s, e) => s + e[3], 0),
      handle_ms_p50: pct(ev.map((e) => e[1]), 50), handle_ms_p95: pct(ev.map((e) => e[1]), 95),
      handle_ms_max: pct(ev.map((e) => e[1]), 100),
      answer_handle_ms_p95: pct(cHandle, 95), answer_handle_ms_max: pct(cHandle, 100),
      paint_lag_ms_p50: pct(lag, 50), paint_lag_ms_p95: pct(lag, 95), paint_lag_ms_max: pct(lag, 100),
      longtasks: m.longtasks.length, longtask_ms_max: pct(m.longtasks.map((l) => l[1]), 100),
    };
  };
  return "instrumented";
})();
