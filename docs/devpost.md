# OpenStall Collective: the Devpost submission

What was entered on Devpost on November 11, 2026, page by page, kept here so the repository and the submission say the same thing. Every claim is in the README and checked by the tests; anything simulated says so. The demo token and the PayPal sandbox buyer login are typed into the Devpost form by a person, never into this repository.

## Project overview

**Project name:** OpenStall Collective

**Elevator pitch:** WhatsApp makers become one supplier that AI shopping agents can buy from, and PayPal pays each maker only when she proves she shipped.

## Project details (public)

### About the project

```markdown
## Inspiration

Where we live, in Pakistan, a huge number of small businesses run entirely on WhatsApp. A woman stitching embroidered cushion covers at home shares photos in chats, takes orders by voice note, and gets paid by whoever she trusts.

At the same time, shopping is moving to AI agents. People ask an assistant to find 40 cushion covers for an office and let it buy. Those agents buy from big stores with clean catalogs and checkout APIs, so the sellers we know best are about to become invisible to the next generation of shoppers. On her own, a home maker also cannot take an order of 40, bargain with an AI buyer, or ask a stranger to trust her with the money first.

So we asked: **what if the smallest sellers could join the agent economy together, as one supplier, and be paid the moment they ship?**

## What it does

OpenStall pools makers who only use WhatsApp into one collective supplier that AI agents buy from through an MCP storefront. Three steps: **list, split, and pay on proof.**

1. **A stall from a chat.** A maker sends a photo and a voice note in Urdu. The voice note becomes text, her photo and words become a draft listing, and OpenStall asks her, in her language, one short question at a time for what is missing: her price, how many a week, delivery days, her city, then her limits (the lowest price she would take, the fewest days she needs). Her "ہاں" (yes) publishes it. [A real WhatsApp chat on our hosted demo](https://openstall-collective.onrender.com/seller-chat?seller=s_53a82b0aeae3): a maker sends Start and gets OpenStall's welcome in Urdu, delivered and read.
2. **A buyer's AI agent asks for 40 cushion covers** at most $30 each, through the MCP storefront (search, product and trust cards, request_quote).
3. **Seller agents bid within each maker's limits.** Each maker's agent proposes a price and a sentence to the buyer's agent. Code checks every price against her floor and the buyer's maximum, and a refused price goes back to her agent with the reason (up to 3 rounds), so no buyer's words can talk a price below her floor.
4. **Plain code splits the order across makers:** 12 from Amina, 11 from Priya, 10 from Lucía and 7 from Grace, $815.00, explained in two sentences whose every number code checks against the plan.
5. **A person approves one PayPal checkout that only reserves the money:** one PayPal order with intent AUTHORIZE. No agent tool can approve, capture, refund or pay out.
6. **Each maker is told on her phone, in her language** (Urdu, Hindi, Spanish or English), with the numbers from the order itself.
7. **Pay on proof.** A maker photographs her courier receipt. The model reads the courier and the tracking number, she confirms, and only then is her share captured from the one authorization and paid out on her rail. Her tracking goes on the PayPal order, so the buyer sees it at PayPal.
8. **The order heals itself.** A maker who cannot deliver says so. On her yes her share is released, never charged, and the other makers' agents are asked for her units as a top up order.
9. **Signed trust passports.** Every delivery updates a maker's record (orders delivered, how many arrived on time, disputes), signed with Ed25519, which any agent can verify. Change one number and the signature fails, shown live in the browser. (Its photo originality score is seeded demo data for now: no image check runs yet.)
10. **Demand Radar.** Searches that found nothing are grouped and sent back as tips in her language: "23 agents searched for ceramic mugs this week. Nobody sells them." (seeded demo searches, marked so).

## How we built it

**PayPal: pay on proof on the payouts path.**

* **Orders v2, intent AUTHORIZE:** one order for the whole collective order, each maker's share an item. Approving only reserves the money.
* **Payments v2:** a partial capture of each maker's share when she proves she shipped (final_capture on the last), and a void of whatever is left when a share is released.
* **Payouts:** each maker paid on her rail. Venmo for a US maker (simulated in the sandbox, which refuses Venmo payouts). A maker in Pakistan, where Payouts does not reach, is paid to her bank through Hyperwallet (simulated and labelled so: no Hyperwallet account is connected).
* **Order tracking:** her courier and tracking number on her capture, with PayPal's carrier codes (OTHER with a name for Pakistani couriers).
* **Webhooks:** every event checked with PayPal's webhook signature verification and applied exactly once.
* **Disputes:** a buyer's "never arrived" dispute answered with the maker's proof of shipping (built and tested; not yet run on the sandbox, where a dispute needs the sandbox buyer to open one).
* **PayPal's JS SDK buttons** on each maker's stall page, and **Venmo at the approval** for a buyer in the US (simulated in test mode; PayPal offers Venmo only to a US business account, which our sandbox app is not).
* **PayPal's own MCP server** (@paypal/mcp): an ops agent reads each order, its disputes and its tracking back from PayPal and checks them against OpenStall's records, offered only the tools that read. On the sandbox it listed 28 tools, and a real order's status, amount and disputes agreed.
* **Every write PayPal can deduplicate carries an idempotency key from our own ids, and none is resent blindly.** A lost answer is read back from PayPal, and tracking, which PayPal does not deduplicate, is checked against the order's trackers before it is sent.

Proven on PayPal's real sandbox: one authorization, several partial captures with tracking on each, a final capture, a void, a payout, PayPal answering a resent capture with the first one, and OpenStall's own Approve flow from start to finish.

**APIMatic's PayPal Context Plugin.** Every Orders and Payments call goes through APIMatic's PayPal Python SDK (2.29, pinned by commit). Claude Code wrote the integration with APIMatic's PayPal Context Plugin installed, following the plugin's process: the contract sheet (paypal-plan.md) first, with every SDK signature, model, enum, error union and the retry policy looked up, not recalled; then the code, strict type checks, and tests that fake PayPal at the SDK's own transport seam. An APIMatic cross check runs with the tests and on /status: every SDK call has its row in the sheet, passes exactly the keywords its row says and exists in the installed SDK by its own signatures, and the sheet, the pin and the installed SDK are one commit.

**AI.**

* **Claude Sonnet 5.5 (Anthropic):** the seller agents that negotiate within each maker's limits; the buyer's AI agent that chooses the MCP storefront's tools itself; the listing reader (vision: her photos and words into a listing); the courier receipt reader (vision); the plan explained in words; and the PayPal ops agent. Code checks every number they produce.
* **ElevenLabs Scribe v2:** a maker's voice notes into text, word for word in her language, with her known language as a hint (spoken Urdu and Hindi sound alike).
* **ElevenLabs Eleven v4 Turbo:** answers to a voice note, spoken back in her language.
* **OpenAI Whisper:** an optional second speech to text provider.

Run for real on November 9: the five makers' agents made five valid offers in one round, each with her own sentence; the split's explanation passed the number check; the buyer's AI agent chose search, quote, draft order and checkout by itself in 12 seconds; the listing reader took $18.00 and 4 a week only from Amina's own Urdu words; and the ops agent answered from eight PayPal calls, all of them reads.

Where code decides, not the model: every price against her limits, the split (cheapest valid offers first, each maker up to what she can make by the deadline), every number in a sentence the model writes, every message to a maker (templates in her language), and every movement of money. Test mode runs fixed stand ins for every model, labelled as such.

**AG Grid.** Seven AG Grid tables (Community, one shared theme in light and dark): on /demo, every seller agent's proposal with the code check's verdict, live, and the allocator's plan; on /dashboard, orders (top ups marked), each maker's payout and rail, every parcel's tracking (on PayPal, delivered, on time), the trust passports with each signature checked, and Demand Radar's groups of searches that found nothing, all following the live event feed.

**Render.** The hosted demo runs on Render from the repository's blueprint: the web app, the API and Postgres, on PayPal's sandbox, with Claude, ElevenLabs and WhatsApp (through Whapi) for real.

**The rest.** FastAPI, SQLAlchemy and Postgres; Next.js, React, TypeScript and Tailwind; the MCP Python SDK; Playwright, Vitest and pytest.

**Safety.** No MCP tool moves money: a test calls every tool with a payment gateway that fails if anything reaches it. **Try to break it** on /demo runs ten real attacks through the code they target (a price talked down to $1.00, a capture tool through MCP, a smaller total from the browser, a forged PayPal webhook, an unapproved reservation, payment before proof, one courier receipt used to be paid twice, a flood of MCP calls, a tampered trust card, and a refund through PayPal's MCP server); each is refused and recorded. Rate limits for each client and for everyone together cap what real AI costs, and a secret scan checks every file and the git history.

## Challenges we ran into

* **One checkout, many makers.** PayPal refuses intent AUTHORIZE with several purchase units, so an order with several payees could not reserve the money. We moved to the payouts path: one order with one purchase unit, a partial capture for each maker on its one authorization, then Payouts on her rail, and proved every step on the sandbox.
* **Making AI negotiation safe.** Models write persuasive offers and are bad at respecting numbers. The model writes the words; code checks every price, and a refused one goes back with the reason.
* **Messy real world input.** Voice notes mix Urdu and English, and spoken Urdu is often heard as Hindi. We pass her known language as a hint, keep the transcript word for word, and ask a short question instead of guessing.
* **Money that must never move twice.** Every PayPal write is claimed in our database before it is sent, keyed by what it is for, with PayPal's idempotency keys from our own ids. A lost answer is read back, never resent.
* **A photo is not proof.** AI can make a convincing courier receipt, and our own demo receipt is one. Today the model only reads the courier and tracking number off the photo, the maker confirms them, and one tracking number can pay only one share. The buyer stays safe: the tracking is on the PayPal order, and in a "not received" dispute PayPal checks it, refunds the buyer if it never moved, and the lost dispute lowers the maker's signed trust score. But OpenStall would already have paid her, so the photo cannot stay the proof (see What's next).

## Accomplishments that we're proud of

* Pay on proof for each maker inside one PayPal hold, proven on PayPal's real sandbox.
* An order that heals itself when a maker drops out, without charging the buyer for her share.
* Signed trust passports checked live in the browser with Web Crypto.
* A hosted demo where a real WhatsApp message is answered in Urdu.
* About 1,690 Python tests, 335 component tests and 119 browser tests, including the whole story, all thirteen steps, played twice in a row, and an accessibility check of every page in light and dark mode.

## What we learned

* The hard part of agentic commerce is trust and control, not the model: limits that code enforces, a person's one approval, and money that moves only on proof.
* PayPal's authorize then capture flow is a natural fit for collective orders: the buyer pays once, and each maker is paid when she ships.
* Designing for sellers who will never install an app kept everything inside the chat they already use.

## What's next for OpenStall Collective

* **The courier's scan releases the money, not the photo.** OpenStall books each parcel through the courier's booking API, so the tracking number comes from the courier, and her share is captured on the courier's own pickup scan. Where she books it herself, her number is checked with the courier's tracking (it exists, was booked after the order, goes from her city to the buyer's, and has been scanned) before anything is captured.
* **Paid on shipping is earned.** A maker with no record is paid on delivery, or part at pickup and the rest on delivery. A signed record of delivered orders without lost disputes earns pay on shipping, and payouts go only to verified PayPal or bank accounts.
* Real pilots with makers in Lahore, more languages reviewed by native speakers, Hyperwallet connected for Pakistan, and buyer agents commissioning products that do not exist yet, with PayPal holding the money until the work ships.

## Try it

* [The hosted demo](https://openstall-collective.onrender.com), on PayPal's sandbox, so no real money moves.
* [Be a maker on WhatsApp](https://wa.me/923275157727?text=Start): send the Start it writes for you, then a photo of something you make. The same chat runs in the browser on [the seller chat page](https://openstall-collective.onrender.com/seller-chat).
* [The code](https://github.com/FahadRamxan/OpenStall-Collective), MIT licensed. In test mode it runs on your machine with no keys or accounts: see the README's "Try it (for judges)" and [the judges' walkthrough](https://github.com/FahadRamxan/OpenStall-Collective/blob/main/docs/judges.md).
* [The demo video](https://www.youtube.com/watch?v=zbl8VqHXcYc), 2:51.
```

