# OpenStall Collective: the demo video

Target: 2:40 to 2:50, never over 3:00 (Devpost's limit). Public on YouTube.

## Narration (ElevenLabs v3, voice Sarah, stability Natural)

**Hook**

[thoughtful] "Forty hand-embroidered cushion covers... needed in thirty days."
[steady] "One AI shopping agent, ready to buy."
[concerned] "And the women who make them best sell only on WhatsApp... and none of them can make forty alone."

**Title**

[confident] "OpenStall Collective turns them into one supplier, in three steps: list, split, and pay on proof."
[assured] "Claude does the talking. Code decides. PayPal holds the money."

**Step one: list**

[clear] "Step one: list."
[warm] "This is a real chat on OpenStall's WhatsApp number. A maker writes one line in Urdu... and sends a photo."
[analytical] "Claude reads the photo: a blue paisley cushion cover. Every number in the listing comes from the maker's own words."
[reassuring] "OpenStall asks only for what's missing, one short question at a time, in Urdu."
[upbeat] "One tap on haan, yes... and the stall is live, for any AI agent to read."

**Step two: split**

[clear] "Step two: split."
[steady] "A buyer's AI agent asks OpenStall's MCP storefront for forty covers, at most thirty dollars each."
[analytical] "Each maker's agent bids, and code checks every price against her floor and the buyer's maximum."
[confident] "Plain code splits the order: twelve from Amina, eleven from Priya, ten from Lucía, seven from Grace... eight hundred and fifteen dollars."
[clear] "The agent can't pay. A person approves one PayPal checkout, intent authorize... so PayPal only holds the money."
[warm] "Each maker hears about her share on her phone, in her own language."

**Step three: pay on proof**

[confident] "Step three: pay on proof."
[steady] "Priya ships her parcel in Jaipur and photographs the courier receipt."
[analytical] "AI reads the courier and the tracking number... and Priya confirms with one tap."
[upbeat] "Only then is her share captured from that one authorization, and paid out to her PayPal... with her tracking on the PayPal order."
[reassuring] "In Pakistan, where Payouts can't reach, Amina is paid to her bank through Hyperwallet... simulated here, and labelled."

**When a maker drops out**

[concerned] "And if Grace can't make it?"
[reassuring] "Her share is released, never charged... and the other makers' agents bid for her seven covers, as a top-up."

**Trust**

[confident] "Try to break it: ten real attacks... all refused by the code they target."
[assured] "Every maker carries a signed trust passport. Change one number, and the signature fails."
[professional] "Orders and payments run on APIMatic's PayPal SDK... and an ops agent checks them through PayPal's own MCP server, read-only."
[thoughtful] "A receipt photo can be faked, so next, the courier's own scan will release the money."

**Close**

[confident] "Claude talks."
[assured] "Code decides."
[definitive] "PayPal pays on proof."

Every claim above is true of the code. The footage is test mode, where PayPal and the models are simulated and every
page says so; the hosted demo runs the same story on PayPal's real sandbox.

## Scene plan

| Time | Narration | On screen | Source |
| --- | --- | --- | --- |
| 0:00 | Hook | "40 cushion covers · 30 days", an AI agent, five WhatsApp phones on a map (Lahore, Jaipur, Oaxaca, Detroit, Manchester) | Animation |
| 0:13 | Title | Logo, three chips: List · Split · Pay on proof; the mantra as text | Animation |
| 0:30 | Step one | The real WhatsApp chat of November 10: one line in Urdu, the welcome, the photo, Claude's read, the questions, the summary with a ہاں button, "your listing is live" | Animation (`whatsapp-real-chat.md`) |
| 0:50 | Step two | /demo: the stepper, offers with two refused, the split 12 / 11 / 10 / 7 = $815.00 | Screen recording R2 |
| 1:15 | Approval | The approval page, the PayPal page, "PayPal is holding $815.00" | Screen recording R3 |
| 1:28 | Told | Four phones get the order in Urdu, Hindi, Spanish and English | Animation, then R4 |
| 1:35 | Step three | Priya's WhatsApp: the receipt photo, "India Post, EE123456789IN, reply yes" with a button, "you've been paid $176.00" | Animation, then R5 (Paid on proof, Tracking on PayPal) |
| 2:05 | Drop-out | Grace says she can't; her share released; a top-up from Priya, 7 for $112.00 | Animation, then R6 |
| 2:15 | Trust | Try to break it: 10 of 10 refused; the tamper check failing and coming back; /status: APIMatic cross-check and the PayPal doctor | R7, R8, R9 |
| 2:40 | Close | The three lines as type; hosted demo and GitHub addresses | Animation |

## What a judge looks for, and where the video shows it

1. **The problem in seconds:** who is left out (makers on WhatsApp) and why now (AI agents buy for people).
2. **PayPal at the centre:** one AUTHORIZE order that only holds the money, a partial capture per maker on proof,
   Payouts, tracking on the PayPal order, a void for a share that drops out. Show the receipt page's words.
3. **AI that is useful but fenced:** agents negotiate and write; code checks every price and number; no agent tool can
   move money; a person approves once.
4. **Real people in their language:** Urdu, Hindi, Spanish and English, on WhatsApp, with no app to install.
5. **Safety you can see:** ten attacks refused, a signed passport that breaks when changed.
6. **Honesty:** simulated parts are labelled on screen and in the voice; the photo-is-not-proof limit is named.
7. **Where to try it:** the hosted demo and the repository at the end, on screen long enough to read.
8. **Craft:** under 3:00, clear voice, captions burnt in, no music that is not licensed.

## Screen recordings (test mode, this computer)

Record at 1920 × 1080, browser at 100%, light mode, no bookmarks bar, one tab. Move the mouse slowly and pause a
second on each result. Open http://localhost:3000.

- **R1 Home:** the hero, then a slow scroll to "How it works". 10 s.
- **R2 /demo:** press **Run the demo request**; let the stepper tick; scroll through Offers (two refused) and
  Allocation (12 / 11 / 10 / 7, $815.00). 25 s.
- **R3 Approval:** **Open its approval page**, scroll to the split, **Approve and pay with PayPal**, **Approve** on
  the simulated PayPal page; wait for "Each maker has been told about her share". 20 s.
- **R4 Phones:** **Watch it happen on the live demo**, scroll to the makers' phones. 10 s.
- **R5 Pay on proof:** on Priya's phone, **Send Priya's courier receipt**, then **Reply "हाँ" as Priya**; scroll up
  to Payments: Paid on proof, Tracking on PayPal. 20 s.
- **R6 Drop-out:** on Grace's phone, **Grace can't make it**, then **Reply "Yes" as Grace**; Payments shows **The
  order heals itself**; **Approve the top-up** and approve it. 20 s.
- **R7 Attacks:** **Try every attack**; wait for "10 of 10 attacks refused"; scroll the rows. 10 s.
- **R8 Tamper:** in **Check a trust passport**, change On-time rate to 0.99, **Check the signature**, then **Put it
  back**. 10 s.
- **R9 Status and dashboard:** /status down to the PayPal doctor and the APIMatic cross-check; /dashboard's Demand
  Radar tip. 10 s.
