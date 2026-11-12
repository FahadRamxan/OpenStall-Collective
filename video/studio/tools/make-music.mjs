// Composes an original, soft ambient music bed for the demo and writes music/openstall-bed.wav.
// Made here in code (warm pad, a quiet felt-piano arpeggio, a low root, a little reverb), so there is no licence to
// clear. D major, about 71 BPM, four chords that land on the home chord as the close begins ("Claude talks.").
// It ends before the silent end card. make-audio.mjs mixes it well under the voice and ducks it while she speaks.
//
//   node tools/make-music.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SR = 48000;
const DUR = 170.6;
const N = Math.round(DUR * SR);
const OUT = fileURLToPath(new URL("../music/", import.meta.url));
mkdirSync(OUT, { recursive: true });

const CLOSE = 161.38; // "Claude talks."
const CHORD = CLOSE / 24; // 6.724 s: 8 beats at ~71.4 BPM, so chord 24 (the home chord) starts with the close
const BEAT = CHORD / 8;
const LAST_HIT = 164.28; // "PayPal pays on proof."
const FADE_OUT = [164.9, 166.4]; // silent end card from about 166

const mtof = (m) => 440 * Math.pow(2, (m - 69) / 12);
// D major: Dmaj9, Bm11, Gmaj9, A6/9 (sus). Pad voicings move by common tones; the arpeggio sits an octave up.
const CHORDS = [
  { bass: 38, pad: [57, 61, 64, 66], arp: [74, 78, 81, 76] },
  { bass: 35, pad: [57, 62, 64, 66], arp: [71, 74, 78, 76] },
  { bass: 31, pad: [59, 62, 66, 69], arp: [71, 74, 78, 81] },
  { bass: 33, pad: [59, 64, 66, 69], arp: [69, 71, 76, 78] },
];

const L = new Float32Array(N);
const R = new Float32Array(N);
let seed = 11;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const panGains = (p) => [Math.cos(((p + 1) * Math.PI) / 4), Math.sin(((p + 1) * Math.PI) / 4)];

// ---- pad: two slightly detuned voices per note, slow swell in and out, chords overlapping ----
function pad(t0, t1, notes, level) {
  const ATT = 1.8;
  const REL = 2.4;
  const a = Math.max(0, Math.round(t0 * SR));
  const b = Math.min(N, Math.round((t1 + REL) * SR));
  notes.forEach((m, ni) => {
    const pan = [-0.4, -0.12, 0.12, 0.4][ni % 4];
    for (const det of [-4.5, 4.5]) {
      const f = mtof(m) * Math.pow(2, det / 1200);
      const w = (2 * Math.PI * f) / SR;
      const [gl, gr] = panGains(pan + det / 40);
      let ph = rnd() * 6.283;
      for (let i = a; i < b; i++) {
        const t = i / SR;
        let env;
        if (t < t0 + ATT) env = 0.5 - 0.5 * Math.cos((Math.PI * (t - t0)) / ATT);
        else if (t < t1) env = 1;
        else env = 0.5 + 0.5 * Math.cos((Math.PI * Math.min(1, (t - t1) / REL)));
        const trem = 1 + 0.06 * Math.sin(2 * Math.PI * 0.13 * t + ni);
        ph += w;
        const s = (Math.sin(ph) + 0.12 * Math.sin(2 * ph) + 0.035 * Math.sin(3 * ph)) * env * trem * level;
        L[i] += s * gl;
        R[i] += s * gr;
      }
    }
  });
}

// ---- low root: a sine with a touch of its octave, so small speakers still hear it ----
function bass(t0, t1, m, level) {
  const f = mtof(m);
  const w = (2 * Math.PI * f) / SR;
  const a = Math.max(0, Math.round(t0 * SR));
  const b = Math.min(N, Math.round((t1 + 2.0) * SR));
  let ph = 0;
  for (let i = a; i < b; i++) {
    const t = i / SR;
    let env;
    if (t < t0 + 1.2) env = 0.5 - 0.5 * Math.cos((Math.PI * (t - t0)) / 1.2);
    else if (t < t1) env = 1;
    else env = 0.5 + 0.5 * Math.cos(Math.PI * Math.min(1, (t - t1) / 2.0));
    ph += w;
    const s = (Math.sin(ph) + 0.3 * Math.sin(2 * ph)) * env * level;
    L[i] += s;
    R[i] += s;
  }
}

// ---- felt piano: soft hammer, upper partials fade first ----
const AMP = [1, 0.42, 0.2, 0.1, 0.05, 0.025];
const TAU = [1.6, 0.95, 0.62, 0.42, 0.3, 0.22];
function piano(t0, m, vel, pan) {
  const f = mtof(m);
  const a = Math.max(0, Math.round(t0 * SR));
  const b = Math.min(N, a + Math.round(3.4 * SR));
  const [gl, gr] = panGains(pan);
  for (let k = 0; k < AMP.length; k++) {
    const fk = f * (k + 1) * (1 + 0.00035 * (k + 1) * (k + 1));
    if (fk > 9000) break;
    const w = (2 * Math.PI * fk) / SR;
    let ph = 0;
    for (let i = a; i < b; i++) {
      const t = (i - a) / SR;
      const env = (1 - Math.exp(-t / 0.005)) * Math.exp(-t / TAU[k]);
      ph += w;
      const s = Math.sin(ph) * env * AMP[k] * vel;
      L[i] += s * gl;
      R[i] += s * gr;
    }
  }
}

