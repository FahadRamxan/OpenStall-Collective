/* OpenStall demo video: building blocks (icons, phone + chat, browser frame, PayPal hold card, captions). */
(function () {
  "use strict";
  const { h, S, show, clamp, lerp, ease, prog, env, track, pwl, setText } = E;

  // ---------- icons ----------
  const ICON = {
    lock: '<svg viewBox="0 0 16 16"><path d="M4.5 7V5.5a3.5 3.5 0 0 1 7 0V7" fill="none" stroke="#8a817a" stroke-width="1.6"/><rect x="3" y="7" width="10" height="7.5" rx="2" fill="#8a817a"/></svg>',
    back: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    mic: '<svg viewBox="0 0 24 24" width="20" height="20"><rect x="9" y="3" width="6" height="11" rx="3" fill="#fff"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>',
    ticks: '<svg class="ticks" viewBox="0 0 18 12"><path d="M1 6.5l3 3L10.5 2.5M7.5 9.5l1 0.9L15.5 2.5" fill="none" stroke="#53bdeb" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    check: (c = "#0e6e64", s = 18) =>
      `<svg viewBox="0 0 20 20" width="${s}" height="${s}"><path d="M4.5 10.5l3.5 3.5 7.5-8" fill="none" stroke="${c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    spark: (c = "#0e6e64", s = 22) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><path d="M12 2.5l1.9 5.6 5.6 1.9-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.9z" fill="${c}"/><path d="M19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z" fill="${c}"/></svg>`,
    chat: (c = "#fff", s = 34) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" fill="none" stroke="${c}" stroke-width="1.8" stroke-linejoin="round"/></svg>`,
    code: (c = "#fff", s = 34) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><path d="M8.5 6L3 12l5.5 6M15.5 6L21 12l-5.5 6" fill="none" stroke="${c}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    hold: (c = "#fff", s = 34) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><rect x="4" y="10.5" width="16" height="10" rx="2.5" fill="none" stroke="${c}" stroke-width="1.9"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="${c}" stroke-width="1.9"/><circle cx="12" cy="15.5" r="1.6" fill="${c}"/></svg>`,
    calendar: (c = "#0e6e64", s = 30) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><rect x="3.5" y="5" width="17" height="15.5" rx="3" fill="none" stroke="${c}" stroke-width="1.8"/><path d="M3.5 10h17M8 3v4M16 3v4" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round"/></svg>`,
    agent: (c = "#fff", s = 30) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><rect x="4" y="7" width="16" height="12" rx="4" fill="none" stroke="${c}" stroke-width="1.8"/><circle cx="9.5" cy="13" r="1.5" fill="${c}"/><circle cx="14.5" cy="13" r="1.5" fill="${c}"/><path d="M12 3.5V7" stroke="${c}" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="3" r="1.3" fill="${c}"/></svg>`,
    scan: (c = "#fff", s = 40) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round"/><path d="M7.5 8v8M10 8v8M12.5 8v8M15.5 8v8M17 8v8" stroke="${c}" stroke-width="1.3"/></svg>`,
    box: (c = "#fff", s = 40) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z" fill="none" stroke="${c}" stroke-width="1.7" stroke-linejoin="round"/><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9" fill="none" stroke="${c}" stroke-width="1.7" stroke-linejoin="round"/></svg>`,
    person: (c = "#fff", s = 40) =>
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}"><circle cx="12" cy="8.5" r="3.6" fill="none" stroke="${c}" stroke-width="1.8"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  };
  const svg = (s) => {
    const d = document.createElement("div");
    d.innerHTML = s.trim();
    return d.firstChild;
  };

  // ---------- text helpers ----------
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const langOf = (s) => (/[؀-ۿ]/.test(s) ? "ur" : /[ऀ-ॿ]/.test(s) ? "hi" : "en");
  // WhatsApp text -> HTML: *bold*, line breaks; marks wrap given words (first match) so they can be highlighted.
  function fmt(text, marks) {
    let s = esc(text);
    s = s.replace(/\*([^*\n]+)\*/g, "<b>$1</b>");
    // links stay one left-to-right unit inside Urdu text, and don't break
    s = s.replace(/openstall-collective\.onrender\.com\/stall\/…/g, '<bdi dir="ltr" class="link-ltr">$&</bdi>');
    for (const m of marks || []) {
      const needle = esc(m.text);
      const i = s.indexOf(needle);
      if (i < 0) throw new Error(`highlight not found: ${m.text}`);
      s = s.slice(0, i) + `<mark class="hlm" data-k="${m.key}">${needle}</mark>` + s.slice(i + needle.length);
    }
    return s.replace(/\n/g, "<br>");
  }

  const PHOTO = {
    real: "../assets/real-chat-photo-1.jpg",
    A2: "../assets/receipt-amina.jpg",
    A3: "../assets/receipt-priya.jpg",
  };

  // ---------- phone + chat ----------
  // A phone that plays one chat from CHATS (data.js). update(t) shows exactly what is on screen at time t.
  function Phone(key) {
    const def = window.CHATS[key];
    const src = window.CHAT_SOURCES[def.source];
    const el = h("div", { class: "phone" });
    const screen = h("div", { class: "screen" });
    const status = h("div", { class: "status" }, h("span", { class: "clock" }, def.time || "18:07"));
    status.appendChild(
      h(
        "span",
        { class: "icons" },
        h("i", { style: { width: "3px", height: "6px" } }),
        h("i", { style: { width: "3px", height: "8px" } }),
        h("i", { style: { width: "3px", height: "10px" } }),
        h("i", { style: { width: "22px", height: "11px", borderRadius: "3px", marginLeft: "5px" } }),
      ),
    );
    const clockEl = status.querySelector(".clock");
    const sub = h("span", { class: "sub" }, "online");
    const head = h(
      "div",
      { class: "head" },
      h("span", { class: "back", html: ICON.back }),
      h("span", { class: "avatar" }, h("img", { src: "../assets/app-icon-1024.png", alt: "" })),
      h("span", { class: "who" }, h("span", { class: "name" }, "OpenStall"), sub),
    );
    const chat = h("div", { class: "chat" });
    const content = h("div", { class: "chat-content" });
    chat.appendChild(content);
    const dateEl = def.date ? h("div", { class: "date-chip" }, def.date) : null;
    if (dateEl) content.appendChild(dateEl);
    const input = h(
      "div",
      { class: "input" },
      h("div", { class: "field" }, "Message"),
      h("div", { class: "mic", html: ICON.mic }),
    );
    const flash = h("div", { class: "flash" });
    const touch = h("div", { class: "touch" });
    screen.append(status, head, chat, input, touch, flash);
    el.appendChild(screen);

    const replace = (s) => {
      for (const [a, b] of def.replace || []) s = s.split(a).join(b);
      return s;
    };

    // Build each message the chat shows.
    const items = [];
    let prevOS = null;
    def.events.forEach((ev, idx) => {
      const m = src[ev.msg];
      if (!m) throw new Error(`${key}: no message ${ev.msg}`);
      const isOS = m.from === "OpenStall";
      const marks = (def.hl || [])
        .map((x, i) => ({ ...x, key: `${key}-${i}` }))
        .filter((x) => x.msg === ev.msg);
      const stamp = ev.stamp || (m.time ? m.time.slice(0, 5) : def.time);
      const wrap = h("div", { class: "msg " + (isOS ? "in" : "out") });
      let lang = "en";
      let btnEls = [];
      if (!isOS && m.media && m.media.length && !m.text) {
        const bub = h("div", { class: "bubble photo-bubble" });
        bub.appendChild(h("img", { src: PHOTO[def.source], alt: "" }));
        if (def.source !== "real") bub.appendChild(h("span", { class: "demo-tag" }, "Demo slip"));
        bub.appendChild(h("div", { class: "scan" }));
        bub.appendChild(h("div", { class: "meta", html: `${stamp} ${ICON.ticks}` }));
        wrap.appendChild(bub);
      } else {
        let text = m.text;
        // A tap on a quick-reply button sends the button's title back as her message, as WhatsApp does.
        if (ev.tap != null && prevOS && prevOS.buttons && prevOS.buttons.length) text = prevOS.buttons[ev.tapButton || 0];
        text = replace(text);
        lang = langOf(text);
        const bub = h("div", { class: `bubble lang-${lang}` });
        bub.appendChild(h("div", { class: "txt", html: fmt(text, marks.map((x) => ({ text: x.text, key: x.key }))) }));
        bub.appendChild(h("div", { class: "meta", html: isOS ? stamp : `${stamp} ${ICON.ticks}` }));
        wrap.appendChild(bub);
        if (isOS && m.buttons && m.buttons.length) {
          const bw = h("div", { class: "buttons" });
          for (const b of m.buttons) {
            const be = h("div", { class: `btn lang-${langOf(b)}` }, h("span", { text: b }), h("span", { class: "ripple" }));
            bw.appendChild(be);
            btnEls.push(be);
          }
          wrap.appendChild(bw);
        }
        if (isOS && m.english) {
          const en = replace(m.english);
          const enMarks = marks.filter((x) => x.en).map((x) => ({ text: x.en, key: x.key + "-en" }));
          wrap.appendChild(
            h("div", { class: "en", html: `<span class="en-tag">IN ENGLISH</span>` + fmt(en, enMarks) }),
          );
        }
      }
      content.appendChild(wrap);
      let typingEl = null;
      if (isOS && ev.typing) {
        typingEl = h("div", { class: "typing-bubble" }, h("i"), h("i"), h("i"));
        content.appendChild(typingEl);
      }
      items.push({ ev, m, isOS, wrap, typingEl, btnEls, stamp, idx, marks });
      if (isOS) prevOS = m;
    });
    // tap events point at the previous OpenStall message's buttons
    items.forEach((it, i) => {
      if (it.ev.tap != null) {
        for (let j = i - 1; j >= 0; j--) {
          if (items[j].btnEls.length) {
            it.tapBtn = items[j].btnEls[it.ev.tapButton || 0];
            it.tapOwner = items[j];
            break;
          }
        }
      }
    });
    const markEls = {};
    el.querySelectorAll("mark.hlm").forEach((mk) => (markEls[mk.dataset.k] = mk));

    const VIEW_H = 840 - 22 - 100 - 62; // chat viewport height inside the screen
    let layout = null;
    function measure() {
      // lay messages out top to bottom; positions are in chat-content pixels
      let y = dateEl ? 12 + dateEl.offsetHeight + 12 : 14;
      let prevFrom = null;
      for (const it of items) {
        const gap = prevFrom === null ? 0 : prevFrom === it.isOS ? 6 : 12;
        y += gap;
        it.top = y;
        it.wrap.style.top = y + "px";
        it.h = it.wrap.offsetHeight;
        if (it.typingEl) it.typingEl.style.top = y + "px";
        y += it.h;
        prevFrom = it.isOS;
        if (it.tapBtn) {
          // button centre relative to its message
          const b = it.tapBtn;
          it.tapX = b.offsetLeft + b.parentElement.offsetLeft + b.offsetWidth / 2 + 10;
          it.tapYIn = b.offsetTop + b.parentElement.offsetTop + b.offsetHeight / 2;
        }
      }
      // scroll keyframes: every message (and typing dots) brings the chat to show its bottom, or its top if taller
      // than the screen
      const evs = [];
      const pad = 12;
      for (const it of items) {
        const appear = it.ev.at;
        if (it.typingEl) {
          const ttop = it.top;
          evs.push({ t: appear - it.ev.typing, target: Math.max(0, ttop + 38 + pad - VIEW_H) });
        }
        evs.push({ t: appear, target: Math.max(0, Math.min(it.top - 16, it.top + it.h + pad - VIEW_H)) });
      }
      evs.sort((a, b) => a.t - b.t);
      const segs = [];
      let v = 0;
      for (const e of evs) {
        if (segs.length) v = segVal(segs[segs.length - 1], e.t);
        else v = e.target; // start already there
        segs.push({ t: e.t, from: v, to: e.target, d: 0.5 });
      }
      layout = { segs };
    }
    function segVal(sg, t) {
      return lerp(sg.from, sg.to, ease.inOutCubic(clamp((t - sg.t) / sg.d)));
    }
    function scrollAt(t) {
      const segs = layout.segs;
      let sg = segs[0];
      for (const s of segs) if (s.t <= t) sg = s;
      return segVal(sg, Math.max(t, sg.t));
    }

    function update(t) {
      if (!layout) measure();
      const sc = scrollAt(t);
      S(content, { transform: `translateY(${-Math.round(sc * 100) / 100}px)` });
      let typing = false;
      let clock = def.time;
      for (const it of items) {
        const a = it.ev.at;
        // message pop
        const p = prog(t, a, 0.3, ease.outQuart);
        const vis = t >= a;
        show(it.wrap, vis ? p : 0, 0, (1 - p) * 10, vis ? lerp(0.94, 1, p) : 0.94);
        if (vis) clock = it.stamp;
        if (it.typingEl) {
          const ts = a - it.ev.typing;
          const on = t >= ts && t < a;
          if (on) typing = true;
          const tp = prog(t, ts, 0.18, ease.outQuart);
          show(it.typingEl, on ? tp : 0, 0, (1 - tp) * 6, on ? lerp(0.9, 1, tp) : 0.9);
          if (on) {
            const dots = it.typingEl.children;
            for (let i = 0; i < 3; i++) {
              const ph = (t - ts) * 2 * Math.PI * 1.7 - i * 0.75;
              const lift = Math.max(0, Math.sin(ph));
              S(dots[i], { transform: `translateY(${(-3.2 * lift).toFixed(2)}px)`, opacity: 0.45 + 0.5 * lift });
            }
          }
        }
        // camera flash before a photo
        // (handled below with the phone-wide flash element)
      }
      // highlights
      for (const it of items) {
        for (const mk of it.marks) {
          const p = prog(t, mk.at, 0.35, ease.outCubic);
          const col = mk.tone === "warn" ? `rgba(237, 161, 0, ${0.3 * p})` : `rgba(14, 110, 100, ${0.2 * p})`;
          const line = mk.tone === "warn" ? `rgba(196, 128, 0, ${0.9 * p})` : `rgba(14, 110, 100, ${0.9 * p})`;
          for (const k of [mk.key, mk.key + "-en"]) {
            const e = markEls[k];
            if (e) S(e, { backgroundColor: col, boxShadow: `inset 0 -2px 0 ${line}` });
          }
        }
      }
      // flash
      let fl = 0;
      for (const it of items) {
        const f = it.ev.flash;
        if (f != null) fl = Math.max(fl, Math.min(prog(t, f, 0.06, ease.linear), 1 - prog(t, f + 0.06, 0.4, ease.outCubic)) * 0.9);
      }
      S(flash, { opacity: fl });
      // photo scan (Claude reading the photo)
      if (def.scan) {
        const it = items.find((x) => x.ev.msg === def.scan.msg);
        const sc = it.wrap.querySelector(".scan");
        const imgH = it.wrap.querySelector("img").offsetHeight || 230;
        const pr = clamp((t - def.scan.t0) / (def.scan.t1 - def.scan.t0));
        const o = t >= def.scan.t0 && t <= def.scan.t1 + 0.25 ? Math.min(1, pr * 6, (def.scan.t1 + 0.25 - t) * 4) : 0;
        S(sc, { top: 4 + (imgH - 46) * ease.inOutSine(pr), opacity: o });
      }
      // taps: touch dot + ripple on the button
      let touchO = 0;
      for (const it of items) {
        if (it.ev.tap == null || !it.tapBtn) continue;
        const tt = it.ev.tap;
        const owner = it.tapOwner;
        const ripple = it.tapBtn.querySelector(".ripple");
        const rp = clamp((t - tt) / 0.55);
        const ro = t >= tt && t <= tt + 0.55 ? (1 - ease.outCubic(rp)) * 0.95 : 0;
        S(ripple, {
          left: it.tapBtn.offsetWidth / 2,
          top: it.tapBtn.offsetHeight / 2,
          transform: `scale(${(0.3 + ease.outCubic(rp) * 4.2).toFixed(3)})`,
          opacity: ro,
        });
        const pressed = t >= tt && t < tt + 0.32;
        S(it.tapBtn, { backgroundColor: pressed ? "#e9f3f8" : "#ffffff" });
        // finger dot, in screen pixels
        const o1 = Math.min(prog(t, tt - 0.22, 0.18, ease.outCubic), 1 - prog(t, tt + 0.12, 0.3, ease.outCubic));
        if (o1 > 0.001) {
          touchO = o1;
          const x = owner.tapX;
          const y = 100 + owner.top + owner.tapYIn - sc;
          S(touch, { left: x, top: y, transform: `scale(${(1 - 0.12 * prog(t, tt - 0.05, 0.12)).toFixed(3)})` });
        }
      }
      S(touch, { opacity: touchO });
      // header + status bar
      const subTxt = typing ? "typing…" : "online";
      setText(sub, subTxt);
      sub.className = typing ? "sub typing" : "sub";
      setText(clockEl, clock);
    }

    // Where a message's bubble is on the phone screen at time t (phone-local pixels, before the phone's transform).
    function bubbleBox(msgIdx, t) {
      const it = items.find((x) => x.ev.msg === msgIdx);
      const b = it.wrap.firstChild;
      const sc = scrollAt(t);
      const x = 11 + 10 + b.offsetLeft;
      const y = 11 + 100 + it.top + b.offsetTop - sc;
      return { x, y, w: b.offsetWidth, h: b.offsetHeight };
    }
    return { el, update, measure, bubbleBox, items };
  }

  // ---------- browser frame with screen-recording shots ----------
  // vw x vh is the page area (16:9). Shots are the SHOTS entries assigned to this frame.
  function Browser(opts) {
    const { vw, vh } = opts;
    const el = h("div", { class: "browser", style: { width: vw + "px", height: vh + 46 + "px" } });
    const urlText = h("span", { class: "url-text" }, "localhost:3000");
    const badgeText = h("span", {}, "Test mode · PayPal simulated");
    const badge = h("div", { class: "badge" }, h("span", { class: "dot" }), badgeText);
    const bar = h(
      "div",
      { class: "bar" },
      h("div", { class: "lights" }, h("i"), h("i"), h("i")),
      h("div", { class: "url", html: ICON.lock }, urlText),
      badge,
    );
    bar.querySelector(".url").appendChild(urlText);
    const viewport = h("div", { class: "viewport" });
    const hlLayer = h("div", { class: "abs", style: { inset: "0" } });
    el.append(bar, viewport);
    const shots = [];
    for (const id of opts.shots) {
      const d = window.SHOTS[id];
      const layer = E.clipLayer(d.clip);
      viewport.appendChild(layer.el);
      const hls = (d.hl || []).map((x) => {
        const b = h("div", { class: "hl-box" + (x.tone && x.tone !== "teal" ? " " + x.tone : "") });
        if (x.label) b.appendChild(h("div", { class: "hl-label" }, x.label));
        hlLayer.appendChild(b);
        return b;
      });
      shots.push({ id, d, layer, hls });
    }
    viewport.appendChild(hlLayer);
    const site = opts.site || (() => ({ url: "localhost:3000", badge: "Test mode · PayPal simulated", sandbox: false }));

    function camAt(d, t) {
      const c = track(t, d.cam);
      let [cx, cy, z] = c;
      z = Math.max(1, z);
      const s = (vw / 1920) * z;
      const hw = vw / (2 * s);
      const hh = vh / (2 * s);
      cx = clamp(cx, hw, 1920 - hw);
      cy = clamp(cy, hh, 1080 - hh);
      return { cx, cy, s };
    }

    function update(t, playing) {
      let top = null;
      let topA = 0;
      for (const sh of shots) {
        const d = sh.d;
        const fi = d.fadeIn || 0;
        const fo = d.fadeOut || 0;
        const on = t >= d.t0 && t < d.t1;
        let a = 0;
        // cuts dip briefly through the page colour instead of double-exposing two pages: the outgoing shot is gone
        // before the incoming one is up
        if (on) a = Math.min(fi > 0 ? prog(t, d.t0 + fi * 0.4, fi * 0.6, ease.inOutSine) : 1, fo > 0 ? 1 - prog(t, d.t1 - fo, fo * 0.6, ease.inOutSine) : 1);
        sh.layer.setActive(on);
        if (!on) {
          S(sh.layer.el, { opacity: 0, visibility: "hidden" });
          for (const b of sh.hls) S(b, { opacity: 0, visibility: "hidden" });
          continue;
        }
        sh.layer.setTime(pwl(t, d.map), playing, E.pwlSlope(t, d.map));
        const { cx, cy, s } = camAt(d, t);
        const tx = vw / 2 - cx * s;
        const ty = vh / 2 - cy * s;
        S(sh.layer.el, {
          opacity: a,
          visibility: "visible",
          transform: `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px) scale(${s.toFixed(5)})`,
        });
        (d.hl || []).forEach((x, i) => {
          const b = sh.hls[i];
          const ho = env(t, x.t, x.until, 0.3, 0.3) * a;
          if (ho <= 0.001) return S(b, { opacity: 0, visibility: "hidden" });
          const [x0, y0, x1, y1] = x.box;
          const pad = 6;
          const p = prog(t, x.t, 0.4, ease.outCubic);
          S(b, {
            left: tx + x0 * s - pad,
            top: ty + y0 * s - pad,
            width: (x1 - x0) * s + pad * 2,
            height: (y1 - y0) * s + pad * 2,
            opacity: ho,
            visibility: "visible",
            transform: `scale(${(1.03 - 0.03 * p).toFixed(4)})`,
          });
        });
        if (a >= topA) {
          topA = a;
          top = sh;
        }
      }
      if (top) {
        const info = site(top.id);
        setText(urlText, info.url);
        setText(badgeText, info.badge);
        badge.className = info.sandbox ? "badge sandbox" : "badge";
      }
    }
    // Screen position (frame-local) of a point in a shot's clip pixels.
    function toFrame(id, t, x, y) {
      const sh = shots.find((s) => s.id === id);
      const { cx, cy, s } = camAt(sh.d, t);
      return { x: vw / 2 + (x - cx) * s, y: 46 + vh / 2 + (y - cy) * s };
    }
    return { el, update, viewport, toFrame };
  }

  // ---------- PayPal hold card ----------
  // mode "split": the plan building up (step two). mode "hold": one authorization, shares captured, paid, released.
  const ORDER = ["amina", "priya", "lucia", "grace"];
  function HoldCard(mode, width = 700) {
    const M = window.MAKERS;
    const el = h("div", { class: "card hold", style: { width: width + "px" } });
    const eyebrow = h("div", { class: "eyebrow" }, mode === "split" ? "Split by plain code" : "One PayPal authorization · intent AUTHORIZE");
    const title = h("div", { class: "h-title" }, mode === "split" ? "All 40 from 4 makers" : "PayPal is holding $815.00");
    const bar = h("div", { class: "bar" });
    const rows = h("div", { class: "rows" });
    const total = 815;
    let x = 0;
    const segs = {};
    const rowEls = {};
    const GAP = 4;
    const BARW = width - 60;
    for (const k of ORDER) {
      const m = M[k];
      const w = (m.total / total) * BARW;
      const seg = h("div", { class: "seg", style: { left: x + "px", width: w - GAP + "px" } });
      const inner = h("div", { class: "seg-in", style: { background: m.color } });
      const ghost = h("div", { class: "seg-ghost" });
      const chk = h("div", { class: "seg-check", html: ICON.check(m.color, 20) });
      seg.append(inner, ghost, chk);
      bar.appendChild(seg);
      segs[k] = { seg, inner, ghost, chk, x, w };
      x += w;
      const st = h("div", { class: "st" });
      const states = {};
      const mk = (cls, html) => {
        const s = h("span", { class: cls, html });
        st.appendChild(s);
        return s;
      };
      states.held = mk("held", "Held");
      states.captured = mk("captured", "Captured");
      states.paid = mk("paid", `${ICON.check("#0a574f", 16)} Paid out`);
      states.sim = mk("sim", "Paid · Hyperwallet (simulated)");
      states.released = mk("released", "Released · never charged");
      const row = h(
        "div",
        { class: "hrow" },
        h("span", { class: "sw", style: { background: m.color } }),
        h("span", { class: "nm" }, m.name),
        h("span", { class: "calc" }, `${m.qty} × $${m.unit} = $${m.total}`),
        st,
      );
      rows.appendChild(row);
      rowEls[k] = { row, states };
    }
    // the top-up from Priya takes Grace's place
    const g = segs.grace;
    const tuW = (112 / total) * BARW;
    const tuSeg = h("div", { class: "seg", style: { left: g.x + "px", width: tuW - GAP + "px" } });
    const tuIn = h("div", { class: "seg-in", style: { background: M.priya.color } });
    tuSeg.appendChild(tuIn);
    bar.appendChild(tuSeg);
    const tuRow = h(
      "div",
      { class: "hrow" },
      h("span", { class: "sw", style: { background: M.priya.color } }),
      h("span", { class: "nm" }, "Priya"),
      h("span", { class: "calc" }, "7 × $16.00 = $112.00"),
      h("div", { class: "st" }, h("span", { class: "topup" }, "Top-up")),
    );
    rows.appendChild(tuRow);
    const totalV = h("span", { class: "v" }, "$815.00");
    const totalRow = h("div", { class: "total" }, h("span", { class: "k" }, mode === "split" ? "Total" : "Authorized once"), totalV);
    const foot =
      mode === "hold"
        ? h("div", { style: { marginTop: "12px", fontSize: "15px", color: "var(--muted)" } }, "This demo runs in test mode: PayPal is simulated and no real money moves.")
        : null;
    el.append(eyebrow, title, bar, rows, totalRow);
    if (foot) el.appendChild(foot);

    // state(t) for the hold card, from the story's times
    function holdState(t) {
      const st = { amina: "held", priya: "held", lucia: "held", grace: "held" };
      if (t >= 111.0) st.priya = "captured";
      if (t >= 113.45) st.priya = "paid";
      if (t >= 120.85) st.amina = "captured";
      if (t >= 121.6) st.amina = "sim";
      if (t >= 129.2) st.grace = "released";
      return st;
    }

    function update(t) {
      if (mode === "split") {
        const T = { amina: 77.3, priya: 78.62, lucia: 80.02, grace: 81.4 };
        let sum = 0;
        for (const k of ORDER) {
          const p = prog(t, T[k], 0.7, ease.inOutCubic);
          const s = segs[k];
          S(s.seg, { transform: `scaleX(${p.toFixed(4)})`, opacity: p > 0 ? 1 : 0 });
          S(s.ghost, { opacity: 0 });
          S(s.chk, { opacity: 0 });
          const rp = prog(t, T[k], 0.5, ease.outQuart);
          show(rowEls[k].row, rp, (1 - rp) * 14, 0);
          for (const n in rowEls[k].states) S(rowEls[k].states[n], { opacity: 0 });
          sum += M[k].total * p;
        }
        S(tuSeg, { opacity: 0 });
        S(tuRow, { display: "none" });
        // the total counts up as shares land, and lands on $815.00 with the voice
        const fin = prog(t, 82.95, 0.5, ease.outQuart);
        setText(totalV, E.money(Math.round(sum)));
        S(totalV, { color: fin > 0.5 ? "#0e6e64" : "#1c1714", transform: `scale(${(1 + 0.06 * Math.sin(Math.PI * fin)).toFixed(4)})`, display: "inline-block", transformOrigin: "100% 70%" });
        return;
      }
      const st = holdState(t);
      for (const k of ORDER) {
        const s = segs[k];
        const r = rowEls[k];
        // status pills crossfade
        for (const n in r.states) {
          const on = st[k] === n;
          S(r.states[n], { opacity: on ? 1 : 0, transform: on ? "translateY(0px)" : "translateY(4px)" });
        }
        let lift = 0;
        let ghost = 0;
        let check = 0;
        if (k === "priya") {
          lift = env(t, 110.95, 113.9, 0.45, 0.6) * -12;
          check = prog(t, 113.45, 0.35, ease.outQuart);
        }
        if (k === "amina") {
          lift = env(t, 120.8, 122.2, 0.4, 0.5) * -12;
          check = prog(t, 121.6, 0.35, ease.outQuart);
        }
        if (k === "grace") ghost = prog(t, 129.2, 0.7, ease.inOutCubic);
        S(s.seg, {
          transform: `translateY(${lift.toFixed(2)}px)`,
          boxShadow: lift < -0.5 ? `0 ${(-lift).toFixed(1)}px ${(-lift * 1.6).toFixed(1)}px rgba(28,23,20,0.18)` : "none",
          opacity: 1,
        });
        S(s.inner, { opacity: 1 - ghost });
        S(s.ghost, { opacity: ghost });
        S(s.chk, { opacity: check, transform: `scale(${(0.6 + 0.4 * check).toFixed(3)})` });
        S(r.row, { opacity: k === "grace" ? 1 - 0.45 * ghost : 1 });
      }
      // top-up slides into Grace's slot
      const tu = prog(t, 132.5, 0.8, ease.inOutCubic);
      S(tuSeg, { opacity: tu > 0 ? 1 : 0, transform: `translateX(${((1 - tu) * 60).toFixed(2)}px) scaleX(${tu.toFixed(4)})`, transformOrigin: "0 50%" });
      // the top-up row opens smoothly under Grace's
      const hp = prog(t, 132.3, 0.5, ease.inOutCubic);
      const tr = prog(t, 132.55, 0.5, ease.outQuart);
      S(tuRow, {
        display: hp > 0 ? "grid" : "none",
        height: 52 * hp,
        overflow: "hidden",
        opacity: tr,
        transform: `translateX(${((1 - tr) * 14).toFixed(2)}px)`,
      });
    }
    return { el, update };
  }

  // ---------- captions ----------
  function Captions(root) {
    const lines = window.NARRATION;
    const chunks = [];
    lines.forEach((ln, li) => {
      const cuts = window.CAPTION_CUTS[li];
      const joined = cuts.map((c) => c[0]).join(" ");
      if (joined !== ln.line) throw new Error(`Caption cuts for line ${li + 1} do not match narration:\n${joined}\n${ln.line}`);
      cuts.forEach((c, ci) => {
        const t0 = ci === 0 ? ln.start : c[1];
        chunks.push({ text: c[0], t0, line: li, last: ci === cuts.length - 1, lineEnd: ln.end });
      });
    });
    chunks.forEach((c, i) => {
      const next = chunks[i + 1];
      if (c.last) c.t1 = Math.min(c.lineEnd + 0.3, next ? next.t0 - 0.05 : Infinity);
      else c.t1 = next.t0;
      c.el = h("div", { class: "cap-text" }, c.text);
      root.appendChild(c.el);
    });
    const pill = h("div", { class: "cap-pill" });
    root.insertBefore(pill, root.firstChild);
    function measure() {
      for (const c of chunks) {
        c.w = c.el.offsetWidth;
        c.h = c.el.offsetHeight;
      }
    }
    let measured = false;
    function update(t) {
      if (!measured) {
        measure();
        measured = true;
      }
      let pillA = 0;
      let cur = null;
      let prev = null;
      for (let i = 0; i < chunks.length; i++) {
        const c = chunks[i];
        const a = env(t, c.t0 - 0.04, c.t1, 0.16, 0.18, ease.inOutSine);
        S(c.el, { opacity: a, visibility: a > 0.001 ? "visible" : "hidden" });
        if (t >= c.t0 - 0.04 && t < c.t1) {
          cur = c;
          prev = chunks[i - 1] || null;
        }
        pillA = Math.max(pillA, a);
      }
      if (!cur) {
        // fading out after a chunk: keep the size of the chunk that just ended
        for (const c of chunks) if (t >= c.t1 && t < c.t1 + 0.2) cur = c;
      }
      if (cur) {
        let w = cur.w;
        let hh = cur.h;
        if (prev && cur.t0 - prev.t1 < 0.3) {
          const p = prog(t, cur.t0 - 0.04, 0.24, ease.inOutCubic);
          w = lerp(prev.w, cur.w, p);
          hh = lerp(prev.h, cur.h, p);
        }
        S(pill, { width: w, height: hh });
      }
      S(pill, { opacity: pillA, visibility: pillA > 0.001 ? "visible" : "hidden" });
      const onTeal = t >= 161.1 && t < 166.0;
      root.className = onTeal ? "on-teal" : "";
    }
    return { update };
  }

  window.C = { ICON, svg, fmt, esc, langOf, Phone, Browser, HoldCard, Captions };
})();