### Built with

Devpost's tags are single words (a space ends a tag), 25 at most:

python, fastapi, sqlalchemy, postgresql, alembic, next.js, react, typescript, tailwindcss, ag-grid, paypal, apimatic, claude, anthropic, mcp, elevenlabs, whatsapp, whapi, render, ed25519, playwright, vitest, pytest

### "Try it out" links

* https://openstall-collective.onrender.com
* https://github.com/FahadRamxan/OpenStall-Collective
* https://openstall-collective.onrender.com/seller-chat?seller=s_53a82b0aeae3 (a real WhatsApp chat on the hosted demo)

### Image gallery and video

The thumbnail is the home page's top. The gallery holds the live demo, the home page, the dashboard, a maker's chat and the receipt, from [docs/images](images), each with a caption that says so when it shows test mode. The demo video is public on YouTube: https://www.youtube.com/watch?v=zbl8VqHXcYc (2:51).

## Additional info (for judges and organizers only)

**Sponsor tools:** AG Grid, APIMatic and Render. **Code:** https://github.com/FahadRamxan/OpenStall-Collective. **Working demo:** https://openstall-collective.onrender.com. **New or existing:** new; the first commit is from October 30, 2026. The three eligibility statements and the Official Rules and Terms box are a person's to tick, and Submit a person's to press.

