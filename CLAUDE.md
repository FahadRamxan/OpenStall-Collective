# OpenStall Collective: notes for Claude

OpenStall pools WhatsApp-only home makers into one collective supplier that AI shopping agents buy from through an MCP storefront. The buyer's agent asks for an order, seller agents negotiate within each maker's limits, an allocator splits the order across makers, and a human approves one PayPal checkout that only **reserves** the money. Each maker's share is captured when she photographs her courier receipt (pay-on-proof), or released if she drops out. Built for the PayPal AI Hackathon (Devpost, submission closes 2026-11-12 12:00 PT).

## Where things are

- **Spec and build plan live outside the repo**, one folder up: `../OpenStall Collective.md` (the spec) and `../prompt.md` (the numbered build prompts, with a status table at the top, the workflow every prompt follows, and "Changes to earlier prompts"). Read the prompt you are building, and the spec sections it names, before writing code.
- `apps/api/openstall_api`: FastAPI app (`main.py`), settings and fake mode (`settings.py`, `adapters.py`), database (`models.py`, `migrations/`), event log (`events.py`), orders and payments (`orders.py`, `payments.py`, `claims.py`), PayPal webhooks (`webhooks.py`), WhatsApp (`whatsapp.py`, `chat/handler.py`), MCP storefront (`storefront.py`: search, product and trust card, request_quote, create_collective_order, checkout and get_order_status; `tests/test_no_tool_moves_money.py` calls every tool, so give a new tool its arguments there), draft orders from a plan (`collective.py`), the scripted buyer agent (`buyer.py`, used by `scripts/run_demo_request.py` over HTTP and `POST /api/demo/run` in process; `POST /api/demo/reset` re-seeds everything but the event log), its search and search log (`search.py`, `search_api.py`), the offer rules on database rows (`offer_rules.py`: policy, listing and quote request mapping, capacity by deadline, and each live maker's limits for `GET /api/demo/limits` in `demo_api.py`), seller agents on real data (`offers.py`: every proposal saved with the code check's verdict; `GET /api/offers`), quote requests (`quotes.py`: agents side by side, up to 3 rounds, each round committed as it ends; `GET /api/quotes`; the story's quote is `POST /api/dev/quote` in fake mode), the allocator on real quotes (`allocation.py`: the plan and its explanation stored on the request, `GET /api/quotes/{id}/plan`), and the agent feeds: `/catalog.json` and `/llms.txt` (`feeds.py`, `feeds_api.py`; llms.txt lists the MCP tools by itself) and trust cards at `/passport/{seller_id}` (`passports.py`, `passports_api.py`). HTTP tests share one uvicorn server (`apps/api/tests/conftest.py`).
- `apps/web`: Next.js 16 (App Router, Cache Components on) with Tailwind 4, Vitest and Playwright. Its `AGENTS.md` is written by `next dev`; Next's own docs are in `node_modules/next/dist/docs/`.
- Live panels on `/demo` share one event stream (`EventStreamProvider` in `src/hooks/use-event-stream.ts`) and keep their rows with `useLiveList` (`src/hooks/use-live-list.ts`). Copy the "Agent searches" panel (`src/components/agent-searches.tsx`) for a new one. Charts use the `--series-1` to `--series-5` colours in `globals.css` (validated for light and dark), in fixed order. UI tests call the MCP storefront through `e2e/support/mcp.ts`. A UI test that needs the seed table's capacities calls `POST /api/dev/release-reserved-shares` first: earlier spec files leave story orders reserved in the shared e2e database.
- `packages/paypal/openstall_paypal`: the payment gateway (`gateway.py` interface and FakeGateway, `sandbox.py` sandbox gateways, `sdk.py` APIMatic SDK boundary, `client.py` our REST client for Payouts and webhook checks, `rails.py` payout rails, `webhooks.py` verifiers).
- `packages/allocator`, `packages/trust`, `packages/agents`: offer rules and the allocator, trust passports, and the agents: AI adapter interfaces and fakes, Claude (`adapters/claude.py`), the seller agent (`seller_agent.py`), the plan in words with its number check (`explain.py`), and fake mode's stand-in answers (`fake_answers.py`; add each new agent's there).
- `docs/decisions.md` (why things are the way they are, newest last), `docs/day-one-checks.md` (account setup and the sandbox proof), `paypal-plan.md` (the APIMatic contract sheet).

## The build loop (every prompt, in this order)

