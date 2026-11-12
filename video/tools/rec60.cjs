// The video's screen clips, recorded at 60 fps: a headless Chromium on the GPU at a real 1.5x scale (1280 x 720 CSS
// pixels drawn as 1920 x 1080), its compositor frames taken with their timestamps through the DevTools screencast
// (about 100 a second), then laid on a constant 60 fps timeline by ffmpeg. Every move is eased: the cursor glides,
// the page scrolls on requestAnimationFrame. Test mode (http://localhost:3000) for the story; R9 on the hosted demo.
//
// Usage, from the repository's root with both test-mode servers running (video/README.md):
//   node video/tools/rec60.cjs [clip ...]   (default: every clip, in story order)
// Writes video/recordings/<clip>.mp4 and video/recordings/moments.json (when each step happens inside each clip).

const path = require("node:path");
const fs = require("node:fs");
const { execFileSync } = require("node:child_process");
const WEB_DIR = process.env.WEB_DIR || path.resolve(__dirname, "..", "..", "apps", "web");
const { chromium } = require(path.join(WEB_DIR, "node_modules", "playwright"));

const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const HOSTED = "https://openstall-collective.onrender.com";
const KIT = path.resolve(__dirname, "..");
const OUT = path.join(KIT, "recordings");
const FRAMES = path.join(__dirname, "frames");
const MIN = 60_000;
fs.mkdirSync(OUT, { recursive: true });

const CURSOR = () => {
  if (window.top !== window) return;
  const install = () => {
    if (document.getElementById("__rec_cursor")) return;
    const style = document.createElement("style");
    style.textContent = "::-webkit-scrollbar{display:none} html{scrollbar-width:none}";
    document.head.appendChild(style);
    const dot = document.createElement("div");
    dot.id = "__rec_cursor";
    Object.assign(dot.style, {
      position: "fixed", left: `${window.__recX ?? -60}px`, top: `${window.__recY ?? -60}px`, width: "26px",
      height: "26px", borderRadius: "50%", background: "rgba(14,110,100,0.18)", border: "2.5px solid #0e6e64",
      boxShadow: "0 2px 10px rgba(0,0,0,0.18)", zIndex: "2147483647", pointerEvents: "none",
      transform: "translate(-50%, -50%) scale(1)", transition: "transform .14s ease, background .14s ease",
    });
    document.documentElement.appendChild(dot);
    document.addEventListener("mousemove", (e) => {
      window.__recX = e.clientX; window.__recY = e.clientY;
      dot.style.left = `${e.clientX}px`; dot.style.top = `${e.clientY}px`;
    }, true);
    document.addEventListener("mousedown", () => {
      dot.style.transform = "translate(-50%, -50%) scale(0.72)"; dot.style.background = "rgba(14,110,100,0.45)";
    }, true);
    document.addEventListener("mouseup", () => {
      dot.style.transform = "translate(-50%, -50%) scale(1)"; dot.style.background = "rgba(14,110,100,0.18)";
    }, true);
  };
  if (document.readyState === "complete") setTimeout(install, 300);
  else window.addEventListener("load", () => setTimeout(install, 300));
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

let page, cdp, mouse = { x: 640, y: 360 };
let clip = null; // { name, dir, frames: [[file, ts]], start, moments: [] }
const allMoments = fs.existsSync(path.join(OUT, "moments.json"))
  ? JSON.parse(fs.readFileSync(path.join(OUT, "moments.json"), "utf8")) : {};

function moment(label) {
  if (!clip) return;
  const t = (Date.now() - clip.start) / 1000;
  clip.moments.push({ t: Number(t.toFixed(2)), label });
  console.log(`  ${t.toFixed(1)}s  ${label}`);
}

async function startClip(name) {
  const dir = path.join(FRAMES, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  clip = { name, dir, frames: [], start: Date.now(), moments: [], writes: [] };
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  await page.mouse.move(mouse.x + 1, mouse.y);  // a first frame
  await page.mouse.move(mouse.x, mouse.y);
  console.log(`\n== ${name}`);
}

async function stopClip() {
  const done = clip;
  await sleep(150);
  await cdp.send("Page.stopScreencast");
  clip = null;
  await Promise.all(done.writes);
  const end = Date.now() / 1000;
  const frames = done.frames.filter(([, ts]) => ts * 1000 >= done.start - 50);
  const lines = [];
  frames.forEach(([file, ts], i) => {
    const next = i + 1 < frames.length ? frames[i + 1][1] : end;
    lines.push(`file '${file.replace(/\\/g, "/")}'`, `duration ${Math.max(0.001, next - ts).toFixed(6)}`);
  });
  lines.push(`file '${frames.at(-1)[0].replace(/\\/g, "/")}'`);
  const list = path.join(done.dir, "list.txt");
  fs.writeFileSync(list, lines.join("\n"));
  const out = path.join(OUT, `${done.name}.mp4`);
  execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list,
    "-vf", "fps=60,scale=1920:1080:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "15",
    "-profile:v", "high", "-movflags", "+faststart", out]);
  const seconds = end - done.start / 1000;
  console.log(`  -> ${path.basename(out)}: ${seconds.toFixed(1)}s, ${frames.length} frames captured (${(frames.length / seconds).toFixed(0)}/s)`);
  allMoments[done.name] = { seconds: Number(seconds.toFixed(2)), moments: done.moments };
  fs.writeFileSync(path.join(OUT, "moments.json"), JSON.stringify(allMoments, null, 2));
  fs.rmSync(done.dir, { recursive: true, force: true });
}

