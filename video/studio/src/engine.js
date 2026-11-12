/* OpenStall demo video: timeline engine.
 * Every frame is a pure function of time t (seconds on the narration track): render(t) sets the DOM, nothing else
 * animates on its own. That is what lets tools/render.mjs step through the video frame by frame at 60 fps, and lets
 * the preview play in sync with narration-draft.mp3. */
(function () {
  "use strict";

  const W = 1920;
  const H = 1080;
  const FPS = 60;

  // ---------- maths ----------
  const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  const lerp = (a, b, p) => a + (b - a) * p;
  const ease = {
    linear: (p) => p,
    inCubic: (p) => p * p * p,
    outCubic: (p) => 1 - Math.pow(1 - p, 3),
    outQuart: (p) => 1 - Math.pow(1 - p, 4),
    outQuint: (p) => 1 - Math.pow(1 - p, 5),
    outExpo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
    inOutSine: (p) => -(Math.cos(Math.PI * p) - 1) / 2,
    inOutCubic: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    inOutQuart: (p) => (p < 0.5 ? 8 * p * p * p * p : 1 - Math.pow(-2 * p + 2, 4) / 2),
    inOutQuint: (p) => (p < 0.5 ? 16 * p * p * p * p * p : 1 - Math.pow(-2 * p + 2, 5) / 2),
    inOutExpo: (p) =>
      p <= 0 ? 0 : p >= 1 ? 1 : p < 0.5 ? Math.pow(2, 20 * p - 10) / 2 : (2 - Math.pow(2, -20 * p + 10)) / 2,
  };
  // Eased progress of t through [t0, t0 + d].
  const prog = (t, t0, d, e = ease.inOutCubic) => (d <= 0 ? (t >= t0 ? 1 : 0) : e(clamp((t - t0) / d)));
  // In-out envelope: 0 before a, up to 1 over fi seconds, down to 0 over fo seconds ending at b.
  const env = (t, a, b, fi = 0.45, fo = 0.45, e = ease.inOutSine) =>
    Math.min(prog(t, a, fi, e), 1 - prog(t, b - fo, fo, e));

  // Keyframe track: [[time, value, easeName], ...]; value is a number or an array of numbers.
  // The ease on a key shapes the segment that ENDS at that key.
  function track(t, keys) {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const k = keys[i];
      if (t <= k[0]) {
        const a = keys[i - 1];
        const e = ease[k[2] || "inOutCubic"];
        const p = e(clamp((t - a[0]) / (k[0] - a[0])));
        if (Array.isArray(a[1])) return a[1].map((v, j) => lerp(v, k[1][j], p));
        return lerp(a[1], k[1], p);
      }
    }
    return keys[keys.length - 1][1];
  }

  // Slope of a piecewise-linear map at t (0 outside or on a hold): the preview plays clips at this rate.
  function pwlSlope(t, pts) {
    for (let i = 1; i < pts.length; i++) {
      if (t >= pts[i - 1][0] && t < pts[i][0]) return (pts[i][1] - pts[i - 1][1]) / (pts[i][0] - pts[i - 1][0]);
    }
    return 0;
  }

  // Piecewise-linear map (for clip time maps): [[t, v], ...], held flat outside.
  function pwl(t, pts) {
    if (t <= pts[0][0]) return pts[0][1];
    for (let i = 1; i < pts.length; i++) {
      if (t <= pts[i][0]) {
        const a = pts[i - 1];
        const b = pts[i];
        return lerp(a[1], b[1], (t - a[0]) / (b[0] - a[0]));
      }
    }
    return pts[pts.length - 1][1];
  }

  // ---------- DOM ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        const v = attrs[k];
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
        else if (k === "html") el.innerHTML = v;
        else if (k === "text") el.textContent = v;
        else el.setAttribute(k, v);
      }
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
    }
    return el;
  }

  // Style writer that skips unchanged values (keeps per-frame work small).
  const r2 = (v) => Math.round(v * 100) / 100;
  const r3 = (v) => Math.round(v * 1000) / 1000;
  function S(el, props) {
    const c = el.__s || (el.__s = {});
    for (const k in props) {
      let v = props[k];
      if (typeof v === "number") v = k === "opacity" ? String(r3(v)) : r2(v) + "px";
      if (c[k] !== v) {
        el.style[k] = v;
        c[k] = v;
      }
    }
  }
  // Common: fade + translate + scale.
  function show(el, o, x = 0, y = 0, s = 1, extra) {
    const vis = o > 0.001;
    const props = {
      opacity: vis ? o : 0,
      visibility: vis ? "visible" : "hidden",
      transform: `translate(${r2(x)}px, ${r2(y)}px)` + (s !== 1 ? ` scale(${r3(s)})` : ""),
    };
    if (extra) Object.assign(props, extra);
    S(el, props);
  }
  function setText(el, txt) {
    if (el.__txt !== txt) {
      el.textContent = txt;
      el.__txt = txt;
    }
  }
  const money = (v) => "$" + v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  // ---------- timeline ----------
  const scenes = [];
  const after = []; // per-frame hooks that run after the scenes (captions)
  function scene(def) {
    scenes.push(def);
    return def;
  }
  let lastT = -1;
  function renderAt(t, playing = false) {
    for (const s of scenes) {
      const on = t >= s.t0 && t < s.t1;
      if (on !== s._on) {
        s.el.style.display = on ? "" : "none";
        s._on = on;
      }
      if (on) s.update(t, playing);
    }
    for (const f of after) f(t);
    lastT = t;
  }

  // ---------- clips (screen recordings) ----------
  // In preview mode a clip plays as a <video>; in render mode each frame is a JPEG pulled from cache/frames/<clip>/
  // (tools/extract-frames.mjs makes them), so every output frame shows exactly the source frame it should.
  const mode = { render: false, framesBase: "cache/frames/" };
  const pendingDecodes = [];
  function clipFrameUrl(clip, idx) {
    return `${mode.framesBase}${clip}/${String(idx).padStart(5, "0")}.jpg`;
  }
  // A clip layer: <img> in render mode, <video> in preview mode.
  function clipLayer(clip) {
    const meta = window.CLIPS[clip];
    const wrap = h("div", { class: "clip-layer" });
    const img = h("img", { class: "clip-img", alt: "", draggable: "false" });
    const video = h("video", { class: "clip-video", muted: "", playsinline: "", preload: "auto" });
    video.muted = true;
    wrap.append(img, video);
    let shownIdx = -1;
    let active = false;
    function setTime(src, playing, rate = 1) {
      const idx = clamp(Math.round(src * FPS), 0, meta.frames - 1);
      if (mode.render) {
        if (idx !== shownIdx) {
          shownIdx = idx;
          const url = clipFrameUrl(clip, idx);
          img.src = url;
          pendingDecodes.push(
            img.decode().catch(() => {
              throw new Error(`clip frame missing: ${url} (run node tools/extract-frames.mjs)`);
            }),
          );
        }
        return;
      }
      // preview: drive the <video> element
      if (!video.src) video.src = `../recordings/${meta.file}`;
      const want = idx / FPS + 0.5 / FPS;
      if (playing && rate > 0.05) {
        if (Math.abs(video.playbackRate - rate) > 0.01) video.playbackRate = rate;
        if (video.paused) video.play().catch(() => {});
        if (Math.abs(video.currentTime - want) > 0.15) video.currentTime = want;
      } else {
        if (!video.paused) video.pause();
        if (Math.abs(video.currentTime - want) > 0.5 / FPS) video.currentTime = want;
      }
    }
    function setActive(on) {
      if (on === active) return;
      active = on;
      if (!on && !mode.render && !video.paused) video.pause();
    }
    return { el: wrap, setTime, setActive, img, video };
  }

  // ---------- clock ----------
  const clock = {
    t: 0,
    playing: false,
  };

  window.E = {
    W, H, FPS, clamp, lerp, ease, prog, env, track, pwl, pwlSlope, h, S, show, setText, money,
    scenes, after, scene, renderAt, mode, pendingDecodes, clipLayer, clock,
    get lastT() { return lastT; },
  };
})();
