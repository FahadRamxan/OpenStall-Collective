// Reads src/data.js (written for the browser) in Node, and works out which clip frames the video needs.
import { readFileSync } from "node:fs";
import vm from "node:vm";

export const FPS = 60;

export function loadData() {
  const code = readFileSync(new URL("../src/data.js", import.meta.url), "utf8");
  const window = {};
  vm.runInNewContext(code, { window });
  return window;
}

function pwl(t, pts) {
  if (t <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) {
      const a = pts[i - 1];
      const b = pts[i];
      return a[1] + ((b[1] - a[1]) * (t - a[0])) / (b[0] - a[0]);
    }
  }
  return pts[pts.length - 1][1];
}

// { clip: Set(frameIndex) } for every frame of every shot (a little margin on each side).
export function neededFrames(data) {
  const need = {};
  for (const [id, s] of Object.entries(data.SHOTS)) {
    const meta = data.CLIPS[s.clip];
    if (!meta) throw new Error(`shot ${id}: unknown clip ${s.clip}`);
    const set = (need[s.clip] ||= new Set());
    const f0 = Math.floor(s.t0 * FPS) - 2;
    const f1 = Math.ceil(s.t1 * FPS) + 2;
    for (let f = f0; f <= f1; f++) {
      const src = pwl(f / FPS, s.map);
      const idx = Math.min(meta.frames - 1, Math.max(0, Math.round(src * FPS)));
      set.add(idx);
    }
  }
  return need;
}

// Contiguous ranges [a, b] covering a set of indices, joining gaps shorter than `join` frames.
export function ranges(set, join = 45) {
  const xs = [...set].sort((a, b) => a - b);
  const out = [];
  for (const x of xs) {
    const last = out[out.length - 1];
    if (last && x - last[1] <= join) last[1] = x;
    else out.push([x, x]);
  }
  return out;
}
