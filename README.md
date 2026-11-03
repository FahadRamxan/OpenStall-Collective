# OpenStall Collective

OpenStall Collective lets small sellers who only use WhatsApp sell to AI shopping agents. A seller sends photos and a voice note, and AI turns them into listings that any agent can read and buy from. Each seller has an agent that negotiates within limits the seller sets. When an order is too big for one seller, the system splits it across several sellers, and one PayPal checkout pays them all.

Built for the PayPal AI Hackathon. Everything runs in the PayPal sandbox; no real money moves.

> **Status:** being built prompt by prompt. Working so far: the MCP storefront with `search_products` over a seeded catalog, settings and fake mode, the database and its migrations, the event log with a live feed on `/demo`, the system status page, and the offer-rules, allocator and trust-passport cores.

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

It starts in **fake mode** (`OPENSTALL_MODE=fake`): PayPal, Twilio and the AI models are replaced by stand-ins that give the same answers every time, so it runs without any keys. To use the real PayPal sandbox, Twilio sandbox and AI models, set `OPENSTALL_MODE=sandbox` in `.env` and fill in the keys you have. The real adapters arrive in later build steps; until one exists, the status page lists it as "Not built yet". The web app's status page (http://localhost:3000/status) and `GET /api/status` show the mode and which services are ready, and name any missing key without showing key values.

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
```

## Demo data

The five demo makers (Amina, Priya, Lucía, Grace and the backup Noor), their listings and their trust records are seeded and marked `seeded_demo` everywhere they appear. They are not real sellers or real sales. Their product photos are labelled placeholders until the team adds its own.

## License

MIT. See [LICENSE](LICENSE).
