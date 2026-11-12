# OpenStall Collective: the demo video

**Watch it:** https://www.youtube.com/watch?v=zbl8VqHXcYc (2:51, public on YouTube; [title, description and
chapters](youtube.md)).

Everything the video is made from is in this folder: the script and its voice, the real WhatsApp chat and the makers'
chats, the twelve screen recordings, and the studio that turns them into the MP4, frame by frame at a true 60 fps.

**Kept honest:** the screen recordings are test mode, where PayPal and the AI models are simulated and every page says
so; the video marks them "Test mode · PayPal simulated". The /status clip (R9) is the hosted demo on PayPal's sandbox.
The courier slips are demo slips, and Hyperwallet is marked simulated. Step 1 is a real WhatsApp chat from November 10,
word for word from the app's database. The voice is ElevenLabs Eleven v3 (the voice "Sarah") reading
[narration.md](narration.md); the music is original, composed in code.

## What is here

| Path | What |
| --- | --- |
| [narration.md](narration.md) | The script, with its ElevenLabs v3 audio tags, the scene plan, and what judges should see |
| `narration-draft.mp3`, `voice/` | The narration as spoken: one MP3 per section, and all of them joined, the video's master track |
| [narration-timecodes.json](narration-timecodes.json) | When each line starts and ends on the master track, from ElevenLabs Scribe's word timings; the captions come from it |
| [whatsapp-real-chat.md](whatsapp-real-chat.md) | The real chat of November 10 that Step 1 animates (and its `.json`) |
| [whatsapp-scripts.md](whatsapp-scripts.md) | The makers' order messages, courier receipts, payments and Grace dropping out, exported from test mode (and its `.json`) |
| [claude-design-brief.md](claude-design-brief.md), [claude-design-prompt.md](claude-design-prompt.md) | The storyboard, timed to the narration, and its brief, written before the studio was built |
| `assets/` | The logo, the app icon, screenshots, the real chat's photo, and the two demo courier slips |
| `recordings/` | The screen recordings R1 to R12 (1920 × 1080, 60 fps), `moments.json` (when each step happens inside each one) and `contact-sheet.jpg` |
| [studio/](studio/README.md) | The video itself: an HTML page whose every frame is a function of time on the narration, and the tools that render it |
| `tools/` | How the recordings, the chats, the narration and its timings, and the hosted demo's courier slip were made |
| [youtube.md](youtube.md), `youtube-thumbnail.jpg` | What YouTube shows: the title, the description with its chapters, and the thumbnail |

Not in git, because the tools make them again: the rendered MP4 (`studio/out/`, about 50 MB; YouTube has it), the
frame cache (`studio/cache/`, about 700 MB), the music (`studio/music/`, from `studio/tools/make-music.mjs`, seeded, so
the same every time) and `node_modules`. The recordings and the voice are kept: a new take would move every shot and
caption time.

## Render the video again

Needs Node 24 or later, ffmpeg on the PATH, and Playwright's Chromium, the one the web app's browser tests use
(`npx playwright install chromium` in `apps/web`, once). Recording the clips again also needs `npm install` in
`apps/web`.

```bash
cd video/studio
npm install
node tools/make-music.mjs
node tools/extract-frames.mjs
node tools/render.mjs
```

The MP4 lands in `video/studio/out/OpenStall-Collective-demo.mp4`, in about 6 minutes. To watch it play in sync with
the narration first: `node tools/serve.mjs`, then http://localhost:5178/studio/. [studio/README.md](studio/README.md)
lists every scene and where to change it.

## Record the clips again (Windows)

The clips are the app itself in test mode, recorded by `tools/rec60.cjs`: headless Chromium on the GPU at a real 1.5×
scale, its frames taken with their timestamps and laid on a 60 fps timeline by ffmpeg, the cursor and every scroll
eased. From the repository's root:

1. `video\tools\run-api-test-mode.cmd` starts the API in test mode on port 8000, with a fresh demo world in
   `video/test-mode.db`.
2. `video\tools\run-web-test-mode.cmd` builds the web app into `apps/web/.next-video` and starts it on port 3000.
3. Record every clip but the last:
   `node video/tools/rec60.cjs R1-home R2-run R3-approve R4-phones R5-proof R6-heal R7-attacks R8-tamper R9-status-hosted R10-dashboard R11-seller-chat`
   (R9 is recorded from the hosted demo's /status).
4. The receipt clip needs an order with every kind of share on it:
   `.venv/Scripts/python video/tools/replay_story.py`, then `node video/tools/rec60.cjs R12-receipt`.
5. Stop both servers, delete `apps/web/.next-video`, and run `git checkout apps/web/tsconfig.json` (Next adds its build
   folder there).

A new take runs a little faster or slower, so check the shot times in `studio/src/data.js` (`SHOTS`) against the new
`recordings/moments.json`.

## The narration, the chats and the slip

Run these from the repository's root, with its `.venv`:

- **The voice:** edit [narration.md](narration.md), then `.venv/Scripts/python video/tools/voice.py [VOICE_ID]
  [SECTION ...]` (ElevenLabs Eleven v3; the voice Sarah unless you name another; the key from `.env`, never printed),
  and `.venv/Scripts/python video/tools/timecodes.py` for the new timings. The caption pieces in `studio/src/data.js`
  must then join back into each line: the page refuses to start if they don't.
- **The makers' chats:** with the test-mode API running, `.venv/Scripts/python video/tools/simulate.py` plays the
  whole story through it and writes `whatsapp-scripts.md` and `.json`. It refuses any API not in test mode.
- **A courier slip for the hosted demo:** `.venv/Scripts/python video/tools/make_receipt.py out.jpg [TRACKING]` makes a
  "DemoPost Express" slip, marked as a demo on its face, with a tracking number never used before (it needs the
  Windows fonts Segoe UI and Consolas, or `FONTS_DIR`). The two slips the video shows are in `assets/`.

## Credits

Fonts: Geist and Geist Mono (Vercel), Noto Nastaliq Urdu and Noto Sans Devanagari (Google), all under the SIL Open
Font License (`studio/fonts/licenses/`). The world map's dots come from world-atlas (Natural Earth, public domain).
Voice: ElevenLabs. Music and sound effects: composed in code for this video.
