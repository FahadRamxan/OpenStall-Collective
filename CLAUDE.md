# OpenStall Collective: notes for Claude

OpenStall pools WhatsApp-only home makers into one collective supplier that AI shopping agents buy from through an MCP storefront. The buyer's agent asks for an order, seller agents negotiate within each maker's limits, an allocator splits the order across makers, and a human approves one PayPal checkout that only **reserves** the money. Each maker's share is captured when she photographs her courier receipt (pay-on-proof), or released if she drops out. Built for the PayPal AI Hackathon (Devpost, submission closes 2026-11-12 12:00 PT).

## Where things are

- **Spec and build plan live outside the repo**, one folder up: `../OpenStall Collective.md` (the spec) and `../prompt.md` (the numbered build prompts, with a status table at the top, the workflow every prompt follows, and "Changes to earlier prompts"). Read the prompt you are building, and the spec sections it names, before writing code.
- `apps/api/openstall_api`: FastAPI app (`main.py`), settings and fake mode (`settings.py`, `adapters.py`), database (`models.py`, `migrations/`), event log (`events.py`), orders and payments (`orders.py`, `payments.py`, `claims.py`), PayPal webhooks (`webhooks.py`), WhatsApp (`whatsapp.py`, `chat/handler.py`), MCP storefront (`storefront.py`), its search and search log (`search.py`, `search_api.py`), the offer rules on database rows (`offer_rules.py`: policy, listing and quote request mapping, capacity by deadline, and each live maker's limits for `GET /api/demo/limits` in `demo_api.py`), and the agent feeds: `/catalog.json` and `/llms.txt` (`feeds.py`, `feeds_api.py`; llms.txt lists the MCP tools by itself) and trust cards at `/passport/{seller_id}` (`passports.py`, `passports_api.py`). HTTP tests share one uvicorn server (`apps/api/tests/conftest.py`).
- `apps/web`: Next.js 16 (App Router, Cache Components on) with Tailwind 4, Vitest and Playwright. Its `AGENTS.md` is written by `next dev`; Next's own docs are in `node_modules/next/dist/docs/`.
- Live panels on `/demo` share one event stream (`EventStreamProvider` in `src/hooks/use-event-stream.ts`) and keep their rows with `useLiveList` (`src/hooks/use-live-list.ts`). Copy the "Agent searches" panel (`src/components/agent-searches.tsx`) for a new one. UI tests call the MCP storefront through `e2e/support/mcp.ts`. A UI test that needs the seed table's capacities calls `POST /api/dev/release-reserved-shares` first: earlier spec files leave story orders reserved in the shared e2e database.
- `packages/paypal/openstall_paypal`: the payment gateway (`gateway.py` interface and FakeGateway, `sandbox.py` sandbox gateways, `sdk.py` APIMatic SDK boundary, `client.py` our REST client for Payouts and webhook checks, `rails.py` payout rails, `webhooks.py` verifiers).
- `packages/allocator`, `packages/trust`, `packages/agents`: offer rules and the allocator, trust passports, AI adapter interfaces and their fakes.
- `docs/decisions.md` (why things are the way they are, newest last), `docs/day-one-checks.md` (account setup and the sandbox proof), `paypal-plan.md` (the APIMatic contract sheet).

## The build loop (every prompt, in this order)

1. Build it, with tests: pytest for Python (respx mocks HTTP; PayPal orders and payments are faked at the SDK's transport seam), Vitest for components.
2. Wire it into the UI.
3. Test it through the UI: a Playwright spec in `apps/web/e2e`, in fake mode.
4. Run `python scripts/check_all.py` (pytest, mypy, lint, Vitest, build, Playwright). Commit only when it ends with "All 6 checks passed". There is no CI; this is the gate.
5. Update `README.md` (what works today), this file's status table, and the status table in `../prompt.md`.
6. Commit with the prompt's commit message, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, then `git pull --rebase` and push: `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git push origin main` (retry once on a network reset).

## Commands (Windows, Git Bash)

- Python: `.venv/Scripts/python` (3.14). Install: `.venv/Scripts/python -m pip install -e ".[dev]"`.
- Backend tests: `.venv/Scripts/python -m pytest -q`. Type check: `.venv/Scripts/python -m mypy --strict packages/paypal/openstall_paypal`.
- Web (in `apps/web`): `npm run lint`, `npm test` (Vitest), `npm run build`, `npm run e2e` (Playwright starts its own API on port 8100 and web app on 3100, in fake mode); one spec: `npx playwright test e2e/<spec>.ts > <log file> 2>&1`.
- Seed: `.venv/Scripts/python scripts/seed_demo.py --reset --demo-order` (the story's order `ord_demo`, 12/11/10/7 = $815.00).

## Rules that are easy to break

- **Fake mode** (`OPENSTALL_MODE=fake`) is for tests and offline demos: deterministic fakes for PayPal, Twilio and the AI models. Tests always run in fake mode and ignore `.env`. `/api/dev/*` endpoints exist only in fake mode (404 otherwise).
- **Secrets:** `.env` holds the real PayPal sandbox keys and a sandbox buyer login. Never print, copy or commit them; `.env` is gitignored. The README gets only the sandbox buyer login, at submission time.
- **Honesty:** anything simulated is labelled. In fake mode the words "Confirmed by PayPal" never appear; it says "simulated PayPal". Seeded makers and numbers are marked `seeded_demo`.
- **Money:** `Decimal` in whole cents; totals are always worked out on the server, never taken from a caller.
- **Events:** every action calls `record_event` with a one-line plain-English summary, in the same transaction; the /demo feed shows them.
- **PayPal:** the payouts path only (one AUTHORIZE order with a single purchase unit, a partial capture per share, `final_capture` on the last, a void of the rest, Payouts per maker); multi-payee AUTHORIZE is refused by PayPal. Orders and Payments calls go through APIMatic's PayPal SDK by the APIMatic Context Plugin's process: keep `paypal-plan.md` in step with the code. Never retry a write blindly; idempotency keys come from our ids. No agent tool may move money.
- **Line endings are LF** (`.gitattributes`). On Windows write files with the Write or Edit tools, or `write_bytes`, never text-mode writes that produce CRLF.
- **Never pipe Playwright into `head` or `tail`**: it kills Playwright before it stops its servers on ports 8100 and 3100. If a port is left busy, stop only that uvicorn or next process, by PID, after checking its command line.
- **Migrations:** a model change needs an Alembic migration (`alembic revision --autogenerate`), and `test_db_migrations` checks they match exactly.

## Status (2026-11-04)

| Prompt | What | State |
|---|---|---|
| 01–06 | Repo, web app, settings and fake mode, database, event log and live feed, seed data and stall pages | Done |
| 07, 10, 11 | PayPal client, checkout that reserves the whole order, reserve on return and pay or release each share | Done |
| 08 | Day-one payment test | Done as a standalone sandbox proof (docs/day-one-checks.md) |
| 09 | Draft orders and the approval page | Done |
| 12 | Render blueprint | Done; the deploy waits for a Render account |
| 13 | Verified, idempotent PayPal webhooks | Done; registering the real webhook waits for the hosted demo |
| 14, 15 | Twilio WhatsApp webhook and media; one chat handler and /seller-chat | Done; a real phone test waits for a Twilio account |
| 25, 35 | Allocator, passport signing | Core logic done; wiring is in prompts 25 and 35 |
| 51 | Fake mode follows the payouts path; a payout rail per maker | Done |
| 58 | Orders and payments on APIMatic's PayPal SDK | Done, proven on the real sandbox |
| 20 | Search with filters, the search log, and the "Agent searches" panel on /demo | Done |
| 21 | get_product and get_trust_card, /catalog.json, /llms.txt, "For AI agents" on stall pages | Done |
| 22 | The offer rules on real data: each live maker's limits on /demo | Done |
| 23–29 | Seller agent, negotiation, allocator, explanations, MCP order tools, the scripted buyer | Next, in order |