// ---- the arrangement ----
const nChords = 25; // 0..23 cycle, 24 = the home chord for the close
for (let k = 0; k < nChords; k++) {
  const c = CHORDS[k % 4];
  const start = k * CHORD;
  const last = k === 24;
  const end = last ? FADE_OUT[1] : start + CHORD;
  pad(start - 0.9, end + 0.9, c.pad, 0.032);
  bass(start - 0.4, end + 0.4, c.bass, 0.034);
  if (!last) {
    // a gentle rolling pattern, one note a beat, the downbeat a little stronger
    const pattern = [0, 2, 1, 3, 0, 2, 1, 3];
    for (let b = 0; b < 8; b++) {
      if (k === 0 && b < 2) continue; // let the very start breathe
      const jitter = (rnd() - 0.5) * 0.012;
      const vel = (b === 0 ? 0.075 : 0.05) * (0.9 + 0.2 * rnd());
      const note = c.arp[pattern[b]];
      piano(start + b * BEAT + jitter, note, vel, [-0.25, 0.2, -0.1, 0.3][pattern[b]]);
    }
  } else {
    // the close: one soft rolled chord with "PayPal pays on proof."
    [74, 78, 81, 86].forEach((m, i) => piano(LAST_HIT + i * 0.06, m, 0.06, -0.2 + i * 0.13));
  }
}

// ---- reverb (Freeverb: 8 combs + 4 allpasses per side) ----
function freeverb(inL, inR, room = 0.84, damp = 0.45, wet = 0.32, dry = 0.8) {
  const s = SR / 44100;
  const combT = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617].map((x) => Math.round(x * s));
  const apT = [556, 441, 341, 225].map((x) => Math.round(x * s));
  const spread = Math.round(23 * s);
  const fb = room * 0.28 + 0.7;
  const d1 = damp * 0.4;
  const d2 = 1 - d1;
  const mk = (len) => ({ buf: new Float32Array(len), i: 0, store: 0 });
  const side = (off) => ({ combs: combT.map((t) => mk(t + off)), aps: apT.map((t) => mk(t + off)) });
  const sides = [side(0), side(spread)];
  const outL = new Float32Array(N);
  const outR = new Float32Array(N);
  for (let n = 0; n < N; n++) {
    const input = (inL[n] + inR[n]) * 0.015;
    for (let c = 0; c < 2; c++) {
      const sd = sides[c];
      let acc = 0;
      for (const cb of sd.combs) {
        const y = cb.buf[cb.i];
        cb.store = y * d2 + cb.store * d1;
        cb.buf[cb.i] = input + cb.store * fb;
        if (++cb.i >= cb.buf.length) cb.i = 0;
        acc += y;
      }
      for (const ap of sd.aps) {
        const bo = ap.buf[ap.i];
        ap.buf[ap.i] = acc + bo * 0.5;
        if (++ap.i >= ap.buf.length) ap.i = 0;
        acc = bo - acc;
      }
      if (c === 0) outL[n] = acc;
      else outR[n] = acc;
    }
  }
  for (let n = 0; n < N; n++) {
    const wl = outL[n] * wet * 3;
    const wr = outR[n] * wet * 3;
    outL[n] = inL[n] * dry + wl;
    outR[n] = inR[n] * dry + wr;
  }
  return [outL, outR];
}
const [ML, MR] = freeverb(L, R);

// ---- master: soften the top (keeps clear of the voice), take out rumble, fade in and out, normalise ----
const lpA = 1 - Math.exp((-2 * Math.PI * 3800) / SR);
const hpA = Math.exp((-2 * Math.PI * 35) / SR);
let lpl = 0, lpr = 0, hpl = 0, hpr = 0, pxl = 0, pxr = 0;
let peak = 0;
for (let n = 0; n < N; n++) {
  const t = n / SR;
  lpl += lpA * (ML[n] - lpl);
  lpr += lpA * (MR[n] - lpr);
  hpl = hpA * (hpl + lpl - pxl);
  hpr = hpA * (hpr + lpr - pxr);
  pxl = lpl;
  pxr = lpr;
  let g = 1;
  if (t < 2.5) g *= 0.5 - 0.5 * Math.cos((Math.PI * t) / 2.5);
  if (t > FADE_OUT[0]) g *= Math.max(0, 0.5 + 0.5 * Math.cos((Math.PI * (t - FADE_OUT[0])) / (FADE_OUT[1] - FADE_OUT[0])));
  if (t > FADE_OUT[1]) g = 0;
  ML[n] = hpl * g;
  MR[n] = hpr * g;
  peak = Math.max(peak, Math.abs(ML[n]), Math.abs(MR[n]));
}
const norm = 0.5 / peak;
const buf = Buffer.alloc(44 + N * 8);
buf.write("RIFF", 0);
buf.writeUInt32LE(36 + N * 8, 4);
buf.write("WAVE", 8);
buf.write("fmt ", 12);
buf.writeUInt32LE(16, 16);
buf.writeUInt16LE(3, 20);
buf.writeUInt16LE(2, 22);
buf.writeUInt32LE(SR, 24);
buf.writeUInt32LE(SR * 8, 28);
buf.writeUInt16LE(8, 32);
buf.writeUInt16LE(32, 34);
buf.write("data", 36);
buf.writeUInt32LE(N * 8, 40);
for (let n = 0; n < N; n++) {
  buf.writeFloatLE(ML[n] * norm, 44 + n * 8);
  buf.writeFloatLE(MR[n] * norm, 48 + n * 8);
}
writeFileSync(OUT + "openstall-bed.wav", buf);
console.log(`music/openstall-bed.wav: ${DUR} s, chord every ${CHORD.toFixed(3)} s (${(480 / CHORD).toFixed(1)} BPM), home chord at ${CLOSE} s, silent from ${FADE_OUT[1]} s`);
