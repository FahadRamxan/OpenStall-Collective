# OpenStall Collective: demo video studio

The demo video as one HTML page whose timeline is tied to `../narration-draft.mp3`, plus the tools that turn it into
the MP4. Every frame is a pure function of time on the narration track, so the same page plays live in a browser and
renders frame by frame at a true 60 fps.

- **Output:** `out/OpenStall-Collective-demo.mp4`: 1920 × 1080, 60 fps, H.264 High (BT.709), AAC 48 kHz, 2:50.6.
- **Sound:** the narration from 0:00 (the master track), quiet UI sounds (message pops, taps, the camera shutter, a
  chime when a maker is paid), and a soft original music bed (`music/openstall-bed.wav`, made by
  `tools/make-music.mjs`: D major, about 71 BPM, landing on the home chord as the close begins) about 17 dB under the
  voice. The end card is silent. The mix is at -14 LUFS.

## Preview (plays in sync with the narration)

```bash
node tools/serve.mjs
```

Then open http://localhost:5178/studio/ : Space plays or pauses, the slider scrubs, ← → step one frame
(Shift: 5 s), and `?t=95` opens at 1:35. In the preview the screen recordings play as `<video>`; the render uses their
exact frames.

## Render

```bash
npm install
node tools/extract-frames.mjs
node tools/render.mjs
```

- `extract-frames.mjs` pulls only the recording frames the video uses into `cache/frames/` (about 700 MB; safe to
  delete, it comes back). Run it again whenever you change a shot's times in `src/data.js`.
- `render.mjs` opens the page in headless Chromium (Playwright's, installed with the repo's e2e tests), screenshots
  every frame, encodes with ffmpeg, rebuilds `out/audio.wav` and muxes it. About 6 minutes on this laptop.
  Options: `--from 60 --to 95` renders a part, `--snap 12.8,95.5` writes PNG stills to `out/snaps/`,
  `--workers 8`, `--crf 16`.
- Needs Node 24+ and ffmpeg on the PATH.

### Music and sound (no re-render needed)

`tools/mux-audio.mjs` rebuilds the soundtrack and puts it on the finished MP4 in seconds, without re-rendering frames.
The music is set to -24 LUFS on its own, ducked 6 dB while the voice speaks, and gone before the silent end card.

```bash
node tools/make-music.mjs
node tools/mux-audio.mjs
```

- A different royalty-free track: `node tools/mux-audio.mjs --music path/to/track.mp3` (it is levelled the same way).
- No music: `node tools/mux-audio.mjs --no-music`. Levels are at the top of `tools/make-audio.mjs`.

## Scenes (times on the narration track)

| Time | Scene (`src/scenes.js`) | Picture |
| --- | --- | --- |
| 0:00 | hook | "40" counts up with 40 dots, "hand-embroidered cushion covers", a "30 days" chip; the AI agent card types `request_quote(40 cushion covers, at most $30)`; a dotted world map with Lahore, Jaipur, Oaxaca, Detroit, Manchester, a phone at each pin, and a meter that never reaches 40 |
| 0:14.9 | title | the pins gather into the logo; OpenStall Collective; List · Split · Pay on proof |
| 0:22.4 | mantra | Claude does the talking. / Code decides. / PayPal holds the money. |
| 0:28.1 | chapter1 | Step 1 · List |
| 0:30.4 | listing | the real chat of November 10 on a phone (date chip, Urdu, the photo, Claude reading it); "Your listing so far" fills from his own words (each answer flies into its field); one tap on the ہاں button; the stall goes live; MCP · catalog.json · llms.txt |
| 0:58.9 | chapter2 | Step 2 · Split |
| 1:01.3 | split | R2: Run the demo request, the request, offers with Grace's $32.00 and Noor's $31.00 refused and their retries, the allocation with the split card (12 × $18 = $216 … total $815.00); R3: approval page, simulated PayPal, "Simulated PayPal is holding $815.00", intent AUTHORIZE chip |
| 1:33.5 | four | four phones get their order in Urdu, Hindi, Spanish, English |
| 1:37.6 | chapter3 | Step 3 · Pay on proof |
| 1:40.5 | proof | Priya: camera flash, her demo slip, the AI read (India Post, EE123456789IN), one tap, the hold card (captured, paid out), R12 her receipt row; Amina: TCS slip, paid through Hyperwallet (simulated), R12 her row; Grace drops out: released, never charged, Priya's top-up 7 × $16.00 = $112.00, R12 "The order heals itself" |
| 2:15.1 | trust | R7 ten attacks refused; R8 the signed passport fails and comes back; R9 the hosted /status (APIMatic cross-check, PayPal doctor) with the PayPal product chips |
| 2:36.0 | next | a receipt photo can be faked → Next: the courier's own scan will release the money |
| 2:41.4 | close | Claude talks. / Code decides. / PayPal pays on proof. (on teal) |
| 2:45.9 | end | logo, openstall-collective.onrender.com, github.com/FahadRamxan/OpenStall-Collective, PayPal AI Hackathon 2026 (silent) |

## Where to change things

| What | Where |
| --- | --- |
| Caption cuts (pieces of each narration line, cut at the voice's own pauses) | `src/data.js`, `CAPTION_CUTS` |
| When each chat message, typing indicator, tap and highlight happens | `src/data.js`, `CHATS` |
| Which part of each screen recording plays, the zooms and pans, the highlight boxes | `src/data.js`, `SHOTS` |
| Maker names, colours, numbers | `src/data.js`, `MAKERS` |
| The scenes themselves (layout, motion) | `src/scenes.js` |
| Phone, browser frame, PayPal hold card, captions | `src/components.js` |
| Colours and type | `styles.css` |

## Kept exact

- **Captions** come from `../narration-timecodes.json` (the same lines as `narration.md`, without the tags). The page
  refuses to start if the caption pieces in `src/data.js` don't join back into each line word for word.
- **Chats** are read at start from `../whatsapp-real-chat.json` and `../whatsapp-scripts.json` (checked against the
  `.md` files). Nothing is retyped or translated. Two display choices, both from the brief: the real chat's stall link
  shows as `openstall-collective.onrender.com/stall/…`, and a tap on a quick-reply button sends the button's title
  back as her message, as WhatsApp does.
- **Numbers:** $815.00 = $216 + $176 + $220 + $203; the top-up is Priya's 7 × $16.00 = $112.00.
- **Honesty:** test-mode footage carries a "Test mode · PayPal simulated" badge in the browser bar, and the app's own
  "Test mode" and "Simulated" labels stay in shot (marked in amber where the voice mentions them). Hyperwallet is
  marked simulated, the courier slips carry a "Demo slip" tag, the PayPal hold card says the demo runs in test mode,
  and the hosted /status clip (R9) is labelled "Hosted demo · PayPal sandbox".

## Files

- `index.html`, `styles.css`, `src/`: the page. `src/map-dots.js` is generated by `tools/make-map.mjs` from
  world-atlas (Natural Earth, public domain).
- `fonts/`: Geist and Geist Mono (Vercel), Noto Nastaliq Urdu, Noto Sans Devanagari; all SIL Open Font License
  (`fonts/licenses/`).
- `music/openstall-bed.wav`: the original music bed (from `tools/make-music.mjs`).
- `tools/`: `serve.mjs`, `extract-frames.mjs`, `render.mjs`, `make-audio.mjs`, `make-music.mjs`, `mux-audio.mjs`,
  `make-map.mjs`, `shots.mjs`, `check-preview.mjs`.