1. Build it, with tests: pytest for Python (respx mocks HTTP; PayPal orders and payments are faked at the SDK's transport seam), Vitest for components.
2. Wire it into the UI.
3. Test it through the UI: a Playwright spec in `apps/web/e2e`, in fake mode.
4. Run `python scripts/check_all.py` (pytest, mypy, lint, Vitest, build, Playwright). Commit only when it ends with "All 6 checks passed". There is no CI; this is the gate.
5. Update `README.md` ("What works today" and "Build progress"), this file's status table, and the status table in `../prompt.md`.
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

Of the 58 build prompts in `../prompt.md`: **25 done, 3 partly done, 30 not started.** Each row was checked against the commits; "done" means built, tested, wired into the UI, tested in a browser and pushed. Update this table, the README's "Build progress" and `../prompt.md`'s status table with every prompt.

| Prompt | What | State | Commit |
|---|---|---|---|
| **A** | **Foundation** | | |
| 01 | Repo and backend CI | Done; CI was removed on request, `scripts/check_all.py` is the gate | 9507795, 3d11519 |
| 02 | Web app with test tooling | Done | e6e02a9 |
| 03 | Settings, fake mode, the status page | Done | 55db8fb |
| 04 | Database models and migrations | Done | 3328b1a |
| 05 | Event log and the live feed on /demo | Done | 9fc6db3 |
| 06 | Seed data and stall pages | Done | 35cbd1f |
| **B** | **PayPal** | | |
| 07 | PayPal client | Done | 8f3fec3 |
| 08 | Day-one payment test | Partly done: the sandbox proof ran on Nov 3 and is recorded in `docs/day-one-checks.md`; its script, `scripts/sandbox_proof.py`, is not in the repo yet | 027960f |
| 09 | Draft orders and the approval page | Done | 7bc0ae8 |
| 10 | Checkout that reserves the whole order | Done | 8f3fec3 |
| 11 | Reserve on return; pay or release each share | Done | f30566d |
| 12 | Deploy to Render | Partly done: the blueprint `render.yaml`; the deploy waits for a Render account | 9d5d70c |
| 13 | Verified, idempotent PayPal webhooks | Done; registering the real webhook waits for the hosted demo | 37ea2d0 |
| **C** | **Seller onboarding over WhatsApp** | | |
| 14 | Twilio WhatsApp webhook and media | Done; a real phone test waits for a Twilio account | 0419bc2 |
| 15 | One chat handler; /seller-chat | Done | 2fddbb9 |
| 16 | Voice notes to text | Not started | |
| 17 | A draft listing from photos and words | Not started | |
| 18 | Ask for what is missing; the seller's limits | Not started | |
| 19 | Confirm and publish | Not started | |
| **D** | **The agent storefront** | | |
| 20 | Search with filters and the search log | Done | 0a03ef8 |
| 21 | Product and trust card tools, /catalog.json, /llms.txt | Done | 3593da6 |
| **E** | **Negotiation and the collective** | | |
| 22 | The offer rules on /demo | Done (core logic feb467f) | bebf270 |
| 23 | The seller agent; Claude in sandbox mode | Done | 3309b31 |
| 24 | Quote requests and negotiation rounds | Done | be677db |
| 25 | The allocator on /demo | Done (core logic feb467f) | 189c2c1 |
| 26 | The plan explained in words | Done | 614ae4e |
| 27 | MCP request_quote and create_collective_order | Done | 1618bb3 |
| 28 | MCP checkout and get_order_status; no tool moves money | Done | d35fd48 |
| 29 | The scripted buyer agent; Run and Reset on /demo | Done | 4b6d2f5 |
| 30 | A real AI agent as the buyer | Not started | |
| **F** | **After payment** | | |
| 31 | Tell each seller about the order | Not started | |
| 32 | Snap the receipt, get paid | Not started (fake mode's `POST /api/dev/parts/{id}/proof` pays a share on simulated proof, from 51) | |
| 33 | Tracking on the PayPal order | Not started (tracking per capture was proven in the sandbox proof) | |
| 34 | Delivery and the end of an order | Not started | |
| **G** | **Trust passports and the materials advance** | | |
| 35 | Signed trust passports | Partly done: scoring, canonical JSON and Ed25519 signing (`packages/trust`), seeded passports signed; no public key or verify endpoint yet, so trust cards say "pending" | 475e435 |
| 36 | Passports update after delivery | Not started | |
| 37 | Materials advance (optional) | Not started | |
| 38 | The tamper check, shown live | Not started | |
| **H** | **The order heals itself; guardrails** | | |
| 39 | The order heals itself | Not started | |
| 40 | Try to break it: the guardrail panel | Not started | |
| **I** | **Pages and design** | | |
| 41 | The home page | Not started (a basic home page exists from 02 and 06) | |
| 42 | PayPal buttons on the stall page | Not started | |
| 43 | The complete live demo page | Not started (its panels exist from 20 to 29) | |
| 44 | The AG Grid dashboard | Not started (`/dashboard` is a placeholder) | |
| 45 | Design and accessibility pass | Not started | |
| **J** | **Hardening and submission** | | |
| 46 | Security and abuse limits | Not started | |
| 47 | The whole story, tested end to end, twice | Not started | |
| 48 | Dress rehearsal on the hosted demo | Not started | |
| 49 | README and testing instructions for judges | Not started | |
| 50 | Submission kit and release | Not started | |
| **K** | **More of PayPal** | | |
| 51 | Fake mode follows the payouts path; a payout rail per maker | Done | cdcf013 |
| 52 | Hyperwallet rail (simulated) | Not started | |
| 53 | PayPal products table, doctor report, APIMatic cross-check | Not started | |
| 54 | Pay-on-proof on the Braintree sandbox (gated) | Not started | |
| 55 | The PayPal ops agent through PayPal's MCP server | Not started | |
| 56 | Disputes answered with the proof | Not started | |
| 57 | Venmo, and Pay Later if proven, at the approval | Not started | |
| 58 | Orders and payments on APIMatic's PayPal SDK | Done, proven on the real sandbox | 027960f |

Next on the path to the November 5 draft: 31 and 32, then a first pass of 43 and 49, the hosted deploy (12, needs a Render account), and the Devpost draft.
