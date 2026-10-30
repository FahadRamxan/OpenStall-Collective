# OpenStall Collective

[![CI](https://github.com/FahadRamxan/OpenStall-Collective/actions/workflows/ci.yml/badge.svg)](https://github.com/FahadRamxan/OpenStall-Collective/actions/workflows/ci.yml)

OpenStall Collective lets small sellers who only use WhatsApp sell to AI shopping agents. A seller sends photos and a voice note, and AI turns them into listings that any agent can read and buy from. Each seller has an agent that negotiates within limits the seller sets. When an order is too big for one seller, the system splits it across several sellers, and one PayPal checkout pays them all.

Built for the PayPal AI Hackathon. Everything runs in the PayPal sandbox; no real money moves.

> **Status:** early scaffold. The API runs and serves an MCP storefront with one tool, `search_products`, over a seeded demo catalog. Everything else is still to be built.

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

Fill in `.env` with the keys you have. The API is then at http://localhost:8000, and the MCP storefront is at http://localhost:8000/mcp (Streamable HTTP). Point any MCP client there, or, with the API running, use the included one in a second terminal:

```bash
python scripts/try_mcp.py "cushion covers"
```

Run the tests (they start their own server, so the API does not need to be running):

```bash
pytest
```

**Note for contributors:** this uses the MCP Python SDK 2.x, where `FastMCP` is now `MCPServer` (`from mcp.server import MCPServer`) and clients use `from mcp import Client`. Examples written for SDK 1.x need small changes.

## Repository layout

```
apps/api/        FastAPI: webhooks, orders, PayPal, passports, MCP server at /mcp
apps/web/        Next.js: stall, seller-chat, demo, approve, dashboard (not started)
packages/        agents, allocator, paypal, trust
scripts/         demo and helper scripts
docs/            day-one checks and decisions
```

## Demo data

The four demo sellers and their listings are seeded and marked `seeded_demo`. They are not real sellers or real sales.

## License

MIT. See [LICENSE](LICENSE).
