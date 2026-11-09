# OpenStall Collective: the Devpost submission text

The text for the Devpost form, kept in the repository so it stays in step with the code. Every claim here is in [README.md](../README.md) and checked by the tests; anything simulated says so. Fill in the parts marked **(at submission)**.

**Tagline:** WhatsApp makers become one supplier that AI shopping agents can buy from, and PayPal pays each maker only when she proves she shipped.

---

## Inspiration

Where we live, in Pakistan, a huge number of small businesses run entirely on WhatsApp. A woman stitching embroidered cushion covers at home shares photos in chats, takes orders by voice note, and gets paid by whoever she trusts.

At the same time, shopping is moving to AI agents. People ask an assistant to find 40 cushion covers for an office and let it buy. Those agents only buy from big stores with clean catalogs and checkout APIs, so the sellers we know best are about to become invisible to the next generation of shoppers. On her own, a home maker also cannot take a 40-unit order, bargain with an AI buyer, or ask a stranger to trust her with the money first.

So we asked: **what if the smallest sellers could join the agent economy together, as one supplier, and be paid the moment they ship?**

## What it does

OpenStall pools makers who only use WhatsApp into one collective supplier that AI agents buy from through an MCP storefront. The story the demo plays, step by step:

1. **A stall from a chat.** A maker sends a photo and a voice note in Urdu. The voice note becomes text, her photo and words become a draft listing, and OpenStall asks her, in her language, one short question at a time for what is missing: her price, how many a week, delivery days, her city, then her limits (the lowest price she would take, the fewest days she needs). Her "ہاں" (yes) publishes it.
2. **A buyer's AI agent asks for 40 cushion covers** at most $30 each, through the MCP storefront (search, product and trust cards, `request_quote`).
3. **Seller agents bid within each maker's limits.** Each maker's agent proposes a price and a sentence to the buyer's agent; code checks every price against her floor and the buyer's maximum, and a refused price goes back to her agent with the reason (up to 3 rounds), so no buyer's words can talk a price below her floor.
4. **The order is split across makers by plain code**: 12 from Amina, 11 from Priya, 10 from Lucía and 7 from Grace, $815.00, explained in two sentences whose every number code checks against the plan.
5. **A person approves one PayPal checkout that only reserves the money**: one PayPal order, intent AUTHORIZE. No agent tool can approve, capture, refund or pay out.
6. **Each maker is told on her phone, in her language** (Urdu, Hindi, Spanish or English), with the numbers from the order itself.
7. **Pay-on-proof.** A maker photographs her courier receipt. The model reads the courier and tracking number, she confirms, and only then is her share captured from the one authorization and paid out on her rail. Her tracking goes on the PayPal order, so the buyer sees it at PayPal.
8. **The order heals itself.** A maker who cannot deliver says so; on her yes her share is released, never charged, and the other makers' agents are asked for her units as a top-up order.
9. **Signed trust passports.** Every delivery updates a maker's record (orders delivered, on-time rate, disputes), signed with Ed25519, which any agent can verify; change one number and the signature fails, shown live in the browser. (Its photo-originality score is seeded demo data for now: no image check runs yet.)
10. **Demand Radar.** Searches that found nothing are grouped and sent back as tips in her language: "23 agents searched for ceramic mugs this week. Nobody sells them." (seeded demo searches, marked so).

## How it uses PayPal

Pay-on-proof on the payouts path, proven step by step on PayPal's real sandbox:

