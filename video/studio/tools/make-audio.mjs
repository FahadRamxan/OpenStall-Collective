// Builds out/audio.wav: narration-draft.mp3 from 0:00 (the master track), plus quiet UI sounds where the phones show
// a message, a tap or a camera shutter, plus soft music well under the voice. Length = the whole video.
//
//   node tools/make-audio.mjs                       narration + UI sounds + music/openstall-bed.wav (if it exists)
//   node tools/make-audio.mjs --music song.mp3      a different (royalty-free) track instead
//   node tools/make-audio.mjs --no-music            no music
//   node tools/make-audio.mjs --no-sfx              no UI sounds
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { loadData } from "./shots.mjs";

const KIT = fileURLToPath(new URL("../..", import.meta.url));
const OUT = fileURLToPath(new URL("../out/", import.meta.url));
mkdirSync(OUT, { recursive: true });
const argv = process.argv.slice(2);
const opt = (n) => {
  const i = argv.indexOf("--" + n);
  return i >= 0 ? argv[i + 1] : null;
};
const SR = 48000;
const data = loadData();
const N = Math.round(data.VIDEO.duration * SR);

// Levels. The narration is mono at -14.4 LUFS (peak -0.9 dBFS); the same signal on both channels reads 3 dB louder,
// so -2.6 dB lands the mix at about -14 LUFS (YouTube's reference) with peaks near -3.5 dBFS.
const VOICE_GAIN = Math.pow(10, -2.6 / 20);
const SFX_GAIN = 1.0; // the sounds below are already quiet (peaks about -24 dBFS, some 20 dB under the voice)
// Music: set to -24 LUFS on its own (10 dB under the voice, heard in the longer pauses) and ducked 6 dB more while
// she speaks (about 17 dB under the voice). Short pauses between sentences don't bring it up, so it never pumps.
const MUSIC_LUFS = -24;
const DUCK_DB = 6;

function decode(file, channels) {
  const r = spawnSync("ffmpeg", ["-v", "error", "-i", file, "-f", "f32le", "-ac", String(channels), "-ar", String(SR), "-"], { maxBuffer: 1 << 30 });
  if (r.status !== 0) throw new Error("ffmpeg could not read " + file);
  const b = r.stdout;
  return new Float32Array(b.buffer, b.byteOffset, b.length / 4);
}

const L = new Float32Array(N);
const R = new Float32Array(N);

// ---- narration from 0:00 ----
const voice = decode(KIT + "narration-draft.mp3", 1);
const vn = Math.min(N, voice.length);
for (let i = 0; i < vn; i++) {
  L[i] += voice[i] * VOICE_GAIN;
  R[i] += voice[i] * VOICE_GAIN;
}

// ---- UI sounds ----
let seed = 7;
const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647) * 2 - 1;
function synth(kind) {
  const dur = { in: 0.22, out: 0.16, tap: 0.06, shutter: 0.16, chime: 0.9 }[kind];
  const n = Math.round(dur * SR);
  const s = new Float32Array(n);
  let ph = 0;
  let ph2 = 0;
  let lp = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    if (kind === "in") {
      // a soft, round pop: a short rising tone
      const f = 540 + 300 * (1 - Math.exp(-t / 0.018));
      ph += (2 * Math.PI * f) / SR;
      const env = (t < 0.004 ? t / 0.004 : 1) * Math.exp(-t / 0.05);
      s[i] = 0.06 * env * (Math.sin(ph) + 0.18 * Math.sin(2 * ph));
    } else if (kind === "out") {
      // sent: lighter and higher
      const f = 980 + 280 * (1 - Math.exp(-t / 0.012));
      ph += (2 * Math.PI * f) / SR;
      const env = (t < 0.003 ? t / 0.003 : 1) * Math.exp(-t / 0.035);
      s[i] = 0.04 * env * Math.sin(ph);
    } else if (kind === "tap") {
      lp += 0.35 * (rnd() - lp);
      ph += (2 * Math.PI * 1700) / SR;
      s[i] = 0.05 * Math.exp(-t / 0.006) * lp + 0.028 * Math.exp(-t / 0.012) * Math.sin(ph);
    } else if (kind === "shutter") {
      const click = (t0) => (t >= t0 ? Math.exp(-(t - t0) / 0.01) : 0);
      lp += 0.5 * (rnd() - lp);
      s[i] = 0.06 * (click(0) + 0.8 * click(0.065)) * lp;
    } else if (kind === "chime") {
      // paid: a gentle major third, D and F# (in the music's key, D major)
      ph += (2 * Math.PI * 1174.66) / SR;
      ph2 += (2 * Math.PI * 1479.98) / SR;
      const e1 = (t < 0.006 ? t / 0.006 : 1) * Math.exp(-t / 0.32);
      const e2 = t < 0.09 ? 0 : (t < 0.096 ? (t - 0.09) / 0.006 : 1) * Math.exp(-(t - 0.09) / 0.34);
      s[i] = 0.03 * e1 * Math.sin(ph) + 0.03 * e2 * Math.sin(ph2);
    }
  }
  return s;
}
const bank = {};
const events = [];
if (!argv.includes("--no-sfx")) {
  const real = JSON.parse(readFileSync(KIT + "whatsapp-real-chat.json", "utf8"));
  const scripts = JSON.parse(readFileSync(KIT + "whatsapp-scripts.json", "utf8"));
  const pick = (p) => scripts[Object.keys(scripts).find((k) => k.startsWith(p))];
  const SRC = { real, A2: pick("A2"), A3: pick("A3"), A4: pick("A4"), A5: pick("A5") };
  for (const [key, def] of Object.entries(data.CHATS)) {
    const four = key.endsWith("4") || key === "lucia";
    for (const ev of def.events) {
      if (!ev.at) continue;
      const from = SRC[def.source][ev.msg].from;
      events.push({ t: ev.at, kind: from === "OpenStall" ? "in" : "out", gain: four ? 0.6 : 1 });
      if (ev.tap != null) events.push({ t: ev.tap, kind: "tap", gain: 1 });
      if (ev.flash != null) events.push({ t: ev.flash, kind: "shutter", gain: 1 });
    }
  }
  for (const x of data.SFX_EXTRA || []) events.push({ ...x, gain: 1 });
  events.sort((a, b) => a.t - b.t);
  for (const e of events) {
    const s = (bank[e.kind] ||= synth(e.kind));
    const at = Math.round(e.t * SR);
    for (let i = 0; i < s.length && at + i < N; i++) {
      const v = s[i] * SFX_GAIN * e.gain;
      L[at + i] += v;
      R[at + i] += v;
    }
  }
}

