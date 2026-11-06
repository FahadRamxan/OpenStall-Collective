# OpenStall Collective

OpenStall Collective lets small sellers who only use WhatsApp sell to AI shopping agents. A seller sends photos and a voice note, and AI turns them into listings that any agent can read and buy from. Each seller has an agent that negotiates within limits the seller sets. When an order is too big for one seller, the system splits it across several sellers. The buyer approves one PayPal checkout that only reserves the money, and each seller is paid when she photographs her shipping receipt.

Built for the PayPal AI Hackathon. Everything runs in the PayPal sandbox, or in test mode on a simulated PayPal; no real money moves. It is still being built: [What works today](#what-works-today) and [Build progress](#build-progress) say what runs now and what does not yet, such as a real AI agent as the buyer.

## Try it (for judges)

**The hosted demo is not live yet.** It will be at https://openstall-collective.onrender.com, on PayPal's sandbox, before judging; this section will say so when it is. Until then, run it on your machine in test mode, which needs no keys and no accounts.

### Run it in test mode (about five minutes)

You need Python 3.11 or newer, Node 24.15 or newer (or 26; not 25), and git. In a terminal:

```bash
git clone https://github.com/FahadRamxan/OpenStall-Collective.git
cd OpenStall-Collective
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python scripts/seed_demo.py --reset --with-amina --demo-order
uvicorn openstall_api.main:app --port 8000
```

On Windows PowerShell, activate the virtual environment with `.venv\Scripts\Activate.ps1` and copy the settings with `copy .env.example .env`. The `.env` starts in test mode (`OPENSTALL_MODE=fake`): a simulated PayPal, WhatsApp and AI model stand in for the real ones, the same on every run, and every page says so.

Leave the API running, and in a second terminal, from the same folder:

```bash
cd apps/web
npm ci
npm run dev
```

Then open **http://localhost:3000/demo**.

### Walk the story

[docs/judges.md](docs/judges.md) walks you through it step by step, with what you should see at each one. In short, on `/demo`:

1. **Run the demo request.** A scripted buyer agent asks OpenStall's MCP storefront for 40 hand-embroidered cushion covers at most $30 each. Five makers' agents make offers; code refuses two prices over the buyer's maximum and the agents come back under it; plain code splits the order 12 / 11 / 10 / 7 across four makers, $815.00.
2. **Open its approval page**, and approve it on the simulated PayPal page. PayPal only holds the $815.00: nothing is taken yet.
3. **Back on `/demo`**, each maker's phone shows her order in her own language: Urdu, Hindi, Spanish, English.
4. **Play Priya from her phone:** send her courier receipt, then reply "हाँ" when OpenStall reads the tracking number back to her. Her share is captured and paid out, and her tracking goes on the PayPal order. Amina, in Pakistan, is told to wait instead: no payout rail reaches Pakistan yet.

The same walkthrough runs as an automated browser test on every change (`apps/web/e2e/live-demo.spec.ts`).

### Use your own AI agent

The API's MCP storefront is at **http://localhost:8000/mcp** (Streamable HTTP). Point any MCP client at it, or use the two included ones, from the repo folder with the virtual environment active:

```bash
python scripts/try_mcp.py "cushion covers"
python scripts/run_demo_request.py
```

The first searches the listings. The second plays the buyer agent's whole request (search, quote, draft order, approval link) and prints each step; open the link it prints to approve the order. No tool can approve, reserve, capture, refund or pay out: a person approves every order.

### On PayPal's sandbox

Set `OPENSTALL_MODE=sandbox` in `.env`, with a PayPal sandbox REST app's `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` (and `ANTHROPIC_API_KEY` for the AI agents, `OPENAI_API_KEY` for voice notes). Approving an order then goes to PayPal's sandbox checkout, where you sign in as a sandbox personal account from your PayPal Developer Dashboard. `/status` shows which services are connected and names any missing key. In sandbox mode the seeded makers cannot be played from `/demo` (test-mode controls are off); a maker proves she shipped from her own WhatsApp or web chat.

## What works today

Being built step by step; each step is tested, wired into the web app, tested in a browser, then pushed.

- **Pay-on-proof with PayPal.** `/approve/{order}` shows each maker's share. Approving creates one PayPal order (intent AUTHORIZE) for the whole total, and the receipt shows PayPal holding the money. Each share is captured on its own when she ships, or released if she cannot deliver, and she is paid on the payout rail her country allows: PayPal Payouts; Venmo for a US maker (simulated in the sandbox, where PayPal does not run Venmo payouts); her bank account through Hyperwallet for a maker in Pakistan, where PayPal Payouts does not reach (her share is captured as usual; the Hyperwallet payout is simulated and labelled so, as no Hyperwallet account is connected). Verified, idempotent PayPal webhooks confirm each step.
- **Proven on PayPal's real sandbox:** one authorization, several partial captures with tracking on each, a final capture, a void, a payout, and OpenStall's own Approve flow end to end. See [docs/day-one-checks.md](docs/day-one-checks.md).
- **Built on APIMatic's PayPal SDK,** with APIMatic's PayPal Context Plugin (below).
- **Sellers chat on WhatsApp or in the browser.** A verified Twilio webhook stores their messages, photos and voice notes; `/seller-chat` is the same chat as a phone in the browser. One handler serves both.
- **Voice notes become text.** Each voice note a seller sends is turned into text before her message is stored, kept word for word under it (never translated, so a wrong reading can be traced to the recording), and the language it was heard in is saved on her profile if she has none yet. One that cannot be heard is kept, and she is asked to send it again or type it. In test mode, `/seller-chat` can attach a sample voice note, heard as Amina's words from the story in Urdu.
- **A maker who talks in voice notes is answered aloud.** Each answer to a voice note is also spoken, in her language, and kept under the answer in her chat; on WhatsApp it follows the text as a voice note. The words stay the template's; the voice only reads them out. An answer that cannot be spoken still goes as text.
- **Her chat becomes a draft listing.** While a seller has no live listing, everything she has sent (photos, typed words, voice notes as text) is read into a draft listing in the spec's fields: what it is, a description, category, colours, price, how many a week, how many days delivery takes, city and photos. Her price, capacity, delivery time and city are kept only with the words she used for them, found in what she actually said; anything else is left to ask. Each answer tells her the listing so far and asks one short question for what it still needs, in her language (Urdu, Hindi, Spanish or English, from her first voice note): a photo first, then each missing field, then her limits, the lowest price she would take for one and the fewest days she needs to make an order. A bare answer ("9") counts as the answer to the question asked. `/seller-chat` shows the draft and her limits under her chat, with her own words beside each number and the question asked now, and the live feed follows it. In test mode, a sample photo of Amina's cushion cover can be attached too.
- **Her yes publishes it.** Once nothing is left to ask, she gets her whole listing and her limits back in her language and must reply yes ("ہاں", "हाँ", "sí", a thumbs up); anything else is read as a change. Her yes publishes it at once: a live listing with her photos and her own words kept beside it, her seller policy set from her limits (her largest discount follows from her price and her lowest price), found by search, the catalog and the MCP storefront, with her stall page linked in the reply. Nothing is published before she says yes.
- **Stalls and the agent storefront.** Five seeded makers with stall pages and trust records (marked as demo data), and an MCP server at `/mcp` that a buyer's AI agent can order through:
  - `search_products`: the live listings, with filters for price, quantity and deadline; each result has the maker's trust record and how many she can still make by the deadline. Every search is logged, and `/demo` lists them live, with the ones that found nothing in amber.
  - `get_product` and `get_trust_card`: a listing in full, and a maker's trust card (its signature says "pending" until passports are signed). Agents without MCP read the same listings at `/catalog.json` and a short guide at `/llms.txt`, and each stall page has a "For AI agents" box with these links and the MCP address to copy.
  - `request_quote`: asks every matching maker's seller agent for an offer, and returns the valid offers, the split and its explanation.
  - `create_collective_order`: turns that plan into one draft order, with every price and total worked out by OpenStall.
  - `checkout` and `get_order_status`: OpenStall's own approval page for the agent to send its human, and where each maker's share stands.
  - None of them spends money: no tool can approve, reserve, capture, refund or pay out, and a test calls every tool with a payment gateway that fails if anything reaches it. A person approves the draft before PayPal holds anything; the approval page says when an AI agent asked for the order, and `/demo` shows the latest order and its approval link.
- **The offer rules, shown before any offer.** `/demo` lists each maker's lowest allowed price (her floor, or her list price less her maximum discount) and how many she can still make and ship in 30 days, worked out by the same code that will check every offer. Reserved orders use up her capacity, and the panel updates live.
- **Seller agents that negotiate within limits, checked by code.** Each maker's agent proposes a price and a sentence to the buyer; code checks it against her limits and the buyer's maximum, and a refused price goes back with the reason, at most twice. A buyer's words can never talk a price below her floor. A quote request asks every matching maker's agent side by side, each within a time limit, for up to 3 rounds. `/demo` shows the buyer's request, the round, and every proposal live in an AG Grid table.
- **One order split across makers by plain code.** When a quote's rounds are done, the allocator fills the quantity from the cheapest valid offers first: for the story, 12 from Amina, 11 from Priya, 10 from Lucía and 7 from Grace, $815.00. `/demo` shows each maker's share as a bar and the plan as a table with its total, or says how many are possible when the offers fall short. The split is also explained in two or three plain sentences, on `/demo` and at the top of the approval page; code checks every number in them against the plan, and a template stands in for words that fail the check. The agents run on Claude in sandbox mode and on deterministic stand-ins in test mode.
- **Each maker is told about her share, in her language.** Once PayPal holds the order, each maker whose share is reserved gets one message in Urdu, Hindi, Spanish or English: the order, the item, how many, her price, the date to ship by, where it goes and how she is paid. Code writes it from a template, so every number is the order's own. It goes on WhatsApp when she has a number, and otherwise to her chat on `/seller-chat` (where the seeded makers' messages appear). A maker no payout rail can reach yet, such as Amina in Pakistan, is asked to wait for us before she ships, rather than promised payment. The receipt says who was told, where and in which language, with a link to her chat; `get_order_status` gives the agent the same; and nobody is told twice. The address is only the buyer's city for now: collecting the street address is still to come.
- **Snap the receipt, get paid.** A maker whose share PayPal holds sends a photo of her courier receipt, on WhatsApp or in the web chat. The model reads the courier and the tracking number, and she is asked in her language to confirm them; a number it cannot read, she types. Only her "yes" moves money: her share is then captured from the order's one PayPal authorization and paid out, and she is told she is paid. Her tracking then goes on that payment at PayPal, with PayPal's own code for her courier, so the buyer sees it on their PayPal order. A maker no payout rail reaches yet keeps her confirmed tracking and is told she is paid once it does. The receipt page shows each maker's tracking with her receipt photo, and `get_order_status` gives the agent the tracking. In test mode, `/seller-chat` plays a seeded maker: send her receipt photo and reply as her.
- **The order heals itself.** A maker who cannot make her share says so in her chat, in her language ("I can't make this order"), and is asked to confirm: nothing moves on her words alone. Her yes sends her share back to the buyer, never charged, and OpenStall asks every other matching maker's agent for her units, by the same deadline and at most the buyer's price. What they offer becomes a top-up order that points at the first; the buyer approves it on its own page, like any order, and its makers are told then. The receipt, `/demo`'s Payments panel and `get_order_status` show the top-up and its approval link. In test mode, **Grace can't make it** on her phone on `/demo` plays it.
- **Delivery and the end of an order.** PayPal's order trackers only say a parcel shipped, so the buyer, who receives the parcels, confirms each one on the receipt (**Confirm delivery**). Her share is then delivered, with the day it arrived and whether by its delivery date (for her trust passport); she is told in her language; no money moves, since she was paid when she shipped. Once every parcel that shipped has arrived and the rest were released, the order is complete, and the receipt shows what was paid to the makers and what came back to the buyer. `get_order_status` and the live feed follow it.
- **Disputes answered with the proof.** When a buyer opens a PayPal dispute saying a maker's parcel never came, PayPal's webhook brings it to OpenStall, which finds her share by its capture and answers the dispute with her proof of shipping (`provide-evidence`: her courier, her tracking number, the buyer's own confirmation that it arrived if they gave one, and her courier receipt photo), once, after the webhook's commit. She is told in her language that PayPal has her proof and she need do nothing, and again when PayPal decides. A dispute her proof does not answer (an item not as described, say) waits for a person, and the receipt says why. A dispute PayPal decides for the buyer counts against her trust passport. Nothing moves money on OpenStall's side: PayPal decides. In test mode, **Dispute this parcel at PayPal** on a paid share of the receipt plays it, and simulated PayPal decides at once.
- **Signed trust passports anyone can check.** A maker's trust card (`/passport/{seller_id}`, the same as the MCP tool `get_trust_card`) is her signed passport itself: OpenStall signs exactly its fields with Ed25519. The public key is at `/passport/public-key`; `/passport/{seller_id}/verify` checks her stored card, and `POST /passport/verify` checks any card sent to it, so a card with one number changed fails. Her stall's For AI agents box links **Check its signature**. Test mode signs with a fixed test key, and says so.
- **The tamper check, live on `/demo`.** **Check a trust passport** loads a maker's signed trust card and checks its signature twice: in your browser, with OpenStall's public key and the browser's own Ed25519 (Web Crypto), and by OpenStall's `POST /passport/verify`. Change any number and press **Check the signature**: both say it no longer matches. **Put it back**, and it checks out again.
- **Try to break it, on `/demo`.** Eight attacks, each a real attempt through the same code a real request goes through: a price talked down to $1.00, an AI agent capturing the payment through MCP, a smaller total sent by the browser, a forged PayPal webhook, an order reserved that no person approved, a maker paid before she shipped, a flood of calls to the MCP storefront from one address, and a trust card with one number raised. **Try every attack**: each is refused by that code, and the live feed records each refusal (`security.rejected`). Nothing an attack touches is kept. `POST /api/guardrails/run` runs them all (in sandbox mode, with the demo token).
- **Trust passports update after each delivery.** When a buyer receives a maker's parcel, her trust passport is worked out again (orders delivered, on-time rate, dispute rate, her score) and signed again with OpenStall's key. It is worked out from facts each time: her history (made-up numbers for the seeded makers, which stay marked as demo data) and every parcel of hers a buyer received, on time or not by its delivery date. Her stall page, her trust card for agents and search results say how many of her orders came through OpenStall; the live feed shows the old and new score. A maker who joined through the chat gets her first passport once her photos can be checked (not built yet).
- **A materials advance for a trusted maker.** A maker whose signed trust score is 0.90 or more can ask in her chat, in her language, for part of a reserved share ahead, to buy her materials: a quarter of it, paid by OpenStall from its own balance by Payouts on her rail, never taken from the buyer. When she ships, her share is captured whole and her payout is the rest; if she never ships, the advance is OpenStall's loss, not the buyer's. In test mode, **Grace asks for an advance** on her phone on `/demo` plays it.
- **A buyer agent you can run.** `python scripts/run_demo_request.py` plays the story through the MCP storefront (search, quote, draft order, approval link) and prints each step; add `--pause` to step through it for a recording, and `--url` to point it at the hosted demo. On `/demo`, "Run the demo request" does the same on the server, a stepper follows it from Search to Approval, and "Reset demo" puts the seeded world back. In sandbox mode both buttons need the `DEMO_RUN_TOKEN`.
- **A real AI agent as the buyer.** On `/demo`, **Run it with an AI agent** hands the story's request, in words, to a buyer's AI agent that chooses the MCP storefront's tools itself, turn by turn, until it has the approval link for its person: Claude (`LLM_MODEL`) in sandbox mode with `ANTHROPIC_API_KEY`, test mode's stand-in otherwise. `/demo` shows each tool it chose and its answer, and the approval page says an AI agent asked for the order (`POST /api/demo/run-agent`).
- **The whole story on `/demo`, live.** In the story's order: the buyer agent's request, the offer rules and every checked offer, the split, the order and its one PayPal approval, each maker's payment (reserved, told, paid on proof, tracking on PayPal), and the makers' own phones, each showing her order in her language, her courier receipt and her payment as they happen, and a maker's trust passport you can tamper with. The live feed of everything that happens sits beside it. In test mode you can play a seeded maker from her phone: send her courier receipt, then say yes in her language.
- **Buy from a stall with PayPal's buttons.** Each listing on a stall page has **Buy from {maker}**: how many, the city it ships to, and PayPal's own buttons (the JS SDK, intent authorize) in sandbox mode, or **Buy with simulated PayPal** in test mode. The order is drafted at her list price with the first day she can deliver (her lead time, weekly capacity, ship days and what she already owes), reserved when the person approves, and she is told in her language, with the city; she is paid on proof like every maker.
- **The home page.** What OpenStall is; the numbers right now (makers with a live listing, orders approved, what makers were paid on proof, parcels delivered, agents' searches this week, from `GET /api/overview`); how it works in six steps, each linking to where it can be seen; the MCP address and feeds for AI agents; and the PayPal pieces it is built on.
- **The dashboard, in AG Grid.** `/dashboard` lists the recent orders (top-ups marked), each maker's share and payout, every parcel's tracking (on PayPal, delivered, on time), and the trust passports with whether each signature holds. It follows the live feed.
- **Demand Radar.** Searches that found nothing are grouped by their words (plural and singular alike, filler words left out), counted for the week, and matched to the maker whose listings share the most describing words, the most trusted first. The dashboard leads with the biggest group: in the seeded world, "23 agents searched for ceramic mugs this week. Nobody sells them.", marked as seeded demo searches. **Send the tip to Noor** sends a group's tip to its maker, in her language, once a week.
- **Security and abuse limits.** What costs money or fills the database is limited, in a sliding window, and refused with 429 and Retry-After: each client gets 600 API requests and 120 MCP calls a minute, 20 stall orders and 30 demo runs an hour; in sandbox mode, where real AI services cost money, OpenStall takes 60 quote requests (each starts the makers' AI agents) and 12 buyer-agent runs an hour from everyone together, and 30 messages per seller every 10 minutes, dropped before any photo or voice note is read. Behind Render's proxy a client is the address the proxy added to X-Forwarded-For (`PROXY_HOPS`), never one the client wrote; this computer is not counted. A refusal is in the live feed once a window, with a hash of the address, never the address. Bodies over 17 MB are refused before they are read, and every page and API answer carries security headers (no framing, no type guessing, no camera or location). `python scripts/scan_secrets.py` looks for secrets in every tracked file and the whole git history, and for this computer's own `.env` values anywhere: it runs with the tests, and the repository is clean.
- **A status page** at `/status`: the mode, the database, PayPal's token and the SDK in use.
- **The PayPal doctor.** `/status` checks whether this setup is ready to hold a buyer's money and pay the makers, and says what to do for each check: where the money goes (test mode, PayPal's sandbox, or its live host), PayPal's keys and a token, the registered webhook read back with its URL and events, the makers' sandbox payout accounts, and the APIMatic cross-check (below). `python scripts/doctor.py` prints the same report in a terminal (`--checks` for the checks only) and exits with 1 when a check fails. It names a missing key, never its value. Under it, **PayPal products** lists every PayPal product with how far it has got and the evidence.
- **Test mode:** a simulated PayPal (labelled as such everywhere), Twilio and AI models, so everything runs offline and in tests.

## How it uses PayPal

Pay-on-proof, on the payouts path (one platform order, each maker paid separately), proven step by step on PayPal's real sandbox ([docs/day-one-checks.md](docs/day-one-checks.md)):

- **Orders v2, intent AUTHORIZE:** one PayPal order for the whole collective order, with each maker's share as an item, so approving it only reserves the money.
- **Payments:** a partial capture of each maker's share when she proves she shipped (`final_capture` on the last), and a void of whatever is left when a share is released.
- **Payouts:** each maker paid on her payout rail, PayPal or, for a US maker, Venmo (simulated on the sandbox, which refuses Venmo payouts); a maker in Pakistan, where Payouts does not reach, is paid to her bank through Hyperwallet (simulated: no Hyperwallet account is connected).
- **Order tracking:** each maker's tracking number and courier attached to her capture on the PayPal order.
- **Webhooks:** every event verified with PayPal (`verify-webhook-signature`) and applied exactly once.
- **Disputes:** a buyer's dispute that a parcel never came is answered with the maker's proof of shipping (`POST /v1/customer/disputes/{id}/provide-evidence`, on our own client, as APIMatic's SDK has no disputes).
- **APIMatic's PayPal Python SDK** for every Orders and Payments call ([below](#built-with-apimatics-paypal-context-plugin)). Every write carries an idempotency key made from our own ids, and is never resent blindly.

Every PayPal product OpenStall uses or plans to, and how far it has got (`packages/paypal/openstall_paypal/products.py`; [/status](http://localhost:3000/status#paypal-products) shows the evidence for each):

| Product | How far it has got |
| --- | --- |
| OAuth 2.0 access tokens | Proven on the sandbox |
| Orders v2, intent AUTHORIZE | Proven on the sandbox |
| Payments v2: captures and voids | Proven on the sandbox |
| Order tracking | Built, not yet run on the sandbox |
| Payouts | Proven on the sandbox |
| Payouts to Venmo | Simulated |
| Hyperwallet | Simulated |
| Webhooks | Built, not yet run on the sandbox |
| JavaScript SDK buttons | Built, not yet run on the sandbox |
| Disputes | Built, not yet run on the sandbox |
| Braintree | Not built yet |
| PayPal's MCP server | Not built yet |
| Venmo and Pay Later at checkout | Not built yet |

## How it uses AI, and where code decides

- **Buyer agents** shop through an MCP storefront: search, product and trust cards, quotes, a draft collective order, an approval link, and order status. None of the tools can move money.
- **Seller agents** (Claude in sandbox mode) propose each maker's price and a sentence to the buyer. Code checks every price against her limits and the buyer's maximum, and refuses one that breaks a limit, whatever the buyer wrote.
- **The split** is plain code: cheapest valid offers first, each maker up to what she can make by the deadline. Claude explains it in two or three sentences, and code checks every number in them against the plan.
- **Voice notes** are turned into text by ElevenLabs' Scribe (`scribe_v2`; or OpenAI's `whisper-1` with `SPEECH_PROVIDER=openai`), word for word in the language she spoke; the language it hears goes on her profile. Spoken Urdu and Hindi sound alike, so her known language goes with each voice note as a hint: Urdu for a number in Pakistan.
- **Spoken answers** are read out by ElevenLabs' Eleven v4 Turbo, in her language, for a maker who sends voice notes.
- **Listings** are drafted by Claude with vision from her photos and words. Code keeps a price, a weekly capacity, a delivery time, a city or one of her limits only when the model quotes the words she used for it, those words are in what she said, and they name what the number counts (dollars, a week, days) or answer OpenStall's question for it, so nothing she did not say is listed.
- **Courier receipts** are read by Claude with vision: the courier and the tracking number. Code checks the number, and the maker confirms it before anything is paid.
- **Messages to makers** are written by code from templates in her language, because they carry the numbers she acts on.

## What is simulated, and what is not built yet

- **Test mode** (the default `.env`) simulates PayPal, WhatsApp and the AI models, and every page says so ("simulated PayPal", "Test mode").
- **The five makers are demo data,** marked `seeded_demo` wherever they appear, with placeholder photos.
- **Not connected yet:** Hyperwallet, so Amina's bank payout in Pakistan is simulated in every mode (on PayPal's live host she would have no rail rather than a pretend payout), and a buyer's street address (makers are told the buyer's city).
- **Not built yet:** changing a listing once it is live. [Build progress](#build-progress) lists every step.

## Build progress

OpenStall is built in 58 numbered steps; each is tested, wired into the web app, tested in a browser, then pushed on its own. As of November 6: **48 done, 3 partly done, 7 not started.** [CLAUDE.md](CLAUDE.md) lists every step with its state and commit.

| Part | Done | Partly done | Not started |
|---|---|---|---|
| Foundation | 01–06 | | |
| PayPal | 07, 09, 10, 11, 13 | 08: the sandbox proof ran and is recorded, its script is not in the repo yet; 12: the Render blueprint, the deploy needs an account | |
| Sellers on WhatsApp | 14–19 | | |
| Agent storefront | 20, 21 | | |
| Negotiation and the collective | 22–30 | | |
| After payment | 31–34 | | |
| Trust passports and the materials advance | 35, 36, 37, 38 | | |
| The order heals itself; guardrails | 39, 40 | | |
| Pages and design | 41, 42, 43, 44 | | 45 design pass |
| Hardening and submission | 46 | 49: this README and [the judges' walkthrough](docs/judges.md); the hosted demo's address and the sandbox buyer login come at submission | 47, 48, 50 |
| More of PayPal | 51, 52, 53, 56, 58 | | 54 Braintree, 55 ops agent, 57 Venmo and Pay Later |

Next: the hosted demo once there is a Render account, and the Devpost draft; then the design pass (45) and the whole story end to end (47).

## Run it locally, in more detail

[Try it](#try-it-for-judges) has the quickest way in. This section is for working on the code. You need Python 3.11 or newer.

```bash
python -m venv .venv
```

Activate it. On Windows PowerShell run `.venv\Scripts\Activate.ps1`. On macOS or Linux run `source .venv/bin/activate`.

```bash
pip install -e ".[dev]"
cp .env.example .env
uvicorn openstall_api.main:app --reload
```

Load the demo world, the five seeded makers from the spec, with `python scripts/seed_demo.py --with-amina` (add `--reset` to start from an empty database). The API keeps its data in a SQLite file at `data/openstall.db` and brings the tables up to date when it starts. To use Postgres instead, set `DATABASE_URL` (see `.env.example`). After changing the tables in `apps/api/openstall_api/models.py`, make a migration with `alembic revision --autogenerate -m "what changed"`.

The API is then at http://localhost:8000, and the MCP storefront is at http://localhost:8000/mcp (Streamable HTTP).

It starts in **fake mode** (`OPENSTALL_MODE=fake`): PayPal, Twilio and the AI models are replaced by stand-ins that give the same answers every time, so it runs without any keys. To use the real PayPal sandbox, Twilio sandbox and AI models, set `OPENSTALL_MODE=sandbox` in `.env` and fill in the keys you have. The real PayPal (sandbox), Twilio (WhatsApp), Claude (the language model), ElevenLabs (speech to text and spoken answers) and OpenAI speech to text adapters exist; OpenAI embeddings and Google Cloud Vision image search arrive later, and until one exists the status page lists it as "Not built yet". The web app's status page (http://localhost:3000/status) and `GET /api/status` show the mode and which services are ready, and name any missing key without showing key values.

Point any MCP client at the storefront, or, with the API running, use the included one in a second terminal:

```bash
python scripts/try_mcp.py "cushion covers"
```

Run the tests (they start their own server, so the API does not need to be running). They always run in fake mode and ignore your `.env`:

```bash
pytest
```

**Note for contributors:** this uses the MCP Python SDK 2.x, where `FastMCP` is now `MCPServer` (`from mcp.server import MCPServer`) and clients use `from mcp import Client`. Examples written for SDK 1.x need small changes.

### The web app

You need Node 24.15 or newer (Node 25 is not supported). With the API running, in a second terminal:

```bash
cd apps/web
npm install
npm run dev
```

The site is then at http://localhost:3000. Its tests are `npm test` (components, Vitest) and `npm run e2e` (UI tests with Playwright, which start their own API and web servers). See [apps/web/README.md](apps/web/README.md) for details.

## Before every push

There is no CI to catch a broken push, so run every check on your machine first:

```bash
python scripts/check_all.py
```

It runs `pytest`, then `mypy --strict` on the PayPal package, then, in `apps/web`, `npm run lint`, `npm test`, `npm run build` and `npm run e2e`. It stops at the first failure and ends with a summary of which checks passed, failed or did not run. Push only when it says all checks passed.

- It works from any folder and with any Python 3.11 or newer: pytest and the UI tests' API run on the repo's `.venv` when it exists.
- It needs the setup above: the Python packages, `npm install` in `apps/web`, and Playwright's browser (`npx playwright install chromium` in `apps/web`, once).
- The UI tests make their own production build, so a full run takes a few minutes.

## The hosted demo

[render.yaml](render.yaml) runs the API, the web app and a Postgres database on Render, and every push to `main` deploys them.

- Web app: https://openstall-collective.onrender.com
- API: https://openstall-collective-api.onrender.com (its health check is `/health`)

These addresses work once the blueprint is created; it is not created yet. To create it (once): in the Render dashboard choose **New > Blueprint** and pick this repo. Render asks for the values marked `sync: false`; leave the ones you do not have yet empty. The API starts in fake mode. Once the PayPal sandbox keys are set, change `OPENSTALL_MODE` to `sandbox` in the dashboard. If Render gives a service a different address, change `PUBLIC_BASE_URL`, `WEB_BASE_URL` and `NEXT_PUBLIC_API_BASE_URL` to match.

Both services run on Starter and the database on basic-256mb. A free Render database is deleted 30 days after it is created, and free services sleep when idle, but the demo must stay up until judging ends on December 15 (see [docs/decisions.md](docs/decisions.md)).

To check a deploy, open `/status`, which names the deployed commit. Then run the smoke tests and an MCP search against it:

```bash
cd apps/web && E2E_BASE_URL=https://openstall-collective.onrender.com npm run e2e:smoke
```

```bash
python scripts/try_mcp.py "cushion covers" --url https://openstall-collective-api.onrender.com/mcp
```

## Built with APIMatic's PayPal Context Plugin

OpenStall's PayPal Orders and Payments calls (creating the checkout, reading the order, reserving it, then capturing or voiding each maker's share) go through [APIMatic's PayPal Python SDK](https://github.com/context-plugins/paypal-python-sdk), and the integration was written with [APIMatic's PayPal Context Plugin](https://github.com/context-plugins/plugin-marketplace) driving the coding agent:

- **The plugin's skills ran the build.** `python-integrate-paypal` set the order of work and its gates, `python-getting-started` was the lookup layer, and the companion skills (client initialization, authentication, calling endpoints, models, error handling, configuration and resilience, testing) were loaded before any code was written.
- **A contract sheet came first.** [paypal-plan.md](paypal-plan.md) holds every SDK fact the code relies on, each looked up in the SDK's own map and source rather than recalled: signatures, wire names, error unions, enum members, the retry policy and the duplicate-claims table. No project file was touched until it had no open lookups.
- **The SDK is pinned** in `pyproject.toml` to commit `143e57f2a372` (by its full hash) of its repository (version 2.29), the code the sheet was checked against. `pip install -e ".[dev]"` installs it, and `/status` names the SDK the gateway uses.
- **Tests fake PayPal at the SDK's own seam:** a fake transport passed as `custom_http_client`, so they check the request the SDK really builds, and every failure kind the plugin lists (refusals, bad credentials, never-sent and may-have-landed transport failures, unreadable answers, the retry policy). See `packages/paypal/tests/test_sandbox_gateways.py`.
- **What the SDK does not cover stays on our own client:** PayPal Payouts and webhook verification.
- **Cross-checked on every run.** The PayPal doctor (`/status`, `python scripts/doctor.py`) checks that the sheet, the gateway's calls and the installed SDK still agree: every SDK call has its row in the sheet and every row is called; each call passes exactly the keywords its row says; the installed SDK has each operation with those parameters, by its own signatures; and the sheet, the pin and the installed SDK are one commit. `packages/paypal/tests/test_crosscheck.py` runs it with the tests.

The design choices are in [docs/decisions.md](docs/decisions.md) (November 3: the APIMatic PayPal SDK). To use the plugin yourself with Claude Code, install it once:

```bash
npx context-plugins install paypal --targets claude
```

## Repository layout

```
apps/api/        FastAPI: webhooks, orders, PayPal, passports, MCP server at /mcp
apps/web/        Next.js: stall, seller-chat, demo, approve, dashboard
packages/        agents, allocator, paypal, trust
scripts/         demo and helper scripts
docs/            day-one checks and decisions
paypal-plan.md   the APIMatic contract sheet for the PayPal SDK
CLAUDE.md        how this repo is built, and the state of every build step
```

## Demo data

The five demo makers (Amina, Priya, Lucía, Grace and the backup Noor), their listings and their trust records are seeded and marked `seeded_demo` everywhere they appear. They are not real sellers or real sales. Their product photos are labelled placeholders until the team adds its own.

## License

MIT. See [LICENSE](LICENSE).
