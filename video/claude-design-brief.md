# OpenStall Collective: video brief for Claude Design

A 2:45 motion-graphics demo video for the PayPal AI Hackathon (Devpost). Everything needed is in this folder.

## The deliverable

- **1920 × 1080, 60 fps, H.264 MP4, 2:45 to 2:50.** Never longer than 2:59: Devpost's limit is 3 minutes. The screen
  clips are already 60 fps, so keep every move smooth: eased zooms and pans, no frame drops.
- **Style:** clean motion graphics on a warm paper background, the teal accent, Geist type; WhatsApp chats as animated
  phone mockups; screen recordings inside a soft browser frame with a gentle zoom on what matters; burnt-in English
  captions of the narration.
- **Audio:** `narration-draft.mp3` is the master track (2:43, ElevenLabs v3). Optional soft, royalty-free music well
  under the voice. Small UI sounds (a message pop, a tap) are welcome.

## Brand

| Token | Value | Use |
| --- | --- | --- |
| Background | `#f8f6f1` | warm paper |
| Surface | `#ffffff` | cards, phone screens |
| Ink | `#1c1714` | text |
| Muted | `#5a514a` | secondary text |
| Border | `#e8e1d7` | hairlines |
| Accent | `#0e6e64` (strong `#0a574f`, soft `#e1f2ee`) | OpenStall teal |
| Amina | `#eb6834` | her phone, her share |
| Priya | `#2a78d6` | |
| Lucía | `#1baf7a` | |
| Grace | `#eda100` | |
| Noor | `#e87ba4` | the top-up |

Type: Geist Sans and Geist Mono (free, from Vercel). Urdu: Noto Nastaliq Urdu or Noto Naskh Arabic, right to left.
Hindi: Noto Sans Devanagari. Logo: `assets/logo.svg`; icon: `assets/app-icon-1024.png`.

## Files