// ---- music, ducked under the voice ----
const BED = fileURLToPath(new URL("../music/openstall-bed.wav", import.meta.url));
const musicFile = argv.includes("--no-music") ? null : opt("music") || (existsSync(BED) ? BED : null);
let musicNote = "";
if (musicFile) {
  // loudness of the track on its own, so any track lands at the same level
  const meas = spawnSync("ffmpeg", ["-hide_banner", "-i", musicFile, "-af", "ebur128", "-f", "null", "-"], { encoding: "utf8" });
  const mI = /I:\s+(-?[\d.]+) LUFS/.exec(meas.stderr.split("Summary:").pop());
  if (!mI) throw new Error("could not measure the music's loudness");
  const base = Math.pow(10, (MUSIC_LUFS - Number(mI[1])) / 20);
  const m = decode(musicFile, 2);
  const mn = m.length / 2;
  // how much she is speaking: fast to duck (120 ms), back up only after about 0.8 s of quiet, then smoothed (300 ms)
  const duck = Math.pow(10, -DUCK_DB / 20);
  const kA = 1 - Math.exp(-1 / (0.12 * SR));
  const kR = 1 - Math.exp(-1 / (0.8 * SR));
  const kS = 1 - Math.exp(-1 / (0.3 * SR));
  let e = 0;
  let g = base;
  const fadeIn = 2 * SR;
  const endAt = Math.round(data.VIDEO.endCard * SR);
  for (let i = 0; i < N; i++) {
    const v = i < vn ? Math.abs(voice[i]) : 0;
    e += (v > e ? kA : kR) * (v - e);
    const speaking = Math.min(1, e / 0.06);
    g += kS * (base * (1 - (1 - duck) * speaking) - g);
    let gi = g;
    if (i < fadeIn) gi *= i / fadeIn;
    if (i > endAt - SR) gi *= Math.max(0, (endAt + 0.5 * SR - i) / (1.5 * SR)); // gone before the silent end card
    const j = i % mn;
    L[i] += m[2 * j] * gi;
    R[i] += m[2 * j + 1] * gi;
  }
  musicNote = `, music ${musicFile.split(/[\\/]/).pop()} (${mI[1]} LUFS -> ${MUSIC_LUFS}, ducked ${DUCK_DB} dB)`;
}

// ---- write a 32-bit float WAV ----
let peak = 0;
for (let i = 0; i < N; i++) peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
const buf = Buffer.alloc(44 + N * 8);
buf.write("RIFF", 0);
buf.writeUInt32LE(36 + N * 8, 4);
buf.write("WAVE", 8);
buf.write("fmt ", 12);
buf.writeUInt32LE(16, 16);
buf.writeUInt16LE(3, 20); // IEEE float
buf.writeUInt16LE(2, 22);
buf.writeUInt32LE(SR, 24);
buf.writeUInt32LE(SR * 8, 28);
buf.writeUInt16LE(8, 32);
buf.writeUInt16LE(32, 34);
buf.write("data", 36);
buf.writeUInt32LE(N * 8, 40);
for (let i = 0; i < N; i++) {
  buf.writeFloatLE(L[i], 44 + i * 8);
  buf.writeFloatLE(R[i], 48 + i * 8);
}
writeFileSync(OUT + "audio.wav", buf);
console.log(`out/audio.wav: ${(N / SR).toFixed(2)} s, ${events.length} UI sounds, peak ${(20 * Math.log10(peak)).toFixed(1)} dBFS${musicNote}`);
