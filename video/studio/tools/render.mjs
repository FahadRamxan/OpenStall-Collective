// Renders the video: opens index.html?render=1 in headless Chromium, shows each frame at its exact time (60 fps),
// screenshots it, and encodes with ffmpeg (H.264 High, 1920x1080, BT.709). Then adds the audio from make-audio.
//
//   node tools/render.mjs                    whole video -> out/OpenStall-Collective-demo.mp4
//   node tools/render.mjs --from 60 --to 95  a part (for checking) -> out/part-60-95.mp4
//   node tools/render.mjs --snap 3.5,40,77   PNG stills -> out/snaps/
//   options: --workers 6  --crf 16  --preset slow
import { chromium } from "playwright-core";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdirSync, writeFileSync, rmSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { startServer } from "./serve.mjs";
import { loadData, FPS } from "./shots.mjs";

const OUT = fileURLToPath(new URL("../out/", import.meta.url));
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf("--" + name);
  return i >= 0 ? argv[i + 1] : dflt;
};
const data = loadData();
const DURATION = data.VIDEO.duration;
const WORKERS = Number(opt("workers", 6));
const CRF = String(opt("crf", 16));
const PRESET = String(opt("preset", "slow"));
const PORT = 5179 + Math.floor(Math.random() * 400);
mkdirSync(OUT, { recursive: true });

function run(cmd, args) {
  return new Promise((ok, fail) => {
    const p = spawn(cmd, args, { stdio: ["ignore", "inherit", "inherit"] });
    p.on("exit", (c) => (c === 0 ? ok() : fail(new Error(`${cmd} exited ${c}`))));
  });
}

async function openPage(browser) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.error("page error:", e.message));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") console.error("page:", m.text());
  });
  await page.goto(`http://127.0.0.1:${PORT}/studio/?render=1`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__ready || window.__error, null, { timeout: 120000 });
  const err = await page.evaluate(() => window.__error);
  if (err) throw new Error(err);
  const cdp = await page.context().newCDPSession(page);
  const shot = async (t, format = "png") => {
    await page.evaluate((x) => window.__seek(x), t);
    const { data: b64 } = await cdp.send("Page.captureScreenshot", { format, optimizeForSpeed: true });
    return Buffer.from(b64, "base64");
  };
  return { page, shot };
}

const server = await startServer(PORT);
const browser = await chromium.launch({
  args: ["--force-color-profile=srgb", "--hide-scrollbars", "--disable-lcd-text", "--autoplay-policy=no-user-gesture-required"],
});

try {
  const snap = opt("snap", null);
  if (snap) {
    mkdirSync(OUT + "snaps", { recursive: true });
    const { shot } = await openPage(browser);
    for (const s of snap.split(",")) {
      const t = Number(s);
      const buf = await shot(t);
      const f = `${OUT}snaps/t${t.toFixed(2).padStart(7, "0")}.png`;
      writeFileSync(f, buf);
      console.log("wrote", f);
    }
  } else {
    const from = Number(opt("from", 0));
    const to = Math.min(DURATION, Number(opt("to", DURATION)));
    const f0 = Math.round(from * FPS);
    const f1 = Math.round(to * FPS);
    const whole = from === 0 && to === DURATION;
    const name = whole ? "OpenStall-Collective-demo" : `part-${from}-${to}`;
    const segDir = OUT + "segments/";
    rmSync(segDir, { recursive: true, force: true });
    mkdirSync(segDir, { recursive: true });
    const n = f1 - f0;
    const per = Math.ceil(n / WORKERS);
    let done = 0;
    const started = Date.now();
    const tick = setInterval(() => {
      const el = (Date.now() - started) / 1000;
      const fps = done / el;
      process.stdout.write(`\r${done}/${n} frames  ${fps.toFixed(1)} fps  eta ${((n - done) / Math.max(fps, 0.01) / 60).toFixed(1)} min   `);
    }, 2000);
    const jobs = [];
    for (let w = 0; w < WORKERS; w++) {
      const a = f0 + w * per;
      const b = Math.min(f1, a + per);
      if (a >= b) break;
      jobs.push(
        (async () => {
          const { page, shot } = await openPage(browser);
          const seg = `${segDir}seg${String(w).padStart(2, "0")}.mp4`;
          const ff = spawn(
            "ffmpeg",
            [
              "-v", "error", "-y",
              "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-",
              "-vf", "scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=bicubic,format=yuv420p",
              "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-profile:v", "high", "-level:v", "4.2",
              "-g", "120", "-keyint_min", "120", "-sc_threshold", "0",
              "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
              "-r", String(FPS), seg,
            ],
            { stdio: ["pipe", "inherit", "inherit"] },
          );
          for (let f = a; f < b; f++) {
            const buf = await shot(f / FPS, "png");
            if (!ff.stdin.write(buf)) await once(ff.stdin, "drain");
            done++;
          }
          ff.stdin.end();
          const [code] = await once(ff, "exit");
          if (code !== 0) throw new Error(`ffmpeg segment ${w} failed`);
          await page.close();
          return seg;
        })(),
      );
    }
    const segs = await Promise.all(jobs);
    clearInterval(tick);
    console.log(`\nrendered ${n} frames in ${((Date.now() - started) / 60000).toFixed(1)} min`);
    const list = segDir + "list.txt";
    writeFileSync(list, segs.map((s) => `file '${s.replace(/\\/g, "/")}'`).join("\n"));
    const silent = OUT + name + ".video.mp4";
    // join the segments; write BT.709 colour tags into the stream itself so every player reads the colours right
    await run("ffmpeg", [
      "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy",
      "-bsf:v", "h264_metadata=video_full_range_flag=0:colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
      silent,
    ]);
    // audio: out/audio.wav from make-audio.mjs (the narration from 0:00, with the UI sounds); rebuilt unless
    // --keep-audio (use that after make-audio.mjs --music …)
    const wav = OUT + "audio.wav";
    if (!argv.includes("--keep-audio") || !existsSync(wav)) {
      await run(process.execPath, [fileURLToPath(new URL("./make-audio.mjs", import.meta.url))]);
    }
    const final = OUT + name + ".mp4";
    await run("ffmpeg", [
      "-v", "error", "-y",
      "-i", silent,
      "-ss", from.toFixed(3), "-t", (to - from).toFixed(3), "-i", wav,
      "-map", "0:v:0", "-map", "1:a:0",
      "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
      // a 1/60 s track timescale puts every frame exactly 1/60 s apart (no rounding at the segment joins)
      "-video_track_timescale", String(FPS),
      "-movflags", "+faststart", "-shortest",
      final,
    ]);
    rmSync(silent);
    console.log(`wrote ${final} (${(statSync(final).size / 1e6).toFixed(1)} MB)`);
  }
} finally {
  await browser.close();
  server.close();
}