- **Orders v2, intent AUTHORIZE:** one order for the whole collective order, each maker's share an item; approving only reserves the money.
- **Payments v2:** a partial capture of each maker's share when she proves she shipped (`final_capture` on the last), and a void of whatever is left when a share is released.
- **Payouts:** each maker paid on her rail. Venmo for a US maker (simulated in the sandbox, which refuses Venmo payouts); a maker in Pakistan, where Payouts does not reach, is paid to her bank through Hyperwallet (simulated and labelled so: no Hyperwallet account is connected).
- **Order tracking:** her courier and tracking number on her capture, with PayPal's carrier codes (`OTHER` with a name for Pakistani couriers).
- **Webhooks:** every event verified with `verify-webhook-signature` and applied exactly once.
- **Disputes:** a buyer's "never arrived" dispute answered with the maker's proof of shipping (`provide-evidence`).
- **PayPal's JS SDK buttons** on each maker's stall page, intent authorize.
- **Venmo at the approval**, for a buyer in the US: the order is made for Venmo and held, paid on proof and released like any order (simulated in test mode; PayPal offers it only to a US business account, which the sandbox app is not).
- **PayPal's own MCP server** (`@paypal/mcp`): an ops agent reads each order, its disputes and its tracking back from PayPal and checks them against OpenStall's records, offered only PayPal's tools that read. Run on the sandbox: 28 tools listed, a real order's status, amount and disputes agreed.
- **Every write PayPal can deduplicate carries an idempotency key from our own ids, and none is resent blindly**: a lost answer is read back from PayPal, and tracking, which PayPal does not deduplicate, is checked against the order's trackers before it is sent.

Proven on the real sandbox (docs/day-one-checks.md): one authorization, several partial captures with tracking on each, a final capture, a void, a payout, PayPal answering a resent capture with the first, and OpenStall's own Approve flow end to end.

## Built with APIMatic's PayPal Context Plugin

Every Orders and Payments call goes through **APIMatic's PayPal Python SDK** (2.29, pinned by commit), and the integration was written by Claude Code with **APIMatic's PayPal Context Plugin** installed (`npx context-plugins install paypal --targets claude`), following the plugin's process: the contract sheet [paypal-plan.md](../paypal-plan.md) first (every SDK signature, model, enum, error union and the retry policy looked up, not recalled), then the code, `mypy --strict`, and tests that fake PayPal at the SDK's own transport seam. An APIMatic cross-check runs with the tests and on `/status`: every SDK call has its row in the sheet, passes exactly the keywords its row says, exists in the installed SDK by its own signatures, and the sheet, the pin and the installed SDK are one commit. [docs/apimatic.md](apimatic.md) maps each SDK operation to the code that calls it, its tests and its sandbox run.

**For the form's Context Plugin question:** We used APIMatic's PayPal Context Plugin (the marketplace PayPal plugin, Python pack, on context-plugins/paypal-python-sdk) in Claude Code to build OpenStall's whole Orders and Payments integration: the plugin's `python-integrate-paypal` skill set the order of work, and its companion skills (client initialization, authentication, calling endpoints, models, error handling, configuration and resilience, testing) were loaded before any code. Its contract sheet is paypal-plan.md at the repo root. Six SDK operations are used (create_order, get_order, authorize_order, capture_authorized_payment, void_payment, create_order_tracking); the first five ran on PayPal's real sandbox on November 3. A cross-check keeps the sheet, the code and the installed SDK in step on every run.

## How it uses AI (Tools)

- **Claude (Anthropic, `claude-sonnet-5-5`)**: the seller agents that negotiate within each maker's limits; the buyer's AI agent that chooses the MCP storefront's tools itself; the listing reader (vision: her photos and words into a listing); the courier receipt reader (vision); the plan explained in words; and the PayPal ops agent. Code checks every number they produce.
- **ElevenLabs Scribe v2**: a maker's voice notes into text, word for word in her language, with her known language as a hint (spoken Urdu and Hindi sound alike). Proven on the real ElevenLabs.
- **ElevenLabs Eleven v4 Turbo**: answers to a voice note spoken back in her language.
- **OpenAI `whisper-1`**: an optional second speech-to-text provider.
- **Claude Code with APIMatic's PayPal Context Plugin**: building the PayPal integration (above).

**Run for real on November 9** (`claude-sonnet-5-5`): the five makers' agents made five valid offers in one round, each with her own sentence; the split's explanation passed the number check; the buyer's AI agent chose search, quote, draft order and checkout by itself in 12 seconds; the listing reader took $18.00 and 4 a week only from Amina's own Urdu words; and the ops agent answered from eight read-only PayPal calls.