### How it meets the main technology requirement

```text
PayPal, all on PayPal's free sandbox:
* Orders v2 with intent AUTHORIZE: one PayPal order holds the whole collective order; approving it only reserves the money.
* Payments v2: a partial capture of each maker's share when she proves she shipped, final_capture on the last share, and a void of what is left when a maker drops out.
* Payouts: pays each maker her captured share on her rail. Venmo payouts are simulated because the sandbox refuses them, and Hyperwallet for makers in Pakistan is simulated and labelled so.
* Order tracking: her courier and tracking number added to her capture on the PayPal order.
* Webhooks: every event checked with PayPal's webhook signature verification and applied exactly once.
* Disputes: a "never arrived" dispute answered with the maker's proof of shipping (built and tested, not yet run on the sandbox).
* PayPal JS SDK buttons, and the Venmo button, on the stall pages and the approval page.
* PayPal's own MCP server (@paypal/mcp): an ops agent reads orders, disputes and tracking back from PayPal through tools that only read, and checks them against our records.
* APIMatic's PayPal Python SDK makes every Orders and Payments call, built with APIMatic's PayPal Context Plugin.

AI:
* Claude Sonnet 5.5 (Anthropic): the seller agents that negotiate within each maker's limits, the buyer's AI agent that uses the MCP storefront's tools, the listing reader and the courier receipt reader (vision), the plan explained in words, and the PayPal ops agent. Code checks every number they produce.
* ElevenLabs Scribe v2: voice notes in Urdu, Hindi, Spanish or English into text.
* ElevenLabs Eleven v4 Turbo: spoken answers to voice notes, in the maker's language.
* OpenAI Whisper: an optional second speech to text provider.
* Claude Code with APIMatic's PayPal Context Plugin: built the PayPal integration.
```

