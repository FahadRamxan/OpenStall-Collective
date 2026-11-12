/* OpenStall demo video: the scenes, in story order. Each scene builds its DOM once and update(t) poses it. */
(function () {
  "use strict";
  const { h, S, show, setText, clamp, lerp, ease, prog, env, track, scene, W, H } = E;
  const { ICON, svg, Phone, Browser, HoldCard } = C;
  const M = window.MAKERS;

  // entrance / exit helpers: [opacity, offset]
  const rise = (t, t0, d = 0.6, dy = 26) => {
    const p = prog(t, t0, d, ease.outQuart);
    return [p, (1 - p) * dy];
  };
  const leave = (t, t0, d = 0.45, dy = -18) => {
    const p = prog(t, t0, d, ease.inOutCubic);
    return [1 - p, p * dy];
  };
  const both = (t, tin, tout, d1 = 0.6, d2 = 0.45, dy1 = 26, dy2 = -18) => {
    const [a, y1] = rise(t, tin, d1, dy1);
    const [b, y2] = leave(t, tout, d2, dy2);
    return [Math.min(a, b), y1 + (1 - b > 0 ? y2 : 0)];
  };
  const sceneEl = (name) => h("div", { class: "scene", "data-scene": name, style: { display: "none" } });
  const pill = (html, cls = "") => h("div", { class: "pill " + cls, html });
  const center = (el) => el.offsetWidth / 2;

  window.buildScenes = function (root) {
    // =====================================================================================================
    // 1. HOOK  0.0 - 15.9: forty covers, thirty days; one AI agent; the makers on a map
    // =====================================================================================================
    {
      const el = sceneEl("hook");
      root.appendChild(el);
      // the counter group
      const grp = h("div", { class: "abs", style: { left: "0", top: "0", width: "1920px", height: "1080px", transformOrigin: "960px 520px" } });
      const big = h("div", { class: "abs big-num", style: { left: "0", width: "1920px", top: "196px", textAlign: "center" } }, "0");
      const sub = h("div", { class: "abs", style: { left: "0", width: "1920px", top: "526px", textAlign: "center", fontSize: "50px", fontWeight: "500", color: "var(--muted)", letterSpacing: "-0.01em" } }, "hand-embroidered cushion covers");
      const chip = pill(`${ICON.calendar("#0e6e64", 30)}<span style="font-size:32px;font-weight:600">30 days</span>`, "");
      S(chip, { left: 0, top: 628 });
      const dots = h("div", { class: "abs", style: { left: "0", top: "760px", width: "1920px", display: "flex", justifyContent: "center", gap: "8px" } });
      const dotEls = [];
      for (let i = 0; i < 40; i++) {
        const d = h("i", { style: { display: "block", width: "16px", height: "16px", borderRadius: "5px", background: "#e8e1d7" } });
        dots.appendChild(d);
        dotEls.push(d);
      }
      grp.append(big, sub, chip, dots);
      el.appendChild(grp);

      // the buyer's agent card
      const agent = h("div", { class: "card", style: { left: "1010px", top: "322px", width: "760px", padding: "34px 36px 36px" } });
      agent.innerHTML = `
        <div style="display:flex;align-items:center;gap:18px">
          <div style="width:66px;height:66px;border-radius:18px;background:#1c1714;display:grid;place-items:center">${ICON.agent("#fff", 36)}</div>
          <div style="display:flex;flex-direction:column;gap:6px">
            <div style="font-size:34px;font-weight:600;letter-spacing:-0.015em">An AI shopping agent</div>
            <div style="display:flex;align-items:center;gap:9px;font-size:22px;color:var(--muted)"><i class="live" style="width:11px;height:11px;border-radius:50%;background:#1baf7a;display:block"></i>ready to buy</div>
          </div>
        </div>
        <div class="code" style="margin-top:28px;padding:20px 22px;border-radius:16px;background:#f4f1ea;border:1px solid var(--border);font-family:var(--mono);font-size:23px;color:#1c1714;height:72px;white-space:nowrap"><span class="typed"></span><span class="caret" style="display:inline-block;width:2px;height:28px;background:#0e6e64;vertical-align:-6px;margin-left:2px"></span></div>`;
      el.appendChild(agent);
      const typed = agent.querySelector(".typed");
      const caret = agent.querySelector(".caret");
      const liveDot = agent.querySelector(".live");
      const CALL = "request_quote(40 cushion covers, at most $30)";

      // compact agent chip during the map
      const achip = pill(`<span style="width:30px;height:30px;border-radius:9px;background:#1c1714;display:grid;place-items:center">${ICON.agent("#fff", 20)}</span><span>Buyer's AI agent</span><span class="mono" style="font-size:19px;color:var(--muted)">40 cushion covers · at most $30</span>`);
      el.appendChild(achip);

      // the map
      const MAP = window.MAP_DOTS;
      const MX = 60;
      const MY = 196;
      const PXD = 1800 / (MAP.lon1 - MAP.lon0);
      const proj = (lon, lat) => [MX + (lon - MAP.lon0) * PXD, MY + (MAP.lat1 - lat) * PXD];
      const mapWrap = h("div", { class: "abs", style: { left: "0", top: "0", width: "1920px", height: "1080px", transformOrigin: "960px 480px" } });
      const cv = h("canvas", { class: "mapcanvas", width: "1920", height: "1080" });
      mapWrap.appendChild(cv);
      el.appendChild(mapWrap);
      const ctx = cv.getContext("2d");
      ctx.fillStyle = "#d9d0c2";
      for (const [lon, lat] of MAP.dots) {
        const [x, y] = proj(lon, lat);
        ctx.beginPath();
        ctx.arc(x, y, 2.9, 0, Math.PI * 2);
        ctx.fill();
      }
      const PINS = [
        { k: "amina", at: 9.05, lbl: [-250, -64] },
        { k: "priya", at: 9.45, lbl: [-250, 26] },
        { k: "lucia", at: 9.85, lbl: [26, 10] },
        { k: "grace", at: 10.25, lbl: [26, -64] },
        { k: "noor", at: 10.65, lbl: [26, -64] },
      ];
      const pinEls = PINS.map((p) => {
        const m = M[p.k];
        const [x, y] = proj(m.lon, m.lat);
        const pin = h("div", { class: "pin", style: { left: x + "px", top: y + "px", color: m.color } });
        const core = h("div", { class: "core", style: { background: m.color } });
        const ring = h("div", { class: "ring" });
        const ring2 = h("div", { class: "ring" });
        const lbl = h("div", { class: "lbl", style: { left: p.lbl[0] + "px", top: p.lbl[1] + "px", display: "flex", alignItems: "center", gap: "10px" } });
        const mp = h("div", { class: "mini-phone" }, h("div", { class: "ms" }, h("i", { style: { top: "14px" } }), h("i", { class: "o", style: { top: "26px" } }), h("i", { style: { top: "38px" } })));
        const tag = pill(`<span class="dot" style="background:${m.color}"></span><span style="font-weight:600">${m.name}</span><span style="color:var(--muted)">${m.city}</span>`);
        tag.style.position = "relative";
        tag.style.fontSize = "21px";
        tag.style.padding = "8px 15px";
        if (p.lbl[0] < 0) lbl.append(tag, mp);
        else lbl.append(mp, tag);
        pin.append(ring, ring2, core, lbl);
        el.appendChild(pin);
        return { p, m, pin, core, ring, ring2, lbl, mp, x, y };
      });
      // the meter that never reaches 40
      const meter = h("div", { class: "abs", style: { left: "0", top: "846px", width: "1920px", display: "flex", justifyContent: "center", alignItems: "center", gap: "22px" } });
      meter.innerHTML = `
        <span style="font-size:23px;color:var(--muted);font-weight:500">Any one maker, alone</span>
        <span style="position:relative;width:620px;height:22px;border-radius:11px;background:#ece6dc;overflow:hidden;display:block">
          <span class="fill" style="position:absolute;left:0;top:0;bottom:0;width:0;border-radius:11px;background:linear-gradient(90deg,#8a7f75,#5a514a)"></span>
          <span class="gap" style="position:absolute;top:3px;bottom:3px;right:3px;border-radius:9px;border:2px dashed #cdbfae;opacity:0"></span>
        </span>
        <span style="font-size:23px;font-weight:600">40 needed</span>`;
      el.appendChild(meter);
      const fill = meter.querySelector(".fill");
      const gapEl = meter.querySelector(".gap");
      el.__layout = () => {
        S(chip, { left: 960 - chip.offsetWidth / 2 });
        S(achip, { left: 960 - achip.offsetWidth / 2, top: 74 });
      };

      scene({
        name: "hook", t0: 0, t1: 15.9, el,
        update(t) {
          // counter
          const v = Math.round(40 * prog(t, 0.25, 2.2, ease.outCubic));
          setText(big, String(v));
          for (let i = 0; i < 40; i++) S(dotEls[i], { background: i < v ? "#0e6e64" : "#e8e1d7" });
          const [ob, yb] = rise(t, 0.05, 0.7, 30);
          show(big, ob, 0, yb);
          const [os, ys] = rise(t, 0.85, 0.7, 22);
          show(sub, os, 0, ys);
          const [oc, yc] = rise(t, 2.85, 0.6, 20);
          show(chip, oc, 0, yc);
          const [od, yd] = rise(t, 0.2, 0.6, 16);
          show(dots, od, 0, yd);
          // shift left for the agent, then away for the map
          const sh = prog(t, 5.2, 0.85, ease.inOutCubic);
          const out = prog(t, 8.2, 0.5, ease.inOutCubic);
          show(grp, 1 - out, -420 * sh, -30 * out, 1 - 0.22 * sh);
          // agent card
          const [oa, xa] = rise(t, 5.35, 0.75, 70);
          const aOut = prog(t, 8.15, 0.5, ease.inOutCubic);
          show(agent, Math.min(oa, 1 - aOut), xa * 1, -24 * aOut);
          const n = Math.round(CALL.length * clamp((t - 5.95) / 1.25));
          setText(typed, CALL.slice(0, n));
          S(caret, { opacity: t < 7.9 && Math.floor(t * 2.4) % 2 === 0 ? 1 : n < CALL.length && t > 5.9 ? 1 : 0 });
          S(liveDot, { opacity: 0.55 + 0.45 * Math.sin(t * 4) });
          // agent chip on the map
          const [oq, yq] = rise(t, 8.85, 0.6, -14);
          const qOut = prog(t, 14.75, 0.45, ease.inOutCubic);
          show(achip, Math.min(oq, 1 - qOut), 0, yq);
          // map
          const mIn = prog(t, 8.65, 1.0, ease.outCubic);
          const mOut = prog(t, 14.8, 0.55, ease.inOutCubic);
          show(mapWrap, Math.min(mIn, 1 - mOut), 0, 0, 1.03 - 0.03 * mIn);
          // pins; from 14.9 they gather to the centre, where the logo appears
          const gather = prog(t, 14.85, 0.85, ease.inOutCubic);
          for (const q of pinEls) {
            const a = q.p.at;
            const pp = prog(t, a, 0.45, ease.outQuart);
            const gx = (960 - q.x) * gather;
            const gy = (392 - q.y) * gather;
            const fadeG = 1 - prog(t, 15.55, 0.2, ease.linear);
            show(q.pin, pp > 0 ? fadeG : 0, gx, gy);
            S(q.core, { transform: `scale(${(pp * (1 - 0.35 * gather)).toFixed(3)})` });
            const r1 = clamp((t - a) / 1.2);
            S(q.ring, { opacity: t >= a ? (1 - r1) * 0.7 * (1 - gather) : 0, transform: `scale(${(1 + 2.6 * ease.outCubic(r1)).toFixed(3)})` });
            const per = (t - a - 1.2) % 2.6;
            const r2 = clamp(per / 1.6);
            S(q.ring2, { opacity: t >= a + 1.2 && per >= 0 ? (1 - r2) * 0.35 * (1 - gather) : 0, transform: `scale(${(1 + 2.2 * ease.outCubic(r2)).toFixed(3)})` });
            const [ol, yl] = rise(t, a + 0.12, 0.5, 10);
            show(q.lbl, ol * (1 - prog(t, 14.8, 0.4, ease.inOutCubic)), 0, yl);
            const mp = prog(t, a + 0.25, 0.45, ease.outQuart);
            S(q.mp, { opacity: mp, transform: `translateY(${((1 - mp) * 8).toFixed(2)}px)` });
          }
          // meter
          const [om, ym] = rise(t, 11.75, 0.6, 16);
          show(meter, Math.min(om, 1 - mOut), 0, ym);
          const f = prog(t, 12.05, 1.3, ease.inOutCubic);
          S(fill, { width: 620 * 0.31 * f });
          S(gapEl, { left: 620 * 0.31 + 8, opacity: prog(t, 13.1, 0.5) });
        },
      });
    }

    // =====================================================================================================
    // 2. TITLE  14.8 - 22.9: the logo, the name, three steps
    // =====================================================================================================
    {
      const el = sceneEl("title");
      root.appendChild(el);
      const logo = h("img", { class: "abs", src: "../assets/logo.svg", style: { left: "875px", top: "300px", width: "170px", height: "170px", transformOrigin: "50% 50%" } });
      const word = h("div", { class: "abs", style: { left: "0", width: "1920px", top: "506px", textAlign: "center", fontSize: "80px", letterSpacing: "-0.03em", lineHeight: "1" } });
      word.innerHTML = `<span style="font-weight:600">OpenStall</span><span style="font-weight:400;color:var(--muted)"> Collective</span>`;
      const row = h("div", { class: "abs", style: { left: "0", top: "640px", width: "1920px", height: "80px" } });
      const steps = [
        ["1", "List", 19.3],
        ["2", "Split", 19.98],
        ["3", "Pay on proof", 20.7],
      ];
      const chips = steps.map(([n, txt]) => {
        const c = h("div", { class: "chip" }, h("span", { class: "num" }, n), h("span", {}, txt));
        row.appendChild(c);
        return c;
      });
      const links = [0, 1].map(() => {
        const l = h("div", { class: "abs", style: { top: "39px", height: "2px", background: "#d6cdbf", transformOrigin: "0 50%" } });
        row.appendChild(l);
        return l;
      });
      el.append(logo, word, row);
      el.__layout = () => {
        const gap = 64;
        const ws = chips.map((c) => c.offsetWidth);
        let x = 960 - (ws.reduce((a, b) => a + b, 0) + gap * 2) / 2;
        chips.forEach((c, i) => {
          c.style.left = x + "px";
          c.style.top = "4px";
          if (i < 2) {
            links[i].style.left = x + ws[i] + 10 + "px";
            links[i].style.width = gap - 20 + "px";
          }
          x += ws[i] + gap;
        });
      };
      scene({
        name: "title", t0: 14.8, t1: 22.9, el,
        update(t) {
          const out = prog(t, 21.95, 0.4, ease.inOutCubic);
          const up = -72 * prog(t, 18.55, 0.75, ease.inOutCubic);
          const lp = prog(t, 15.45, 0.75, ease.outQuart);
          show(logo, lp * (1 - out), 0, up - 30 * out, 0.86 + 0.14 * lp);
          const [ow, yw] = rise(t, 15.85, 0.7, 22);
          show(word, ow * (1 - out), 0, up + yw - 30 * out);
          show(row, 1 - out, 0, -30 * out);
          chips.forEach((c, i) => {
            const [oc, yc] = rise(t, steps[i][2], 0.55, 20);
            show(c, oc, 0, yc);
          });
          links.forEach((l, i) => {
            const p = prog(t, steps[i + 1][2] - 0.15, 0.45, ease.inOutCubic);
            S(l, { transform: `scaleX(${p.toFixed(3)})`, opacity: p > 0 ? 1 : 0 });
          });
        },
      });
    }

    // =====================================================================================================
    // 3. MANTRA  22.2 - 28.0: Claude does the talking. Code decides. PayPal holds the money.
    // =====================================================================================================
    {
      const el = sceneEl("mantra");
      root.appendChild(el);
      const L = [
        ["Claude", " does the talking.", ICON.chat("#fff", 36), 22.35],
        ["Code", " decides.", ICON.code("#fff", 36), 23.6],
        ["PayPal", " holds the money.", ICON.hold("#fff", 36), 24.8],
      ];
      const block = h("div", { class: "abs", style: { left: "0", top: "0" } });
      const lines = L.map(([a, b, ic], i) => {
        const line = h("div", { class: "abs", style: { left: "0", top: 318 + i * 148 + "px", display: "flex", alignItems: "center", gap: "30px" } });
        const tile = h("div", { style: { width: "78px", height: "78px", borderRadius: "22px", background: "var(--teal)", display: "grid", placeItems: "center", flex: "none" }, html: ic });
        const txt = h("div", { class: "kinetic", html: `<span style="color:var(--teal)">${a}</span><span class="rest">${b}</span>` });
        line.append(tile, txt);
        block.appendChild(line);
        return { line, txt };
      });
      el.appendChild(block);
      el.__layout = () => {
        const w = Math.max(...lines.map((l) => l.line.offsetWidth));
        block.style.left = 960 - w / 2 + "px";
      };
      scene({
        name: "mantra", t0: 22.2, t1: 28.0, el,
        update(t) {
          lines.forEach((l, i) => {
            const [o, y] = rise(t, L[i][3], 0.6, 28);
            const outT = 27.25 + i * 0.08;
            const [o2, y2] = leave(t, outT, 0.5, -20);
            show(l.line, Math.min(o, o2), 0, y + (t > outT ? y2 : 0));
            const next = L[i + 1] ? L[i + 1][3] : 99;
            const dim = prog(t, next, 0.45, ease.inOutSine);
            S(l.txt, { opacity: 1 - 0.42 * dim });
          });
        },
      });
    }

    // =====================================================================================================
    // 4. CHAPTER CARDS
    // =====================================================================================================
    function chapter(n, title, t0, tin, tout, t1) {
      const el = sceneEl("chapter" + n);
      root.appendChild(el);
      const eb = h("div", { class: "abs eyebrow", style: { left: "0", width: "1920px", top: "352px", textAlign: "center", fontSize: "26px", letterSpacing: "0.16em" } }, "Step " + n);
      const tt = h("div", { class: "abs", style: { left: "0", width: "1920px", top: "398px", textAlign: "center", fontSize: "132px", fontWeight: "600", letterSpacing: "-0.035em", lineHeight: "1.05" } }, title);
      const row = h("div", { class: "abs", style: { left: "0", top: "602px", width: "1920px", display: "flex", justifyContent: "center", gap: "14px" } });
      ["List", "Split", "Pay on proof"].forEach((s, i) => {
        const on = i + 1 === n;
        const done = i + 1 < n;
        const c = h("div", {
          style: {
            display: "inline-flex", alignItems: "center", gap: "10px", padding: "10px 20px 10px 12px", borderRadius: "999px", fontSize: "24px", fontWeight: "600",
            background: on ? "var(--teal)" : "#fff", color: on ? "#fff" : done ? "var(--teal-strong)" : "var(--muted)", border: on ? "1px solid var(--teal)" : "1px solid var(--border)",
          },
          html: `<span style="width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-family:var(--mono);font-size:16px;background:${on ? "#fff" : done ? "var(--teal-soft)" : "#f3efe7"};color:${on ? "var(--teal)" : done ? "var(--teal-strong)" : "var(--muted)"}">${done ? ICON.check("#0a574f", 16) : i + 1}</span>${s}`,
        });
        row.appendChild(c);
      });
      el.append(eb, tt, row);
      scene({
        name: "chapter" + n, t0, t1, el,
        update(t) {
          const [o1, y1] = rise(t, tin, 0.6, 20);
          const [o2, y2] = rise(t, tin + 0.1, 0.65, 28);
          const [o3, y3] = rise(t, tin + 0.25, 0.6, 18);
          const out = prog(t, tout, 0.45, ease.inOutCubic);
          show(eb, o1 * (1 - out), 0, y1 - 20 * out);
          show(tt, o2 * (1 - out), 0, y2 - 20 * out);
          show(row, o3 * (1 - out), 0, y3 - 20 * out);
        },
      });
    }
    chapter(1, "List", 27.8, 28.0, 29.95, 30.6);
    chapter(2, "Split", 58.7, 58.92, 60.55, 61.2);
    chapter(3, "Pay on proof", 97.3, 97.55, 99.75, 100.4);

    // =====================================================================================================
    // 5. STEP ONE  30.1 - 59.0: the real chat, and the listing it builds
    // =====================================================================================================
    {
      const el = sceneEl("listing");
      root.appendChild(el);
      const phone = Phone("real");
      el.appendChild(phone.el);
      const label = pill(`<span class="dot" style="background:#1baf7a"></span>${window.CHATS.real.label}`);
      el.appendChild(label);
      const read = pill(`${ICON.spark("#0e6e64", 24)}<span>Claude reads the photo</span>`, "soft");
      el.appendChild(read);

      // the listing card
      const card = h("div", { class: "card listing", style: { left: "880px", top: "184px", width: "690px" } });
      const status = h("span", { class: "l-status" }, h("span", { class: "dot" }), h("span", { class: "st-txt" }, "Draft"));
      card.appendChild(h("div", { class: "l-head" }, h("span", { class: "l-title" }, "Your listing so far"), status));
      const ROWS = [
        { k: "Item", v: "Blue patterned cushion cover", src: null, at: 40.35 },
        { k: "Price", v: "$15.00 each", src: "15$", msg: 5, at: 42.25 },
        { k: "Per week", v: "100 a week", src: "100", msg: 7, at: 43.85 },
        { k: "Delivery", v: "arrives in 20 days", src: "20", msg: 9, at: 45.75 },
        { k: "Ships from", v: "from Islamabad", src: "Islamabad, Pakistan", msg: 11, at: 47.35 },
        { k: "Lowest", v: "$8.00 for a big order", src: "8$", msg: 13, at: 48.95 },
        { k: "Make time", v: "25 days to make an order", src: "25", msg: 15, at: 50.5 },
      ];
      const rowEls = ROWS.map((r) => {
        const v = h("span", { class: "v" });
        const ph = h("span", { class: "ph" }, "…");
        const val = h("span", {}, r.v);
        v.append(ph, val);
        ph.style.position = "absolute";
        const srcEl = r.src
          ? h("span", { class: "src" }, r.src)
          : h("span", { class: "src", html: `${ICON.spark("#0a574f", 15)} from his photo`, style: { display: "inline-flex", alignItems: "center", gap: "6px", fontFamily: "var(--sans)", fontWeight: "500" } });
        const row = h("div", { class: "row" }, h("span", { class: "k" }, r.k), v, srcEl);
        card.appendChild(row);
        return { r, row, ph, val, srcEl };
      });
      const link = h("div", { class: "link" }, "openstall-collective.onrender.com/stall/…");
      card.appendChild(link);
      el.appendChild(card);
      const agentsRow = h("div", { class: "abs", style: { left: "900px", top: "0", display: "flex", alignItems: "center", gap: "12px" } });
      agentsRow.appendChild(h("span", { style: { fontSize: "21px", color: "var(--muted)", fontWeight: "500", marginRight: "4px" } }, "For any AI agent to read:"));
      const agentChips = ["MCP", "catalog.json", "llms.txt"].map((s) => {
        const c = pill(`<span class="mono" style="font-size:20px">${s}</span>`, "soft");
        c.style.position = "relative";
        agentsRow.appendChild(c);
        return c;
      });
      el.appendChild(agentsRow);
      // flying tokens: his words travel from his bubble to the field they fill
      const tokens = ROWS.filter((r) => r.src).map((r) => {
        const tk = h("div", { class: "token" }, r.src);
        el.appendChild(tk);
        return { r, tk };
      });
      let geo = null;
      el.__layout = () => {
        // keep each value clear of its source chip
        for (const x of rowEls) x.row.querySelector(".v").style.paddingRight = x.srcEl.offsetWidth + 16 + "px";
        geo = rowEls.map((x) => ({ x: card.offsetLeft + x.row.offsetLeft + x.srcEl.offsetLeft, y: card.offsetTop + x.row.offsetTop + x.row.offsetHeight / 2 }));
        S(agentsRow, { top: card.offsetTop + card.offsetHeight + 26, left: card.offsetLeft });
      };
      const phoneX = (t) => track(t, [[30.1, 760], [39.25, 760], [40.25, 380, "inOutCubic"]]);
      scene({
        name: "listing", t0: 30.1, t1: 59.0, el,
        update(t) {
          const px = phoneX(t);
          const [op, yp] = rise(t, 30.4, 0.75, 60);
          const out = prog(t, 58.15, 0.6, ease.inOutCubic);
          show(phone.el, op * (1 - out), px, 64 + yp + 30 * out);
          phone.update(t);
          const [ol, yl] = rise(t, 30.6, 0.6, 14);
          show(label, ol * (1 - out), px + 424, 92 + yl);
          // "Claude reads the photo" chip, beside the photo
          const pb = phone.bubbleBox(3, t);
          const [orr, xr] = rise(t, 38.1, 0.45, -16);
          const rOut = prog(t, 39.3, 0.35, ease.inOutCubic);
          show(read, Math.min(orr, 1 - rOut), px + 400 + 20 + xr, 64 + pb.y + pb.h / 2 - 24);
          // card
          const [oc, yc] = rise(t, 39.95, 0.7, 30);
          show(card, oc * (1 - out), 0, yc + 30 * out);
          for (let i = 0; i < rowEls.length; i++) {
            const x = rowEls[i];
            const land = x.r.msg != null ? x.r.at + 0.62 : x.r.at;
            const p = prog(t, land, 0.35, ease.outCubic);
            S(x.ph, { opacity: 1 - p });
            S(x.val, { opacity: p });
            S(x.srcEl, { opacity: prog(t, land - 0.05, 0.3), visibility: t >= land - 0.05 ? "visible" : "hidden" });
            S(x.row, { backgroundColor: `rgba(225, 242, 238, ${(0.9 * env(t, land, land + 1.1, 0.15, 0.8)).toFixed(3)})` });
          }
          // tokens
          for (const tk of tokens) {
            const t0 = tk.r.at + 0.08;
            const p = clamp((t - t0) / 0.54);
            if (t < t0 || p >= 1 || !geo) {
              S(tk.tk, { opacity: 0, visibility: "hidden" });
              continue;
            }
            const bb = phone.bubbleBox(tk.r.msg, t);
            const sx = px + bb.x + bb.w / 2 - 30;
            const sy = 64 + bb.y + bb.h / 2 - 16;
            const g = geo[ROWS.indexOf(tk.r)];
            const ex = g.x;
            const ey = g.y - 17;
            const e = ease.inOutCubic(p);
            const x = lerp(sx, ex, e);
            const y = lerp(sy, ey, e) - 70 * Math.sin(Math.PI * e);
            S(tk.tk, { opacity: Math.min(1, p * 5, (1 - p) * 6), visibility: "visible", transform: `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)` });
          }
          // live
          const live = prog(t, 54.25, 0.4, ease.outCubic);
          setText(status.querySelector(".st-txt"), t >= 54.25 ? "Live" : "Draft");
          S(status, { background: t >= 54.25 ? "#e1f2ee" : "#f3efe7", color: t >= 54.25 ? "#0a574f" : "#5a514a" });
          S(status.querySelector(".dot"), { background: t >= 54.25 ? "#1baf7a" : "#c9bfb1" });
          S(link, { opacity: live });
          agentChips.forEach((c, i) => {
            const [o, y] = rise(t, 55.4 + i * 0.35, 0.5, 14);
            show(c, o * (1 - out), 0, y);
          });
          S(agentsRow.firstChild, { opacity: prog(t, 55.25, 0.4) * (1 - out) });
        },
      });
    }

    // =====================================================================================================
    // 6. STEP TWO  60.7 - 93.9: R2 (request, offers, split) and R3 (approval, simulated PayPal, the hold)
    // =====================================================================================================
    const testSite = () => ({ url: "localhost:3000", badge: "Test mode · PayPal simulated", sandbox: false });
    {
      const el = sceneEl("split");
      root.appendChild(el);
      const br = Browser({ vw: 1504, vh: 846, shots: ["r2a", "r2b", "r3a", "r3c", "r3d"], site: testSite });
      S(br.el, { left: 208, top: 30 });
      el.appendChild(br.el);
      const lab1 = pill(`<span class="mono" style="font-size:18px;color:var(--teal-strong);background:var(--teal-soft);padding:3px 8px;border-radius:7px">MCP</span><span>MCP storefront: search · request_quote</span>`);
      const lab2 = pill(`<span>No agent can talk a price below a maker's floor.</span>`, "teal");
      const lab3 = pill(`<span class="mono" style="font-size:20px">intent AUTHORIZE</span><span style="opacity:.7">·</span><span>held, not captured</span>`, "teal");
      el.append(lab1, lab2, lab3);
      const card = HoldCard("split", 480);
      S(card.el, { left: 1212, top: 176 });
      el.appendChild(card.el);
      const RIGHT = 208 + 1504 - 24;
      scene({
        name: "split", t0: 60.7, t1: 93.9, el,
        update(t, playing) {
          const [o, y] = rise(t, 60.95, 0.7, 50);
          const out = prog(t, 92.95, 0.45, ease.inOutCubic);
          show(br.el, o * (1 - out), 0, y + 30 * out, 0.985 + 0.015 * o);
          br.update(t, playing);
          const [o1, y1] = both(t, 61.7, 68.4, 0.55, 0.4, 14, -10);
          show(lab1, o1, RIGHT - lab1.offsetWidth, 100 + y1);
          const [o2, y2] = both(t, 73.55, 75.05, 0.5, 0.35, 14, -10);
          show(lab2, o2, 960 - lab2.offsetWidth / 2, 98 + y2);
          const [o3, y3] = both(t, 89.85, 92.85, 0.55, 0.4, 14, -10);
          show(lab3, o3, RIGHT - lab3.offsetWidth, 100 + y3);
          const [oc, yc] = both(t, 76.75, 85.3, 0.6, 0.45, 26, -16);
          show(card.el, oc, 0, yc);
          card.update(t);
        },
      });
    }

    // =====================================================================================================
    // 7. FOUR PHONES  93.2 - 97.8: each maker hears about her share, in her own language
    // =====================================================================================================
    {
      const el = sceneEl("four");
      root.appendChild(el);
      const KEYS = [["amina4", "amina"], ["priya4", "priya"], ["lucia", "lucia"], ["grace4", "grace"]];
      const SC = 0.74;
      const ps = KEYS.map(([ck, mk], i) => {
        const ph = Phone(ck);
        el.appendChild(ph.el);
        const m = M[mk];
        const tag = pill(`<span class="dot" style="background:${m.color}"></span><span style="font-weight:600">${m.name}</span><span style="color:var(--muted)">${m.lang}</span>`);
        tag.style.fontSize = "22px";
        el.appendChild(tag);
        // her order's price line, in English (Grace's message is in English already, so it has no English line)
        const first = window.CHAT_SOURCES[window.CHATS[ck].source][0];
        const priceLine = (first.english || first.text).split("\n").find((s) => s.startsWith("Price:"));
        const note = h("div", { class: "abs", style: { textAlign: "center", width: "330px", fontSize: "18px", color: "var(--ink)", fontWeight: "500" } }, priceLine);
        el.appendChild(note);
        const cx = 465 + i * 330;
        return { ph, tag, note, cx, i };
      });
      scene({
        name: "four", t0: 93.2, t1: 97.8, el,
        update(t) {
          const out = prog(t, 97.05, 0.4, ease.inOutCubic);
          for (const p of ps) {
            const [o, y] = rise(t, 93.45 + p.i * 0.07, 0.65, 40);
            show(p.ph.el, o * (1 - out), p.cx - 200 * SC, 128 + y + 24 * out, SC);
            p.ph.update(t);
            show(p.tag, o * (1 - out), p.cx - p.tag.offsetWidth / 2, 62 + y);
            const [on, yn] = rise(t, 94.6 + p.i * 0.12, 0.5, 12);
            show(p.note, on * (1 - out), p.cx - 165, 128 + 840 * SC + 26 + yn);
          }
        },
      });
    }

    // =====================================================================================================
    // 8. STEP THREE  99.9 - 135.4: Priya paid on proof, Amina paid through Hyperwallet (simulated), Grace drops out
    // =====================================================================================================
    {
      const el = sceneEl("proof");
      root.appendChild(el);
      const PX = 236;
      const PY = 64;
      const COL = 772; // the right column: x 772 to 1732
      const COLW = 960;
      // one phone at a time: the old one slides out before the next slides in
      const phones = {
        priya: { ph: Phone("priya"), tin: 100.2, tout: 117.15 },
        amina: { ph: Phone("amina"), tin: 117.5, tout: 124.95 },
        grace: { ph: Phone("grace"), tin: 125.3, tout: 134.45 },
      };
      for (const k in phones) {
        const m = M[k];
        phones[k].tag = pill(`<span class="dot" style="background:${m.color}"></span><span style="font-weight:600">${m.name}'s phone</span><span style="color:var(--muted)">${m.city}</span>`);
        phones[k].tag.style.fontSize = "21px";
        el.append(phones[k].ph.el, phones[k].tag);
      }
      // Priya's receipt, big, as the AI reads it
      const rc = h("div", { class: "abs", style: { left: COL + (COLW - 500) / 2 + "px", top: "120px", width: "500px", height: "653px", borderRadius: "18px", overflow: "hidden", boxShadow: "var(--shadow-card)", background: "#5b4a3e" } });
      const rimg = h("img", { src: "../assets/receipt-priya.jpg", style: { width: "500px", height: "653px", display: "block" } });
      const rflash = h("div", { class: "abs", style: { inset: "0", background: "#fff", opacity: "0" } });
      const rhl1 = h("div", { class: "hl-box" });
      const rhl2 = h("div", { class: "hl-box" });
      rc.append(rimg, rhl1, rhl2, rflash);
      const rcap = pill(`${ICON.spark("#0e6e64", 22)}<span>AI reads the courier and the tracking number</span>`, "soft");
      el.append(rc, rcap);
      const RS = 500 / 1080;
      const box = (el2, [x0, y0, x1, y1]) => S(el2, { left: x0 * RS - 6, top: y0 * RS - 6, width: (x1 - x0) * RS + 12, height: (y1 - y0) * RS + 12 });
      box(rhl1, [455, 452, 760, 515]);
      box(rhl2, [118, 292, 724, 400]);

      const card = HoldCard("hold", 700);
      S(card.el, { left: COL + (COLW - 700) / 2, top: 196 });
      el.appendChild(card.el);
      const side = Browser({ vw: COLW, vh: 540, shots: ["r12p", "r12a", "r12g"], site: testSite });
      S(side.el, { left: COL, top: 214 });
      el.appendChild(side.el);
      const sideLab = pill(`<span>The buyer's receipt</span>`);
      el.appendChild(sideLab);
      const hw = pill(`<span style="font-weight:600">Hyperwallet</span><span class="tag">simulated</span>`);
      el.appendChild(hw);
      const RIGHTCOL = [
        // [element, in, out]: one thing at a time, each gone before the next comes in
        [rc, 100.9, 109.4],
        [card.el, 109.8, 114.5],
        [side.el, 114.9, 117.3],
        [card.el, 117.7, 122.35],
        [side.el, 122.75, 124.95],
        [card.el, 125.4, 133.05],
        [side.el, 133.45, 134.45],
      ];
      scene({
        name: "proof", t0: 99.9, t1: 135.4, el,
        update(t, playing) {
          for (const k in phones) {
            const p = phones[k];
            const a = prog(t, p.tin, 0.55, ease.outQuart);
            const b = prog(t, p.tout, 0.35, ease.inOutCubic);
            const o = Math.min(a, 1 - b);
            const on = t >= p.tin - 0.01 && t < p.tout + 0.4;
            if (!on) {
              S(p.ph.el, { visibility: "hidden", opacity: 0 });
              S(p.tag, { visibility: "hidden", opacity: 0 });
              continue;
            }
            show(p.ph.el, o, PX + 50 * (1 - a) - 50 * b, PY);
            p.ph.update(t);
            show(p.tag, o, PX + 200 - p.tag.offsetWidth / 2 + 50 * (1 - a) - 50 * b, PY - 52);
          }
          // right column: one thing at a time
          const alphaOf = (elx) => {
            let best = 0;
            for (const [e2, tin, tout] of RIGHTCOL) {
              if (e2 !== elx) continue;
              best = Math.max(best, Math.min(prog(t, tin, 0.4, ease.outQuart), 1 - prog(t, tout, 0.35, ease.inOutCubic)));
            }
            return best;
          };
          const ar = alphaOf(rc);
          show(rc, ar, 0, (1 - Math.min(1, prog(t, 100.9, 0.55, ease.outQuart))) * 30, 1);
          S(rflash, { opacity: Math.min(prog(t, 102.25, 0.06, ease.linear), 1 - prog(t, 102.31, 0.45, ease.outCubic)) * 0.85 });
          S(rhl1, { opacity: env(t, 105.55, 109.4, 0.3, 0.3) });
          S(rhl2, { opacity: env(t, 106.25, 109.4, 0.3, 0.3) });
          const [orc, yrc] = both(t, 104.75, 109.2, 0.5, 0.4, 12, -8);
          show(rcap, orc, COL + COLW / 2 - rcap.offsetWidth / 2, 800 + yrc);
          const ac = alphaOf(card.el);
          show(card.el, ac, 0, (1 - ac) * 22);
          card.update(t);
          const as = alphaOf(side.el);
          show(side.el, as, 0, (1 - as) * 22);
          side.update(t, playing);
          show(sideLab, as, COL, 214 - 60 + (1 - as) * 22);
          const [oh, yh] = both(t, 122.7, 125.0, 0.5, 0.45, 12, -8);
          show(hw, oh, COL + COLW - hw.offsetWidth, 214 - 60 + yh);
        },
      });
    }

    // =====================================================================================================
    // 9. TRUST  134.8 - 156.4: ten attacks refused, the signed passport, APIMatic's SDK and the PayPal doctor
    // =====================================================================================================
    {
      const el = sceneEl("trust");
      root.appendChild(el);
      const site = (id) =>
        id.startsWith("r9")
          ? { url: "openstall-collective.onrender.com/status", badge: "Hosted demo · PayPal sandbox", sandbox: true }
          : testSite();
      const br = Browser({ vw: 1504, vh: 846, shots: ["r7", "r8a", "r8b", "r8c", "r9a", "r9b"], site });
      S(br.el, { left: 208, top: 30 });
      el.appendChild(br.el);
      const strip = h("div", { class: "abs", style: { left: "0", top: "0", display: "flex", gap: "10px", padding: "14px 16px", borderRadius: "18px", background: "rgba(255,255,255,0.97)", border: "1px solid var(--border)", boxShadow: "var(--shadow-card)" } });
      const CH = ["Orders v2", "Payments v2", "Payouts", "Tracking", "Webhooks", "Disputes", "JS SDK", "MCP server"];
      const chs = CH.map((s) => {
        const c = h("span", { style: { display: "inline-flex", alignItems: "center", padding: "9px 16px", borderRadius: "999px", background: "var(--teal-soft)", color: "var(--teal-strong)", fontSize: "21px", fontWeight: "600", whiteSpace: "nowrap" } }, s);
        strip.appendChild(c);
        return c;
      });
      el.appendChild(strip);
      scene({
        name: "trust", t0: 134.8, t1: 156.4, el,
        update(t, playing) {
          const [o, y] = rise(t, 134.9, 0.6, 50);
          const out = prog(t, 155.7, 0.45, ease.inOutCubic);
          show(br.el, o * (1 - out), 0, y + 30 * out, 0.985 + 0.015 * o);
          br.update(t, playing);
          const so = env(t, 147.85, 155.75, 0.5, 0.4);
          show(strip, so * (1 - out), 960 - strip.offsetWidth / 2, 922 - 30 - strip.offsetHeight + (1 - prog(t, 147.85, 0.5, ease.outQuart)) * 16);
          chs.forEach((c, i) => {
            const p = prog(t, 148.0 + i * 0.27, 0.4, ease.outQuart);
            S(c, { opacity: p, transform: `translateY(${((1 - p) * 8).toFixed(2)}px)` });
          });
        },
      });
    }

    // =====================================================================================================
    // 10. NEXT  155.6 - 161.5: a receipt photo can be faked; next, the courier's own scan releases the money
    // =====================================================================================================
    {
      const el = sceneEl("next");
      root.appendChild(el);
      const nextPill = pill(`<span style="font-weight:600">Next</span>`, "teal");
      nextPill.style.fontSize = "26px";
      el.appendChild(nextPill);
      const headline = h("div", { class: "abs", style: { left: "0", width: "1920px", top: "298px", textAlign: "center", fontSize: "52px", fontWeight: "600", letterSpacing: "-0.02em" } }, "The courier's own scan will release the money");
      el.appendChild(headline);
      const Y = 640;
      const NODES = [
        { x: 420, icon: ICON.hold("#fff", 46), title: "PayPal holds the share", sub: "one authorization" },
        { x: 960, icon: ICON.scan("#fff", 50), title: "The courier's own scan", sub: "booking and tracking" },
        { x: 1500, icon: ICON.person("#fff", 46), title: "The maker is paid", sub: "only after the scan" },
      ];
      const nodeEls = NODES.map((n) => {
        const g = h("div", { class: "abs", style: { left: n.x - 160 + "px", top: Y - 60 + "px", width: "320px", textAlign: "center" } });
        const tile = h("div", { style: { width: "120px", height: "120px", margin: "0 auto", borderRadius: "34px", background: "#cfc6b8", display: "grid", placeItems: "center", position: "relative" }, html: n.icon });
        const chk = h("div", { class: "abs", style: { right: "-10px", top: "-10px", width: "40px", height: "40px", borderRadius: "50%", background: "#fff", boxShadow: "var(--shadow-soft)", display: "grid", placeItems: "center", opacity: "0" }, html: ICON.check("#0e6e64", 24) });
        tile.appendChild(chk);
        const tt = h("div", { style: { marginTop: "20px", fontSize: "28px", fontWeight: "600", letterSpacing: "-0.01em" } }, n.title);
        const ss = h("div", { style: { marginTop: "6px", fontSize: "21px", color: "var(--muted)" } }, n.sub);
        g.append(tile, tt, ss);
        el.appendChild(g);
        return { g, tile, chk };
      });
      const lines = [0, 1].map((i) => {
        const x0 = NODES[i].x + 86;
        const x1 = NODES[i + 1].x - 86;
        const base = h("div", { class: "abs", style: { left: x0 + "px", top: Y - 1 + "px", width: x1 - x0 + "px", height: "0", borderTop: "3px dashed #d6cdbf" } });
        const fillL = h("div", { class: "abs", style: { left: x0 + "px", top: Y - 2 + "px", width: x1 - x0 + "px", height: "4px", borderRadius: "2px", background: "var(--teal)", transformOrigin: "0 50%" } });
        el.append(base, fillL);
        return { base, fillL, x0, x1 };
      });
      const coin = h("div", { class: "abs", style: { width: "54px", height: "54px", borderRadius: "50%", background: "#0e6e64", color: "#fff", display: "grid", placeItems: "center", fontSize: "28px", fontWeight: "700", boxShadow: "0 8px 22px rgba(14,110,100,0.35)" } }, "$");
      el.appendChild(coin);
      // first: the receipt photo, with a question mark
      const ph = h("div", { class: "abs", style: { left: "834px", top: "200px", width: "252px", height: "329px", borderRadius: "16px", overflow: "hidden", boxShadow: "var(--shadow-card)", background: "#5b4a3e", transformOrigin: "50% 50%" } });
      ph.appendChild(h("img", { src: "../assets/receipt-priya.jpg", style: { width: "252px", height: "329px", display: "block" } }));
      const q = h("div", { class: "abs", style: { left: "1046px", top: "170px", width: "76px", height: "76px", borderRadius: "50%", background: "#eda100", color: "#fff", fontSize: "46px", fontWeight: "700", display: "grid", placeItems: "center", boxShadow: "0 10px 24px rgba(237,161,0,0.35)" } }, "?");
      const phLab = h("div", { class: "abs", style: { left: "0", width: "1920px", top: "560px", textAlign: "center", fontSize: "30px", color: "var(--ink)", fontWeight: "500" } }, "A receipt photo can be faked");
      el.append(ph, q, phLab);
      scene({
        name: "next", t0: 155.6, t1: 161.5, el,
        update(t) {
          const out = prog(t, 160.95, 0.45, ease.inOutCubic);
          const fade = 1 - out;
          // the receipt photo and its question mark, until "so next"
          const [op, yp] = rise(t, 156.1, 0.6, 24);
          const gone = prog(t, 157.5, 0.5, ease.inOutCubic);
          show(ph, op * (1 - gone), 0, yp - 26 * gone, 1 - 0.06 * gone, { transform: `translate(0px, ${(yp - 26 * gone).toFixed(2)}px) rotate(-3deg) scale(${(1 - 0.06 * gone).toFixed(3)})` });
          const qp = prog(t, 156.7, 0.4, ease.outQuart);
          show(q, qp * (1 - gone), 0, (1 - qp) * 10 - 26 * gone, 0.7 + 0.3 * qp);
          const [ol, yl] = rise(t, 156.25, 0.5, 10);
          show(phLab, ol * (1 - gone), 0, yl - 26 * gone);
          // then: Next, and the courier's scan releasing the money
          const [on, yn] = rise(t, 157.7, 0.5, 14);
          show(nextPill, on * fade, 960 - nextPill.offsetWidth / 2, 214 + yn);
          const [oh, yh] = rise(t, 157.85, 0.6, 18);
          show(headline, oh * fade, 0, yh);
          nodeEls.forEach((n, i) => {
            const [o, y] = rise(t, 157.95 + i * 0.1, 0.6, 22);
            show(n.g, o * fade, 0, y);
          });
          lines.forEach((l) => {
            const o = prog(t, 158.0, 0.5) * fade;
            S(l.base, { opacity: o });
          });
          // node 1 is the hold (teal from the start), node 2 lights with the scan, node 3 when paid
          S(nodeEls[0].tile, { background: "#0e6e64" });
          const scan = prog(t, 158.45, 0.35, ease.outCubic);
          S(nodeEls[1].tile, { background: scan > 0.5 ? "#0e6e64" : "#cfc6b8" });
          S(nodeEls[1].tile, { transform: `scale(${(1 + 0.05 * Math.sin(Math.PI * clamp((t - 158.45) / 0.5))).toFixed(4)})` });
          const c2 = prog(t, 159.15, 0.35, ease.outQuart);
          S(nodeEls[1].chk, { opacity: c2, transform: `scale(${(0.6 + 0.4 * c2).toFixed(3)})` });
          const paid = prog(t, 160.35, 0.35, ease.outCubic);
          S(nodeEls[2].tile, { background: paid > 0.5 ? "#0e6e64" : "#cfc6b8" });
          S(nodeEls[2].chk, { opacity: prog(t, 160.4, 0.35, ease.outQuart) });
          // the money moves only after the scan
          const m1 = prog(t, 159.35, 0.55, ease.inOutCubic);
          const m2 = prog(t, 159.9, 0.5, ease.inOutCubic);
          S(lines[0].fillL, { transform: `scaleX(${m1.toFixed(4)})` });
          S(lines[1].fillL, { transform: `scaleX(${m2.toFixed(4)})` });
          const cx = t < 159.9 ? lerp(NODES[0].x, NODES[1].x, m1) : lerp(NODES[1].x, NODES[2].x, m2);
          const co = t >= 159.3 && t < 160.45 ? Math.min(prog(t, 159.3, 0.15), 1 - prog(t, 160.3, 0.15)) : 0;
          show(coin, co * fade, cx - 27, Y - 27 - 70);
        },
      });
    }

    // =====================================================================================================
    // 11. CLOSE  161.0 - 166.2: Claude talks. Code decides. PayPal pays on proof.
    // =====================================================================================================
    {
      const el = sceneEl("close");
      root.appendChild(el);
      const teal = h("div", { class: "abs", style: { inset: "0", background: "linear-gradient(160deg, #10786d 0%, #0e6e64 45%, #0a574f 100%)" } });
      el.appendChild(teal);
      const L = [
        ["Claude talks.", 161.38],
        ["Code decides.", 162.74],
        ["PayPal pays on proof.", 164.28],
      ];
      const ls = L.map(([s], i) => {
        const d = h("div", { class: "abs kinetic", style: { left: "0", width: "1920px", top: 300 + i * 150 + "px", textAlign: "center", color: "#fff", fontSize: "100px" } }, s);
        el.appendChild(d);
        return d;
      });
      scene({
        name: "close", t0: 161.0, t1: 166.25, el,
        update(t) {
          S(teal, { opacity: prog(t, 161.0, 0.5, ease.inOutSine) });
          const out = prog(t, 165.7, 0.4, ease.inOutCubic);
          S(el, { opacity: 1 - out });
          ls.forEach((d, i) => {
            const [o, y] = rise(t, L[i][1] - 0.04, 0.6, 30);
            show(d, o, 0, y);
          });
        },
      });
    }

    // =====================================================================================================
    // 12. END CARD  165.7 - end (silent)
    // =====================================================================================================
    {
      const el = sceneEl("end");
      root.appendChild(el);
      const logo = h("img", { class: "abs", src: "../assets/logo.svg", style: { left: "885px", top: "222px", width: "150px", height: "150px" } });
      const word = h("div", { class: "abs", style: { left: "0", width: "1920px", top: "404px", textAlign: "center", fontSize: "66px", letterSpacing: "-0.03em" } });
      word.innerHTML = `<span style="font-weight:600">OpenStall</span><span style="font-weight:400;color:var(--muted)"> Collective</span>`;
      const u1 = h("div", { class: "abs mono", style: { left: "0", width: "1920px", top: "530px", textAlign: "center", fontSize: "38px", color: "var(--teal-strong)", fontWeight: "500" } }, "openstall-collective.onrender.com");
      const u2 = h("div", { class: "abs mono", style: { left: "0", width: "1920px", top: "596px", textAlign: "center", fontSize: "32px", color: "var(--ink)" } }, "github.com/FahadRamxan/OpenStall-Collective");
      const hk = pill(`<span class="dot"></span><span>PayPal AI Hackathon 2026</span>`);
      hk.style.fontSize = "26px";
      el.append(logo, word, u1, u2, hk);
      scene({
        name: "end", t0: 165.7, t1: 999, el,
        update(t) {
          const items = [logo, word, u1, u2];
          items.forEach((d, i) => {
            const [o, y] = rise(t, 166.1 + i * 0.12, 0.7, 22);
            show(d, o, 0, y);
          });
          const [o, y] = rise(t, 166.6, 0.7, 16);
          show(hk, o, 960 - hk.offsetWidth / 2, 700 + y);
        },
      });
    }
  };
})();
