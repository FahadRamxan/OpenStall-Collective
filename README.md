# OpenStall Collective

OpenStall Collective lets small sellers who only use WhatsApp sell to AI shopping agents. A seller sends photos and a voice note, and AI turns them into listings that any agent can read and buy from. Each seller has an agent that negotiates within limits the seller sets. When an order is too big for one seller, the system splits it across several sellers, and one PayPal checkout pays them all.

Built for the PayPal AI Hackathon. Everything runs in the PayPal sandbox; no real money moves.

> **Status:** early scaffold. The API runs and serves an MCP storefront with one tool, `search_products`, over a seeded demo catalog. It has a fake mode with a stand-in for every outside service, and a status endpoint. The web app has its layout, a home page, a system status page and placeholder pages. Everything else is still to be built.

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

It runs `pytest`, then, in `apps/web`, `npm run lint`, `npm test`, `npm run build` and `npm run e2e`. It stops at the first failure and ends with a summary of which checks passed, failed or did not run. Push only when it says all checks passed.

- It works from any folder and with any Python 3.11 or newer: pytest and the UI tests' API run on the repo's `.venv` when it exists.
- It needs the setup above: the Python packages, `npm install` in `apps/web`, and Playwright's browser (`npx playwright install chromium` in `apps/web`, once).
- The UI tests make their own production build, so a full run takes a few minutes.

## Repository layout

```
apps/api/        FastAPI: webhooks, orders, PayPal, passports, MCP server at /mcp
apps/web/        Next.js: stall, seller-chat, demo, approve, dashboard
packages/        agents, allocator, paypal, trust
scripts/         demo and helper scripts
docs/            day-one checks and decisions
```

## Demo data

The four demo sellers and their listings are seeded and marked `seeded_demo`. They are not real sellers or real sales.

## License

MIT. See [LICENSE](LICENSE).