### Testing instructions

The values in brackets are pasted into the Devpost form by a person, never into this repository.

```text
Hosted demo (PayPal's real sandbox, so no real money moves; Claude, ElevenLabs and WhatsApp for real):
1. Open https://openstall-collective.onrender.com/demo and press "Run it with an AI agent" (or "Run the demo request"). When the page asks for the demo token, enter: [demo token]
2. Press "Open its approval page", then "Approve and pay with PayPal", and log in at PayPal's sandbox as the sandbox buyer: [sandbox buyer email] / [sandbox buyer password]. The receipt says PayPal is holding the order's total, and each maker is told in her language.
3. To be a maker yourself, open https://wa.me/923275157727?text=Start on a phone with WhatsApp, send the Start it writes for you, then a photo of something you make, and answer its questions. Your chat appears on the seller chat page, which is public, so send nothing private. If WhatsApp does not answer, press "Start as a new seller" on https://openstall-collective.onrender.com/seller-chat: it is the same chat in the browser.
4. https://openstall-collective.onrender.com/status shows what runs for real and the PayPal doctor's checks. "Reset demo" on /demo puts the demo world back.

Test mode on your machine (no keys or accounts; a simulated PayPal and stand ins for the models, labelled everywhere): follow "Try it (for judges)" in the README, then docs/judges.md, a walkthrough of the whole story in ten steps, pay on proof included, with what to press and what to expect.
```