async function cursorShown(on) {
  await page.evaluate((visible) => {
    const dot = document.getElementById("__rec_cursor");
    if (!dot) return;
    dot.style.transition = "opacity .3s ease, transform .14s ease, background .14s ease";
    dot.style.opacity = visible ? "1" : "0";
  }, on).catch(() => {});
}

async function glideTo(x, y, ms = 650) {
  await cursorShown(true);
  const from = { ...mouse };
  const steps = Math.max(8, Math.round(ms / 16));
  for (let i = 1; i <= steps; i += 1) {
    const t = ease(i / steps);
    await page.mouse.move(from.x + (x - from.x) * t, from.y + (y - from.y) * t);
    await sleep(14);
  }
  mouse = { x, y };
}

async function glide(locator, ms) {
  await locator.waitFor({ state: "visible", timeout: 45_000 });
  let box = await locator.boundingBox();
  if (!box) return;
  if (box.y < 120 || box.y + box.height > 690) {
    // Under the header or below the fold: bring it into view first, with an eased scroll.
    const top = await locator.evaluate((el) => el.getBoundingClientRect().top + scrollY);
    await scrollY(top - 330, 1300);
    box = await locator.boundingBox();
  }
  await glideTo(box.x + box.width / 2, box.y + box.height / 2, ms);
}

async function press(locator, ms = 700) {
  await glide(locator, ms);
  await sleep(250);
  await page.mouse.down();
  await sleep(90);
  await page.mouse.up();
  await sleep(350);
}

async function rest(ms = 700) {
  // Out of the way, where nothing lights up under it, then fade it out until the next move.
  await glideTo(1250, 430, ms);
  await cursorShown(false);
}

async function scrollY(to, ms = 1500) {
  await page.evaluate(([target, duration]) => new Promise((resolve) => {
    // The site scrolls smoothly (scroll-behavior: smooth), which would restart on every frame of this easing:
    // turn it off while this animation runs, so each frame lands exactly where it is put.
    const root = document.documentElement;
    const before = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    const from = scrollY, start = performance.now();
    const max = root.scrollHeight - innerHeight;
    const goal = Math.max(0, Math.min(max, target));
    const e = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      scrollTo({ top: from + (goal - from) * e(t), behavior: "instant" });
      if (t < 1) requestAnimationFrame(step);
      else { root.style.scrollBehavior = before; resolve(); }
    };
    requestAnimationFrame(step);
  }), [to, ms]);
  await sleep(120);
}

async function scrollToEl(locator, offset = 150, ms = 1500) {
  await locator.waitFor({ state: "attached", timeout: 45_000 });
  const top = await locator.evaluate((el) => el.getBoundingClientRect().top + scrollY);
  await scrollY(top - offset, ms);
}

async function scrollBy(dy, ms = 1500) {
  const now = await page.evaluate(() => scrollY);
  await scrollY(now + dy, ms);
}