Where code decides, not the model: every price against her limits, the split (cheapest valid offers first, each maker up to what she can make by the deadline), every number in a sentence the model writes, every message to a maker (templates in her language), and every movement of money. Test mode runs deterministic stand-ins for every model, labelled as such.

## How it uses AG Grid

Seven AG Grid tables (Community, one shared theme in light and dark): on `/demo`, every seller agent's proposal with the code check's verdict, live, and the allocator's plan; on `/dashboard`, orders (top-ups marked), each maker's payout and rail, every parcel's tracking (on PayPal, delivered, on time), the trust passports with each signature checked, and Demand Radar's groups of searches that found nothing, all following the live event feed.

## Safety

No MCP tool moves money: a test calls every tool with a payment gateway that fails if anything reaches it. **Try to break it** on `/demo` runs nine real attacks through the code they target (a price talked down to $1.00, a capture tool through MCP, a smaller total from the browser, a forged PayPal webhook, an unapproved reservation, payment before proof, a flood of MCP calls, a tampered trust card, and a refund through PayPal's MCP server); each is refused and recorded. Per-client and global rate limits cap what real AI costs; a secret scan checks every file and the git history.

## Challenges we ran into

- **One checkout, many makers.** PayPal refuses intent AUTHORIZE with several purchase units, so a multi-payee order could not reserve the money. We moved to the payouts path: one order with one purchase unit, a partial capture per maker on its one authorization, then Payouts on her rail, and proved every step on the sandbox.
- **Making AI negotiation safe.** Models write persuasive offers and are bad at respecting numbers. The model writes the words; code checks every price, and a refused one goes back with the reason.
- **Messy real-world input.** Voice notes mix Urdu and English, and spoken Urdu is often heard as Hindi. We pass her known language as a hint, keep the transcript word for word, and ask a short question instead of guessing.
- **Money that must never move twice.** Every PayPal write is claimed in our database before it is sent, keyed by what it is for, with PayPal's idempotency keys from our own ids; a lost answer is read back, never resent.

## Accomplishments that we're proud of

- Pay-on-proof per maker inside one PayPal hold, proven on PayPal's real sandbox.
- An order that heals itself when a maker drops out, without charging the buyer for her share.
- Signed trust passports checked live in the browser with Web Crypto.
- About 1,560 Python tests, 310 component tests and 117 browser tests, including the whole thirteen-step story played twice in a row, and an accessibility check of every page in light and dark mode.

## What we learned

- The hard part of agentic commerce is trust and control, not the model: code-enforced limits, a person's one approval, and money that moves only on proof.
- PayPal's authorize-then-capture is a natural fit for collective orders: the buyer pays once, and each maker is paid when she ships.
- Designing for sellers who will never install an app kept everything inside the chat they already use.

## What's next

Real pilots with makers in Lahore, more languages reviewed by native speakers, Hyperwallet connected for Pakistan, and buyer agents commissioning products that do not exist yet, with PayPal holding the money until the work ships.

## Built With

python, fastapi, sqlalchemy, alembic, postgresql, next.js, react, typescript, tailwindcss, ag-grid, paypal-orders-v2, paypal-payments, paypal-payouts, paypal-webhooks, paypal-js-sdk, paypal-mcp-server, apimatic-paypal-python-sdk, apimatic-context-plugin, claude, anthropic, model-context-protocol, elevenlabs, openai-whisper, twilio-whatsapp, render, ed25519, playwright, vitest, pytest, axe-core

## Links (at submission)

- Code: https://github.com/FahadRamxan/OpenStall-Collective (MIT)
- Hosted demo: **(at submission)**
- Video (public on YouTube, under 3 minutes): **(at submission)**

## Testing instructions

Without keys, in test mode (a simulated PayPal and stand-in models, labelled everywhere): follow the README's "Try it (for judges)", then [docs/judges.md](judges.md), a ten-step walkthrough of the story with what to press and what to expect. On the hosted demo: the address, the sandbox buyer login and the demo token go here **(at submission)**.

## Sponsor tools to tick on the form

APIMatic (and answer its Context Plugin question with the paragraph above), AG Grid, and Render once the demo is hosted there. Not Elastic: OpenStall does not use it.
