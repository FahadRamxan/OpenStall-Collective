# OpenStall Collective

OpenStall Collective lets small sellers who only use WhatsApp sell to AI shopping agents. A seller sends photos and a voice note, and AI turns them into listings that any agent can read and buy from. Each seller has an agent that negotiates within limits the seller sets. When an order is too big for one seller, the system splits it across several sellers. The buyer approves one PayPal checkout that only reserves the money, and each seller is paid when she photographs her shipping receipt.

Built for the PayPal AI Hackathon. Everything runs in the PayPal sandbox, or in test mode on a simulated PayPal; no real money moves. It is still being built: [What works today](#what-works-today) and [Build progress](#build-progress) say what runs now and what does not yet, such as turning a seller's photos and voice notes into a listing.

## What works today

Being built step by step; each step is tested, wired into the web app, tested in a browser, then pushed.

- **Pay-on-proof with PayPal.** `/approve/{order}` shows each maker's share. Approving creates one PayPal order (intent AUTHORIZE) for the whole total, and the receipt shows PayPal holding the money. Each share is captured on its own when she ships, or released if she cannot deliver, and she is paid on the payout rail her country allows: PayPal Payouts; Venmo for a US maker (simulated in the sandbox, where PayPal does not run Venmo payouts); Pakistan not connected yet. Verified, idempotent PayPal webhooks confirm each step.
- **Proven on PayPal's real sandbox:** one authorization, several partial captures with tracking on each, a final capture, a void, a payout, and OpenStall's own Approve flow end to end. See [docs/day-one-checks.md](docs/day-one-checks.md).
- **Built on APIMatic's PayPal SDK,** with APIMatic's PayPal Context Plugin (below).
- **Sellers chat on WhatsApp or in the browser.** A verified Twilio webhook stores their messages, photos and voice notes; `/seller-chat` is the same chat as a phone in the browser. One handler serves both.
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
- **A buyer agent you can run.** `python scripts/run_demo_request.py` plays the story through the MCP storefront (search, quote, draft order, approval link) and prints each step; add `--pause` to step through it for a recording, and `--url` to point it at the hosted demo. On `/demo`, "Run the demo request" does the same on the server, a stepper follows it from Search to Approval, and "Reset demo" puts the seeded world back. In sandbox mode both buttons need the `DEMO_RUN_TOKEN`.
- **A live feed** on `/demo` of everything that happens, and a status page at `/status`: the mode, the database, PayPal's token and the SDK in use.
- **Test mode:** a simulated PayPal (labelled as such everywhere), Twilio and AI models, so everything runs offline and in tests.

## Build progress

OpenStall is built in 58 numbered steps; each is tested, wired into the web app, tested in a browser, then pushed on its own. As of November 4: **25 done, 3 partly done, 30 not started.** [CLAUDE.md](CLAUDE.md) lists every step with its state and commit.

| Part | Done | Partly done | Not started |
|---|---|---|---|
| Foundation | 01–06 | | |
| PayPal | 07, 09, 10, 11, 13 | 08: the sandbox proof ran and is recorded, its script is not in the repo yet; 12: the Render blueprint, the deploy needs an account | |
| Sellers on WhatsApp | 14, 15 | | 16 voice notes to text, 17 a listing from photos, 18 asking for what is missing, 19 confirm and publish |
| Agent storefront | 20, 21 | | |
| Negotiation and the collective | 22–29 | | 30 a real AI agent as the buyer |
| After payment | | | 31 telling each maker, 32 a receipt photo pays her share, 33 tracking on the PayPal order, 34 delivery |
| Trust passports | | 35: signing works, but there is no public key or verify endpoint yet | 36 updates after delivery, 37 materials advance, 38 the tamper check |
| The order heals itself; guardrails | | | 39, 40 |
| Pages and design | | | 41 home page, 42 PayPal buttons on stalls, 43 the full demo page, 44 the AG Grid dashboard, 45 design pass |
| Hardening and submission | | | 46–50 |
| More of PayPal | 51, 58 | | 52 Hyperwallet (simulated), 53 products table, 54 Braintree, 55 ops agent, 56 disputes, 57 Venmo and Pay Later |

Next: telling each maker about her share (31) and paying her on a receipt photo (32), then the full demo page (43), the judges' README (49) and the hosted deploy.

## Run it locally

You need Python 3.11 or newer.

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

It starts in **fake mode** (`OPENSTALL_MODE=fake`): PayPal, Twilio and the AI models are replaced by stand-ins that give the same answers every time, so it runs without any keys. To use the real PayPal sandbox, Twilio sandbox and AI models, set `OPENSTALL_MODE=sandbox` in `.env` and fill in the keys you have. The real PayPal (sandbox), Twilio (WhatsApp) and Claude (the language model) adapters exist; speech to text and the other AI services arrive later, and until one exists the status page lists it as "Not built yet". The web app's status page (http://localhost:3000/status) and `GET /api/status` show the mode and which services are ready, and name any missing key without showing key values.

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

These addresses work once the blueprint is created. To create it (once): in the Render dashboard choose **New > Blueprint** and pick this repo. Render asks for the values marked `sync: false`; leave the ones you do not have yet empty. The API starts in fake mode. Once the PayPal sandbox keys are set, change `OPENSTALL_MODE` to `sandbox` in the dashboard. If Render gives a service a different address, change `PUBLIC_BASE_URL`, `WEB_BASE_URL` and `NEXT_PUBLIC_API_BASE_URL` to match.

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