| File | What it is |
| --- | --- |
| `narration-draft.mp3` | the whole voiceover, the master track |
| `voice/01-hook.mp3` … `voice/08-close.mp3` | the same, one clip per section |
| `narration.md` | the script with its ElevenLabs tags, and the judges' checklist |
| `narration-timecodes.json` | when each line starts and ends on the master track |
| `whatsapp-real-chat.md` (and `.json`) | the real WhatsApp chat of November 10 (19 messages, a phone writing to OpenStall's number), for Step one |
| `whatsapp-scripts.md` (and `.json`) | the other chats to animate (the makers' orders, receipts, payments, Grace dropping out), word for word from the app |
| `assets/` | logo, screenshots, the photo from the real chat (`real-chat-photo-1.jpg`), a sample cushion photo, two demo courier slips |
| `recordings/` | the screen recordings R2 to R9 (below) |

## Storyboard (times on the master track)

| Time | Voice | Picture |
| --- | --- | --- |
| 0:00.1 | "Forty hand-embroidered cushion covers... needed in thirty days." | A big "40" counts up; "hand-embroidered cushion covers"; a calendar chip "30 days". |
| 0:05.4 | "One AI shopping agent, ready to buy." | An agent card slides in, in mono: `request_quote(40 cushion covers, at most $30)`. |
| 0:08.5 | "And the women who make them best sell only on WhatsApp... and none of them can make forty alone." | Pins on a world map: Lahore, Jaipur, Oaxaca, Detroit, Manchester. A small phone pops at each; a meter under them never reaches 40. |
| 0:14.9 | "OpenStall Collective turns them into one supplier, in three steps: list, split, and pay on proof." | The logo, then "OpenStall Collective"; three chips: List · Split · Pay on proof. |
| 0:22.4 | "Claude does the talking. Code decides. PayPal holds the money." | Three lines of kinetic type, one per beat. |
| 0:28.1 | "Step one: list." | Chapter card "1 · List". |
| 0:30.4 | "This is a real chat on OpenStall's WhatsApp number. A maker writes one line in Urdu... and sends a photo." | The real chat (`whatsapp-real-chat.md`), on a phone: his line «میں ہاتھ سے کشن کور بناتا ہوں», the formatted Urdu welcome, then his photo (`assets/real-chat-photo-1.jpg`). A small label: "A real WhatsApp chat, November 10". |
| 0:38.1 | "Claude reads the photo: a blue paisley cushion cover. Every number in the listing comes from the maker's own words." | OpenStall's reply «نیلے نقش والا کشن کور» with its English, "Blue patterned cushion cover"; beside the phone a card "Your listing so far" fills in as he answers: $15.00 each, 100 a week, arrives in 20 days, from Islamabad. |
| 0:45.7 | "OpenStall asks only for what's missing, one short question at a time, in Urdu." | The questions and his answers, fast: 15$, 100, 20, Islamabad, Pakistan, 8$ (his lowest price), 25 (days to make an order); English in small type under each question. |
| 0:52.1 | "One tap on haan, yes... and the stall is live, for any AI agent to read." | The summary with its button [ہاں، اشتہار لگائیں]; a tap; «آپ کا اشتہار لگ گیا ہے!» and his stall link (show it as openstall-collective.onrender.com/stall/…); chips: MCP · catalog.json · llms.txt. |
| 0:58.9 | "Step two: split." | Chapter card "2 · Split". |
| 1:01.3 | "A buyer's AI agent asks OpenStall's MCP storefront for forty covers, at most thirty dollars each." | **R2**: /demo, Run the demo request, the stepper ticking. Label: "MCP storefront: search · request_quote". |
| 1:08.9 | "Each maker's agent bids, and code checks every price against her floor and the buyer's maximum." | **R2**: Offers. Highlight Grace's $32.00 and Noor's $31.00 "over the buyer's maximum of $30.00", back at $29.00 and $29.50. Text: "No agent can talk a price below a maker's floor." |
| 1:15.4 | "Plain code splits the order: twelve from Amina, eleven from Priya, ten from Lucía, seven from Grace... eight hundred and fifteen dollars." | **R2**: Allocation. Over it, a bar builds in the makers' colours: 12 × $18 = $216, 11 × $16 = $176, 10 × $22 = $220, 7 × $29 = $203; a total counts to $815.00. |
| 1:25.8 | "The agent can't pay. A person approves one PayPal checkout, intent authorize... so PayPal only holds the money." | **R3**: the approval page, Approve and pay with PayPal, the simulated PayPal page, Approve, "Simulated PayPal is holding $815.00". Chip: "intent AUTHORIZE: held, not captured". |
| 1:33.5 | "Each maker hears about her share on her phone, in her own language." | Four phones at once (A2 Urdu, A3 Hindi, A4 Spanish, A5 English), each getting her order message; English under each. |
| 1:37.6 | "Step three: pay on proof." | Chapter card "3 · Pay on proof". |
| 1:40.5 | "Priya ships her parcel in Jaipur and photographs the courier receipt." | Priya's phone (A3): a camera flash, then `assets/receipt-priya.jpg` as a photo message. |
| 1:44.6 | "AI reads the courier and the tracking number... and Priya confirms with one tap." | A3's reply with "India Post" and "EE123456789IN" highlighted; a tap on [हाँ, सही है]. |
| 1:50.0 | "Only then is her share captured from that one authorization, and paid out to her PayPal... with her tracking on the PayPal order." | The hold bar: Priya's $176 segment lifts out, "Captured", then "Paid out" with a check; "आपको भुगतान हो गया!"; **R5**: Payments, Paid on proof and Tracking on PayPal. Then **R12** at 4.8: her row on the buyer's receipt, "Paid on proof of shipping". |
| 1:57.6 | "In Pakistan, where Payouts can't reach, Amina is paid to her bank through Hyperwallet... simulated here, and labelled." | Amina's phone (A2): `assets/receipt-amina.jpg`, the confirm, "آپ کو ادائیگی ہو گئی! … Hyperwallet …". Chip: "Hyperwallet · simulated". Then **R12** at 13.2: her row, "Paid to her bank through Hyperwallet (simulated)". |
| 2:05.3 | "And if Grace can't make it?" | Grace's phone (A5): "Sorry, I can't make this order." |
| 2:08.1 | "Her share is released, never charged... and the other makers' agents bid for her seven covers, as a top-up." | A5: [Yes, drop my share]; Grace's $203 segment fades to "Released · never charged"; a new segment slides in: Priya 7 × $16.00 = $112.00, "top-up" (she has shipped her 11, so she has room, and she is the cheapest); **R6**: "The order heals itself". **R12** at 18.5 and 23.5 shows the same on the receipt: "Released back to you", and the top-up. |
| 2:15.1 | "Try to break it: ten real attacks... all refused by the code they target." | **R7**: Try every attack; rows turn to refused; "10 of 10 attacks refused". |
| 2:20.7 | "Every maker carries a signed trust passport. Change one number, and the signature fails." | **R8**: On-time rate to 0.99, "Signature does not match" in red, Put it back, valid again. |
| 2:26.9 | "Orders and payments run on APIMatic's PayPal SDK... and an ops agent checks them through PayPal's own MCP server, read-only." | **R9**: the hosted /status: the PayPal doctor's checks and the APIMatic cross-check. Chips: Orders v2 · Payments v2 · Payouts · Tracking · Webhooks · Disputes · JS SDK · MCP server. |
| 2:36.0 | "A receipt photo can be faked, so next, the courier's own scan will release the money." | A receipt with a question mark; a courier's scan icon with a check; money moves only after the scan. Label: "Next". |
| 2:41.4 | "Claude talks." / "Code decides." / "PayPal pays on proof." | One line per beat on teal. |
| 2:45.6 | (silence) | End card for 4 to 5 seconds: the logo, **openstall-collective.onrender.com**, **github.com/FahadRamxan/OpenStall-Collective**, "PayPal AI Hackathon 2026". |

## Animating WhatsApp

- A plain phone frame, no maker's brand. The chat header reads "OpenStall". A WhatsApp-like look (bubbles, ticks,
  quick-reply buttons) without WhatsApp's logo.
- Before each OpenStall message, a typing indicator for about half a second; bubbles pop in; a button tap shows a
  ripple, and the button's title comes back as her message, as WhatsApp does.
- Urdu right to left; WhatsApp's `*bold*` as bold; numbered lines and bullets kept.
- Under each OpenStall bubble, its English in small muted type, for the viewer (the app shows the same on its pages).
- Use the exact text in `whatsapp-real-chat.md` (Step one) and `whatsapp-scripts.md` (everything after); shorten long
  messages with a fade if needed, never reword them. Show the stall link as openstall-collective.onrender.com/stall/….

## Keep it honest

- The screen recordings are test mode, where PayPal and the models are simulated. Leave the "Test mode" and
  "Simulated PayPal" labels in shot; don't crop them out.
- Keep "simulated" on Hyperwallet, and the demo slips' own small print.
- Numbers must match the app: $815.00 = $216 + $176 + $220 + $203; the top-up is Priya's 7 × $16.00 = $112.00.

## The screen recordings (in `recordings/`, ready to use)

Recorded from the real app on November 11: **1920 × 1080 at a true 60 fps** (Chrome on the GPU at 1.5x, its frames
taken as drawn, about 80 to 100 a second, and laid on a constant 60 fps timeline), H.264 at high quality. The
cursor is a soft teal ring that glides with easing and fades out at rest; every scroll is eased. R1 to R8 and R10 to
R12 are test mode on this computer (simulated PayPal, labelled on screen); R9 is the hosted demo on PayPal's real
sandbox. Each clip ends on a few seconds of still frame, for a clean cut. Times below are seconds into each clip
(also in `recordings/moments.json`).

| Clip | Length | Shows | Key moments |
| --- | --- | --- | --- |
| `R1-home.mp4` | 17.2 s | The home page | 3.3 hover "See the live demo"; 11.4 How it works |
| `R2-run.mp4` | 33.2 s | /demo: the buyer agent's request, offers, the split | 5.8 Run the demo request; 9.5 Request; 13.9 Offer rules; 18.0 Offers (two refused); 24.1 Allocation (12/11/10/7, $815.00); 30.5 Order |
| `R3-approve.mp4` | 33.9 s | Approval, simulated PayPal, the hold | 4.5 approval page; 9.2 the split and pay-on-proof explained; 16.4 simulated PayPal; 22.9 "Simulated PayPal is holding $815.00"; 24.4 each maker told |
| `R4-phones.mp4` | 22.2 s | Payments and the makers' phones | 8.5 Payments (reserved, makers told); 13.4 the four phones in four languages |
| `R5-proof.mp4` | 21.6 s | Priya paid on proof | 6.0 her courier receipt sent and read (India Post, EE123456789IN); 12.4 her "हाँ", paid; 17.1 Payments: Paid on proof, Tracking on PayPal |
| `R6-heal.mp4` | 22.8 s | Grace drops out, the order heals itself | 5.7 "Grace can't make it"; 11.7 she confirms; 15.5 The order heals itself (top-up: Priya, 7 for $112.00) |
| `R7-attacks.mp4` | 16.1 s | Try to break it | 7.6 Try every attack; 10 of 10 attacks refused, each with what refused it |
| `R8-tamper.mp4` | 21.6 s | The signed trust passport | 8.1 on-time rate changed to 0.99; 12.2 "Signature does not match"; 18.5 put back: valid |
| `R9-status-hosted.mp4` | 23.3 s | The hosted demo's /status (real PayPal sandbox) | 4.4 PayPal doctor: nothing failed; 10.7 APIMatic cross-check; 16.3 PayPal products |
| `R10-dashboard.mp4` | 19.2 s | The AG Grid dashboard | 2.2 Demand Radar tip, then orders, payouts and tracking |
| `R11-seller-chat.mp4` | 11.6 s | Priya's whole chat as the app shows it | 2.2 Hindi with English under each message, "आपको भुगतान हो गया!" |
| `R12-receipt.mp4` | 39.0 s | The buyer's receipt after the proofs: how the money moved | 2.4 "PayPal is holding $815.00", every share confirmed; 4.8 Priya: Paid on proof of shipping, India Post EE123456789IN, See her courier receipt, Tracking on PayPal; 13.2 Amina: paid to her bank through Hyperwallet (simulated), TCS 7712345678; 18.5 Lucía reserved, Grace released back to you; 23.5 The order heals itself (Priya, 7 for $112.00); 28.0 "One PayPal authorization for $815.00. Each maker's share is captured when she ships." |

WhatsApp itself is animated from `whatsapp-scripts.md`, not recorded.
