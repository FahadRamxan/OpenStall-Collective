You're making the demo video for OpenStall Collective, our PayPal AI Hackathon entry. Everything you need is in the
attached `video-kit` folder. Read `claude-design-brief.md` first: it is the storyboard, scene by scene, timed to the
voiceover.

**What to build:** a motion-graphics demo video, 1920 × 1080 at 60 fps, about 2:50 long and never over 2:59.

**Sound:** `narration-draft.mp3` is the master track from 0:00. Each scene starts when its line starts (the times are
in the brief's storyboard and in `narration-timecodes.json`). Burn in English captions of each line, taken from
`narration.md` without the [tags]. Soft royalty-free music under the voice is optional; keep it well below the voice.

**Look:** warm paper background #f8f6f1, ink #1c1714, muted #5a514a, OpenStall teal #0e6e64. Type in Geist Sans and
Geist Mono. One colour per maker, used everywhere she appears: Amina #eb6834, Priya #2a78d6, Lucía #1baf7a,
Grace #eda100, Noor #e87ba4. The logo is `assets/logo.svg`. Motion should be calm and premium: eased, smooth,
nothing bouncy.

**Screen recordings** (`recordings/R1` to `R12`, already 1080p at 60 fps; R12 is the buyer's receipt that shows how the money moved): show each one in a soft rounded browser
frame with a light shadow, and use gentle eased zooms and pans toward whatever the voice is talking about. Each
clip's key moments, to the second, are in the brief and in `recordings/moments.json`. Trim freely, but never so fast
that the text can't be read, and keep the app's "Test mode" and "Simulated" labels in shot.

**WhatsApp:** animate the phone chats from the exact text in `whatsapp-real-chat.md` (Step one: a real chat on our
WhatsApp number from November 10, with its photo `assets/real-chat-photo-1.jpg`) and `whatsapp-scripts.md` (the
makers' order messages, the courier receipts, the payments, Grace dropping out). Give them a WhatsApp-like look,
without WhatsApp's logo. Urdu reads right to left (use Noto Nastaliq Urdu); Hindi uses Noto Sans Devanagari. Show a
typing indicator before each OpenStall message. Buttons are quick replies with a small tap ripple. Put each
OpenStall message's English line under its bubble in small muted type, for the viewer. Never reword or translate
the messages yourself.

**Motion graphics:**
- The hook: a counter for 40 cushion covers in 30 days, and map pins for Lahore, Jaipur, Oaxaca, Detroit and Manchester.
- The three steps as chips: List · Split · Pay on proof.
- The PayPal hold as a bar: $815.00 = $216 + $176 + $220 + $203. Priya's segment is captured and paid on proof; Grace's is released, never charged; a top-up of 7 × $16.00 = $112.00 from Priya takes its place.
- The beat where a receipt photo could be faked, and a courier's scan releases the money instead.
- The closing lines, one per beat: "Claude talks. Code decides. PayPal pays on proof."

**End card** (4 to 5 seconds, silent): the logo, openstall-collective.onrender.com,
github.com/FahadRamxan/OpenStall-Collective and "PayPal AI Hackathon 2026".

**Keep it honest:** use the numbers exactly as the brief gives them. Keep "simulated" on Hyperwallet and on the
test-mode footage. The courier slips are marked as demo slips. Nothing in the video may claim a real shipment or a
real payment.

**Deliver:** the final MP4 (H.264, 1920 × 1080, 60 fps, AAC audio), plus the project or source so we can make small
changes. If you can't render video directly, build it as one HTML page whose timeline plays in sync with
`narration-draft.mp3` at 1920 × 1080, so we can record it at 60 fps.
