// Puts a new soundtrack on the finished video without re-rendering a single frame: rebuilds out/audio.wav
// (make-audio.mjs, same options) and muxes it with the video stream of out/OpenStall-Collective-demo.mp4.
//
//   node tools/mux-audio.mjs                    narration + UI sounds + music/openstall-bed.wav
//   node tools/mux-audio.mjs --no-music         (any make-audio.mjs option passes through)
import { spawnSync } from "node:child_process";
import { existsSync, renameSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const OUT = fileURLToPath(new URL("../out/", import.meta.url));
const video = OUT + "OpenStall-Collective-demo.mp4";
if (!existsSync(video)) throw new Error("render the video first: node tools/render.mjs");
const run = (cmd, args) => {
  const r = spawnSync(cmd, args, { stdio: "inherit" });
  if (r.status !== 0) throw new Error(`${cmd} failed`);
};
run(process.execPath, [fileURLToPath(new URL("./make-audio.mjs", import.meta.url)), ...process.argv.slice(2)]);
const tmp = OUT + "OpenStall-Collective-demo.tmp.mp4";
run("ffmpeg", [
  "-v", "error", "-y",
  "-i", video, "-i", OUT + "audio.wav",
  "-map", "0:v:0", "-map", "1:a:0",
  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
  "-video_track_timescale", "60", "-movflags", "+faststart", "-shortest",
  tmp,
]);
renameSync(tmp, video);
console.log(`wrote ${video} (${(statSync(video).size / 1e6).toFixed(1)} MB)`);