### Overall experience integrating PayPal

```text
The sandbox was dependable and the core flow did what we needed: one AUTHORIZE order, a partial capture of each maker's share, a final capture, a void and Payouts, all proven on the sandbox on the first day. PayPal answering a resent capture with the first one made pay on proof safe to build, webhook signature verification worked as documented, and PayPal's MCP server gave our ops agent 28 tools that we could limit to reads. What cost us time: Orders v2 refuses intent AUTHORIZE with more than one purchase unit, so a hold with several payees was impossible and we moved to one order plus Payouts; the sandbox refuses Venmo payouts; Venmo and Pay Later are offered only to a US business account, so we could not prove them with our sandbox app; adding tracking is not idempotent, so we read the order's trackers before adding one; and Payouts does not reach Pakistan, where our makers are, so that rail is simulated through Hyperwallet.
```

### APIMatic Context Plugin experience

```text
What worked well: the plugin's process made us write a contract sheet (paypal-plan.md) before any code, with every SDK signature, model, enum and error union looked up in the SDK's own source instead of recalled, and the first five operations (create, get, authorize, capture and void an order) ran on PayPal's real sandbox the day we switched. Its testing guidance had us fake PayPal at the SDK's transport, so our tests check the exact request the SDK builds, and we turned the sheet into a cross check that runs with the tests and on our status page. Issues: the SDK is not on PyPI, so we install it from git, pinned to a commit; it has no Payouts, webhook verification or Disputes operations, so those stay on our own small REST client; its default retries had to be limited to reads, since a capture that got no answer may have landed; and PayPal's usual 401 bodies do not fit the SDK's error model, so they come out as decode failures and we resend once with a fresh token ourselves. Compared with the small REST client we wrote first, the move took a day and our old gateway tests still passed against the SDK.
```

### AG Grid experience

```text
Good. We used AG Grid Community (36.2) for seven tables: the seller agents' live offers with the code check's verdict and the allocator's plan on /demo, and orders, payouts, tracking, signed trust passports and Demand Radar on /dashboard. One shared theme built from our page's colour tokens made every grid follow light and dark mode, pinned columns and a pinned total row keep the key numbers in view, and rows fed from our live event stream update as the agents work. Every page passes our axe accessibility check (WCAG 2.1 AA) in light and dark mode. The one thing we designed around: the grids need room, so /demo uses two columns only from 1280 pixels wide. We did not use AG Charts or AG Studio.
```

### AI tools used while building it

```text
Claude Code (Claude Opus 5.5) wrote, tested and documented most of the code with us, with APIMatic's PayPal Context Plugin installed for the PayPal integration. Inside the product: Claude Sonnet 5.5 (the seller agents, the buyer's AI agent, the listing and receipt readers, the plan in words and the PayPal ops agent), ElevenLabs Scribe v2 (voice notes to text) and Eleven v4 Turbo (spoken answers), and OpenAI Whisper as an optional speech to text provider. ElevenLabs Eleven v3 voiced our demo video.
```