async function goto(url) {
  await page.goto(url, { waitUntil: "networkidle" });
  await sleep(500);
}

const hold = sleep;

const clips = {
  async "R1-home"() {
    await goto(WEB + "/");
    await startClip("R1-home");
    await hold(1800);
    await glide(page.getByRole("link", { name: "See the live demo" }), 1100);
    moment("hover See the live demo");
    await hold(1500);
    await scrollBy(560, 2600);
    await hold(1600);
    const how = page.getByRole("heading", { name: /How it works/i }).first();
    if (await how.count()) await scrollToEl(how, 90, 2200);
    moment("How it works");
    await hold(2600);
    await stopClip();
  },

  async "R2-run"() {
    await fetch(API + "/api/demo/reset", { method: "POST" });
    await goto(WEB + "/demo");
    await startClip("R2-run");
    await hold(1600);
    const controls = page.locator('section[aria-labelledby="controls-heading"]');
    await press(controls.getByRole("button", { name: "Run the demo request" }), 1000);
    await rest();
    moment("Run the demo request pressed");
    await controls.getByRole("link", { name: "Open its approval page" }).waitFor({ timeout: 60_000 });
    moment("approval link ready");
    await hold(1800);
    for (const [id, wait] of [["request", 2600], ["rules", 2200], ["offers", 4200], ["allocation", 4600], ["order", 2400]]) {
      await scrollToEl(page.locator(`#${id}-heading`), 150, 1700);
      moment(`section ${id}`);
      await hold(wait);
    }
    await stopClip();
  },

  async "R3-approve"() {
    const controls = page.locator('section[aria-labelledby="controls-heading"]');
    await scrollToEl(controls, 96, 10);
    await startClip("R3-approve");
    await hold(900);
    await press(controls.getByRole("link", { name: "Open its approval page" }), 900);
    await rest();
    await page.waitForURL(/\/approve\/[^/]+$/, { timeout: MIN });
    await page.getByRole("button", { name: "Approve and pay with PayPal" }).waitFor({ timeout: MIN });
    moment("approval page");
    await hold(2200);
    await scrollBy(520, 2400);
    moment("split and pay-on-proof explained");
    await hold(2600);
    await press(page.getByRole("button", { name: "Approve and pay with PayPal" }), 1000);
    await rest();
    await page.waitForURL(/fake-paypal/, { timeout: MIN });
    await page.getByRole("button", { name: "Approve", exact: true }).waitFor({ timeout: MIN });
    moment("simulated PayPal page");
    await hold(2000);
    await press(page.getByRole("button", { name: "Approve", exact: true }), 900);
    await rest();
    await page.getByRole("heading", { level: 1, name: /is holding \$815\.00/ }).waitFor({ timeout: MIN });
    moment("PayPal is holding $815.00");
    await hold(1500);
    await page.getByText("Each maker has been told about her share").waitFor({ timeout: MIN }).catch(() => {});
    moment("each maker told");
    await hold(1800);
    await scrollBy(560, 2600);
    await hold(2200);
    await stopClip();
  },

  async "R4-phones"() {
    await startClip("R4-phones");
    await hold(700);
    await press(page.getByRole("link", { name: "Watch it happen on the live demo" }), 900);
    await rest();
    await page.waitForURL(/\/demo/, { timeout: MIN });
    await sleep(1200);
    await scrollToEl(page.locator("#payments-heading"), 150, 1800);
    moment("Payments: reserved, makers told");
    await hold(3000);
    await scrollToEl(page.locator("#phones-heading"), 150, 1800);
    moment("the makers' phones");
    await hold(3200);
    await scrollBy(420, 2200);
    await hold(3000);
    await stopClip();
  },

  async "R5-proof"() {
    await scrollToEl(page.locator("#phones-heading"), 150, 10);
    await startClip("R5-proof");
    await hold(800);
    const send = page.getByRole("button", { name: "Send Priya's courier receipt" });
    await scrollToEl(send, 360, 1400);
    await press(send, 1000);
    await rest();
    moment("Priya sends her courier receipt");
    await page.getByText("EE123456789IN").first().waitFor({ timeout: MIN });
    moment("receipt read: India Post EE123456789IN");
    await hold(2600);
    await press(page.getByRole("button", { name: /Reply .+ as Priya/ }), 1000);
    await rest();
    moment("Priya replies yes");
    await page.getByText(/भुगतान हो गया/).first().waitFor({ timeout: MIN }).catch(() => {});
    moment("Priya is paid");
    await hold(2600);
    await scrollToEl(page.locator("#payments-heading"), 150, 1900);
    moment("Payments: paid on proof, tracking on PayPal");
    await hold(4200);
    await stopClip();
  },

  async "R6-heal"() {
    await scrollToEl(page.locator("#phones-heading"), 150, 10);
    await startClip("R6-heal");
    await hold(800);
    const drop = page.getByRole("button", { name: "Grace can't make it" });
    await scrollToEl(drop, 360, 1400);
    await press(drop, 1000);
    await rest();
    moment("Grace can't make it");
    await page.getByRole("button", { name: /Reply .+ as Grace/ }).waitFor({ timeout: MIN });
    await hold(2400);
    await press(page.getByRole("button", { name: /Reply .+ as Grace/ }), 1000);
    await rest();
    moment("Grace confirms");
    await hold(1800);
    await scrollToEl(page.locator("#payments-heading"), 150, 1900);
    await page.getByText("The order heals itself").first().waitFor({ timeout: MIN }).catch(() => {});
    moment("The order heals itself");
    await hold(1600);
    const heal = page.getByText("The order heals itself").first();
    if (await heal.count()) await scrollToEl(heal, 220, 1500);
    await hold(3600);
    await stopClip();
  },

  async "R7-attacks"() {
    await startClip("R7-attacks");
    await hold(600);
    await scrollToEl(page.locator("#guardrails-heading"), 150, 1900);
    await hold(1400);
    const panel = page.locator("section", { has: page.getByRole("button", { name: "Try every attack" }) }).first();
    await press(panel.getByRole("button", { name: "Try every attack" }), 1000);
    await rest();
    moment("Try every attack");
    await panel.getByText(/10 of 10 attacks refused/).waitFor({ timeout: 60_000 });
    moment("10 of 10 attacks refused");
    await hold(2000);
    await scrollBy(700, 3600);
    await hold(2400);
    await stopClip();
  },

  async "R8-tamper"() {
    await startClip("R8-tamper");
    await hold(600);
    await scrollToEl(page.locator("#tamper-heading"), 150, 1900);
    const form = page.locator('form[aria-label$="trust card"]').first();
    await scrollToEl(form, 200, 1200);
    await hold(1800);
    const rate = form.getByLabel("On-time rate");
    await glide(rate, 900);
    await rate.click({ clickCount: 3 });
    await sleep(200);
    await rate.pressSequentially("0.99", { delay: 140 });
    moment("on-time rate changed to 0.99");
    await hold(1000);
    await press(form.getByRole("button", { name: "Check the signature" }), 900);
    await rest();
    await page.getByText(/does not match/).first().waitFor({ timeout: MIN });
    moment("signature does not match");
    await hold(3200);
    await press(form.getByRole("button", { name: "Put it back" }), 900);
    await rest();
    await page.getByText(/Signature valid/).first().waitFor({ timeout: MIN }).catch(() => {});
    moment("put back: signature valid");
    await hold(2800);
    await stopClip();
  },

  async "R9-status-hosted"() {
    await goto(HOSTED + "/status");
    await page.getByText(/PayPal doctor/i).first().waitFor({ timeout: 45_000 }).catch(() => {});
    await startClip("R9-status-hosted");
    await hold(2000);
    const doctor = page.getByRole("heading", { name: /PayPal doctor/i }).first();
    if (await doctor.count()) await scrollToEl(doctor, 96, 2200);
    moment("PayPal doctor (hosted, PayPal sandbox)");
    await hold(3600);
    await scrollBy(600, 2600);
    moment("APIMatic cross-check");
    await hold(3200);
    const products = page.getByRole("heading", { name: /PayPal products/i }).first();
    if (await products.count()) await scrollToEl(products, 96, 2200);
    moment("PayPal products");
    await hold(3200);
    await stopClip();
  },

  async "R10-dashboard"() {
    await goto(WEB + "/dashboard");
    await startClip("R10-dashboard");
    await hold(2200);
    moment("Demand Radar tip");
    for (let i = 0; i < 3; i += 1) {
      await scrollBy(560, 2400);
      await hold(2200);
    }
    await stopClip();
  },

  async "R11-seller-chat"() {
    await goto(WEB + "/seller-chat?seller=s_priya");
    await startClip("R11-seller-chat");
    await hold(2200);
    moment("Priya's chat, Hindi with English under it");
    await scrollBy(360, 2200);
    await hold(3200);
    await stopClip();
  },

  // The buyer's receipt once the story has run (replay_story.py): Priya and Amina paid on proof, Lucía reserved,
  // Grace released, the top-up, and the one authorization at the bottom.
  async "R12-receipt"() {
    const order = fs.readFileSync(path.join(__dirname, "receipt-order.txt"), "utf8").trim();
    await goto(`${WEB}/approve/${order}/return`);
    await page.getByRole("heading", { level: 1, name: /is holding/ }).waitFor({ timeout: 45_000 });
    await startClip("R12-receipt");
    await hold(2400);
    moment("PayPal holds $815.00; every share confirmed; each maker told");
    await scrollToEl(page.getByRole("heading", { name: "Your receipt" }), 120, 2200);
    moment("Priya: paid on proof of shipping, India Post tracking, her courier receipt, tracking on PayPal");
    await hold(2200);
    const receiptLink = page.getByRole("link", { name: "See her courier receipt" }).first();
    await glide(receiptLink, 1000);
    await hold(1800);
    await rest();
    const amina = page.getByText("Paid to her bank through Hyperwallet (simulated)").first();
    await scrollToEl(amina, 260, 2000);
    moment("Amina: paid to her bank through Hyperwallet (simulated), TCS tracking");
    await hold(3000);
    const released = page.getByText("Released back to you").first();
    await scrollToEl(released, 420, 2200);
    moment("Lucía reserved, paid when she ships; Grace released back to you");
    await hold(3000);
    const heal = page.getByText("The order heals itself").first();
    await scrollToEl(heal, 200, 1800);
    moment("The order heals itself: Priya's top-up, 7 for $112.00");
    await hold(2600);
    const total = page.getByText(/One PayPal authorization for \$815\.00/).first();
    await scrollToEl(total, 420, 1800);
    moment("One PayPal authorization for $815.00; each share captured when she ships");
    await hold(3000);
    await stopClip();
  },
};

