/* OpenStall demo video: boot, preview player, and the frame-by-frame API used by tools/render.mjs. */
(async function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  const RENDER = params.has("render");
  E.mode.render = RENDER;
  if (RENDER) document.body.classList.add("render");
  const boot = document.getElementById("bootmsg");
  const say = (s) => (boot.textContent = s);

  try {
    if (location.protocol === "file:") {
      say("Open this page through the little server: run  node tools/serve.mjs  in the studio folder, then go to http://localhost:5178/studio/");
      return;
    }
    say("Loading the kit…");
    const get = (u) => fetch(u, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`${u}: ${r.status}`);
      return r.json();
    });
    const [timecodes, real, scripts] = await Promise.all([
      get("../narration-timecodes.json"),
      get("../whatsapp-real-chat.json"),
      get("../whatsapp-scripts.json"),
    ]);
    window.NARRATION = timecodes;
    const pick = (p) => scripts[Object.keys(scripts).find((k) => k.startsWith(p))];
    window.CHAT_SOURCES = { real, A2: pick("A2"), A3: pick("A3"), A4: pick("A4"), A5: pick("A5") };

    say("Loading fonts…");
    await Promise.all([
      document.fonts.load('400 20px "Geist"', "Aa"),
      document.fonts.load('500 20px "Geist"', "Aa"),
      document.fonts.load('600 20px "Geist"', "Aa"),
      document.fonts.load('400 20px "Geist Mono"', "Aa"),
      document.fonts.load('600 20px "Geist Mono"', "Aa"),
      document.fonts.load('400 20px "Noto Nastaliq Urdu"', "اب"),
      document.fonts.load('700 20px "Noto Nastaliq Urdu"', "اب"),
      document.fonts.load('400 20px "Noto Sans Devanagari"', "नम"),
      document.fonts.load('600 20px "Noto Sans Devanagari"', "नम"),
    ]);
    await document.fonts.ready;

    say("Building…");
    const stage = document.getElementById("stage");
    const scenesRoot = document.getElementById("scenes");
    window.buildScenes(scenesRoot);
    const caps = C.Captions(document.getElementById("captions"));
    E.after.push(caps.update);

    // wait for every picture on the page
    const imgs = [...stage.querySelectorAll("img")].filter((i) => i.getAttribute("src"));
    await Promise.all(imgs.map((i) => i.decode().catch(() => console.warn("image failed", i.src))));

    // layout pass: scenes measure themselves while shown
    for (const s of E.scenes) {
      s.el.style.display = "";
      if (s.el.__layout) s.el.__layout();
      s.el.style.display = "none";
      s._on = false;
    }
    boot.remove();

    const raf = () => new Promise((r) => requestAnimationFrame(() => r()));
    // Render API: show time t exactly (clip frames decoded), then resolve.
    window.__duration = window.VIDEO.duration;
    window.__seek = async (t) => {
      E.pendingDecodes.length = 0;
      E.renderAt(t, false);
      await Promise.all(E.pendingDecodes);
      await raf();
      return true;
    };
    // The sound effects follow the story: message pops and button taps, read by tools/make-audio.mjs.
    window.__sfx = () => {
      const out = [];
      for (const [key, def] of Object.entries(window.CHATS)) {
        for (const ev of def.events) {
          if (!ev.at) continue;
          const src = window.CHAT_SOURCES[def.source][ev.msg];
          out.push({ t: ev.at, kind: src.from === "OpenStall" ? "in" : "out", chat: key });
          if (ev.tap != null) out.push({ t: ev.tap, kind: "tap", chat: key });
          if (ev.flash != null) out.push({ t: ev.flash, kind: "shutter", chat: key });
        }
      }
      return out.sort((a, b) => a.t - b.t);
    };
    window.__ready = true;

    if (RENDER) {
      E.renderAt(Number(params.get("t") || 0), false);
      return;
    }

    // ---------- preview player ----------
    const audio = document.getElementById("narration");
    const range = document.getElementById("scrub");
    const timeEl = document.getElementById("time");
    const btn = document.getElementById("play");
    range.max = String(window.VIDEO.duration);
    let t = Number(params.get("t") || 0);
    let playing = false;
    let last = performance.now();
    const fit = () => {
      const s = Math.min(innerWidth / 1920, (innerHeight - 54) / 1080);
      stage.style.transform = `translate(${(innerWidth - 1920 * s) / 2}px, ${(innerHeight - 54 - 1080 * s) / 2}px) scale(${s})`;
    };
    addEventListener("resize", fit);
    fit();
    const fmtT = (x) => `${Math.floor(x / 60)}:${(x % 60).toFixed(2).padStart(5, "0")}`;
    function setPlaying(p) {
      playing = p;
      btn.textContent = p ? "Pause" : "Play";
      if (p) {
        if (t < audio.duration - 0.05) {
          audio.currentTime = t;
          audio.play().catch(() => {});
        }
        last = performance.now();
      } else audio.pause();
    }
    btn.onclick = () => setPlaying(!playing);
    range.oninput = () => {
      t = Number(range.value);
      if (playing && t < audio.duration) audio.currentTime = t;
    };
    addEventListener("keydown", (e) => {
      if (e.code === "Space") {
        e.preventDefault();
        setPlaying(!playing);
      } else if (e.code === "ArrowRight") t = Math.min(window.VIDEO.duration, t + (e.shiftKey ? 5 : 1 / 60));
      else if (e.code === "ArrowLeft") t = Math.max(0, t - (e.shiftKey ? 5 : 1 / 60));
      if (playing && (e.code === "ArrowRight" || e.code === "ArrowLeft")) audio.currentTime = t;
    });
    function frame(now) {
      if (playing) {
        if (!audio.paused && !audio.ended) t = audio.currentTime;
        else t += (now - last) / 1000;
        if (t >= window.VIDEO.duration) {
          t = window.VIDEO.duration;
          setPlaying(false);
        }
      }
      last = now;
      E.renderAt(t, playing);
      range.value = String(t);
      timeEl.textContent = `${fmtT(t)} / ${fmtT(window.VIDEO.duration)}`;
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  } catch (err) {
    console.error(err);
    say("Could not start: " + err.message);
    window.__error = String(err && err.stack ? err.stack : err);
  }
})();
