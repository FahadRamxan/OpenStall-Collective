// Pulls the screen-recording frames the video needs out of recordings/*.mp4, as JPEGs in cache/frames/<clip>/.
// The renderer shows these one by one, so every output frame shows exactly the source frame it should.
// Run: node tools/extract-frames.mjs   (skips frames already there; delete cache/ to start over)
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { loadData, neededFrames, ranges, FPS } from "./shots.mjs";

const KIT = fileURLToPath(new URL("../..", import.meta.url));
const CACHE = fileURLToPath(new URL("../cache/frames/", import.meta.url));
const pad = (n) => String(n).padStart(5, "0");

const data = loadData();
const need = neededFrames(data);
let total = 0;
for (const [clip, set] of Object.entries(need)) {
  const dir = CACHE + clip + "/";
  mkdirSync(dir, { recursive: true });
  for (const [a, b] of ranges(set)) {
    let missing = false;
    for (let i = a; i <= b; i++) if (!existsSync(dir + pad(i) + ".jpg")) { missing = true; break; }
    total += b - a + 1;
    if (!missing) continue;
    const file = KIT + "recordings/" + data.CLIPS[clip].file;
    // seek a little before the range (fast input seek), then select exact frames by timestamp
    const ss = Math.max(0, a / FPS - 2);
    const args = [
      "-v", "error", "-y",
      "-ss", ss.toFixed(3), "-i", file,
      "-vf", `select='between(n\\,${Math.round(a - ss * FPS)}\\,${Math.round(b - ss * FPS)})'`,
      "-fps_mode", "passthrough",
      "-q:v", "2",
      "-start_number", String(a),
      dir + "%05d.jpg",
    ];
    process.stdout.write(`${clip}: frames ${a}-${b} (${((b - a + 1) / FPS).toFixed(1)} s)… `);
    const r = spawnSync("ffmpeg", args, { stdio: ["ignore", "inherit", "inherit"] });
    if (r.status !== 0) throw new Error(`ffmpeg failed on ${clip}`);
    for (let i = a; i <= b; i++) if (!existsSync(dir + pad(i) + ".jpg")) throw new Error(`${clip}: frame ${i} missing after extract`);
    console.log("done");
  }
}
console.log(`clip frames ready: ${total}`);