const ORDER = Object.keys(clips);

(async () => {
  const wanted = process.argv.slice(2).length ? process.argv.slice(2) : ORDER;
  const browser = await chromium.launch({
    headless: true, channel: "chromium",
    args: ["--hide-scrollbars", "--force-color-profile=srgb", "--force-device-scale-factor=1.5", "--window-size=1400,900",
      "--use-angle=d3d11", "--enable-gpu-rasterization", "--ignore-gpu-blocklist", "--enable-zero-copy"],
  });
  const context = await browser.newContext({ viewport: null, colorScheme: "light", locale: "en-US" });
  await context.addInitScript(CURSOR);
  page = await context.newPage();
  cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 720, deviceScaleFactor: 0, mobile: false });
  cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
    if (!clip) return;
    const file = path.join(clip.dir, `f${String(clip.frames.length).padStart(6, "0")}.jpg`);
    clip.frames.push([file, metadata.timestamp]);
    clip.writes.push(fs.promises.writeFile(file, Buffer.from(data, "base64")));
  });
  // A clip that needs an earlier one is skipped when that one failed, instead of recording idle minutes.
  const NEEDS = { "R3-approve": "R2-run", "R4-phones": "R3-approve", "R5-proof": "R4-phones", "R6-heal": "R5-proof" };
  const failed = new Set();
  for (const name of ORDER.filter((n) => wanted.includes(n))) {
    if (NEEDS[name] && failed.has(NEEDS[name])) {
      console.log(`  -- ${name} skipped: ${NEEDS[name]} failed`);
      failed.add(name);
      continue;
    }
    try {
      await clips[name]();
    } catch (error) {
      failed.add(name);
      console.log(`  !! ${name} failed: ${String(error.message || error).split("\n")[0]}`);
      if (clip) {
        await cdp.send("Page.stopScreencast").catch(() => {});
        clip = null;
      }
    }
  }
  await browser.close();
})();
