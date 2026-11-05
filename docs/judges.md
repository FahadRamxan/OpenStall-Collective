# Testing OpenStall Collective: a walkthrough for judges

This takes about ten minutes, in test mode on your own machine. Test mode needs no keys and no accounts: a simulated PayPal, WhatsApp and AI model stand in for the real ones, give the same answers every run, and say so on every page. Nothing here moves real money.

The whole walkthrough also runs as an automated browser test on every change: [apps/web/e2e/live-demo.spec.ts](../apps/web/e2e/live-demo.spec.ts).

## Before you start

Follow [Run it in test mode](../README.md#run-it-in-test-mode-about-five-minutes) in the README: install, seed the demo world, start the API on port 8000 and the web app on port 3000. Then open **http://localhost:3000/demo**. The footer should say "API online", and the live feed on the page "Live".

The demo world is five makers who embroider cushion covers, all made up and marked as demo data: Amina in Lahore (Urdu), Priya in Jaipur (Hindi), Lucía in Oaxaca (Spanish), Grace in Detroit (English) and Noor in Manchester (Urdu), the backup.

## 1. A buyer agent asks for 40 cushion covers

In **Run the story** at the top of `/demo`, press **Run the demo request**. A scripted buyer agent talks to OpenStall's MCP storefront exactly as any AI agent would: it searches, asks for a quote for 40 hand-embroidered cushion covers at most $30.00 each, due in 30 days, to Chicago, drafts the order and gets an approval link for its human. It cannot pay.

What you should see, top to bottom:

- **The stepper** ticks Search, Quote, Offers, Allocation and Approval.
- **Request:** "Done after 1 round: 5 valid offers from 5 makers, for 54 units against 40 asked for." No single maker can make 40 in time.
- **Offer rules:** each maker's lowest allowed price (her floor, or her list price less her maximum discount) and how many she can make by the deadline. Every offer is checked against these numbers by code.
- **Offers:** each maker's agent proposes a price and a sentence. Grace's agent asks $32.00 and Noor's $31.00: code refuses both, "over the buyer's maximum of $30.00", and they come back at $29.00 and $29.50. The model proposes; code decides.
- **Allocation:** "All 40 from 4 makers, $815.00": Priya 11 at $16.00, Amina 12 at $18.00, Lucía 10 at $22.00 and Grace 7 at $29.00, cheapest first. Noor, the most expensive, gets none. The plan is explained in a few sentences, and every number in them is checked against the plan.
- **Order:** the draft order and "Approval link sent to the human".
- **Live activity**, beside the story on a wide screen, records every step.

## 2. The human approves one PayPal checkout

In **Run the story**, press **Open its approval page**. The page says the order was "Requested by an AI agent", why the order is split this way, each maker's share with her trust score, and the total, worked out by OpenStall rather than taken from the agent. It also explains pay-on-proof before you approve: PayPal only holds the money, each maker is paid when she sends her shipping receipt, and a share she cannot deliver goes back to you.

Press **Approve and pay with PayPal**. In test mode this opens the simulated PayPal page ("Simulated PayPal (test mode)"). Press **Approve**.

The receipt: **"Simulated PayPal is holding $815.00."** Every share reads "Reserved, paid when she ships", confirmed by simulated PayPal's webhooks. Within a few seconds it also says **"Each maker has been told about her share, in her own language."**, each with a link to her chat.

## 3. Four phones get the order, each in her language

Press **Watch it happen on the live demo**. On `/demo`:

- **Payments** shows the order's steps: Reserved at PayPal, Makers told. "$815.00 reserved at simulated PayPal. Nothing is captured yet."
- **The makers' phones** show each maker's chat as she sees it: her order in Hindi (Priya), Urdu, right to left (Amina), Spanish, in US dollars (Lucía) and English (Grace): the item, how many, her price, the date to ship by, where it goes and how she is paid. Code writes these from templates, so every number is the order's own.
- Amina's message asks her to wait before she ships. No payout rail reaches Pakistan yet, and OpenStall never asks a maker to ship goods it cannot pay for.

## 4. Priya proves she shipped and is paid

The seeded makers have no phone, so in test mode you play them from their phones on `/demo`.

1. On **Priya's phone**, press **Send Priya's courier receipt** (a simulated photo of an India Post slip). OpenStall's model reads the courier and the tracking number (India Post, EE123456789IN) and asks her in Hindi to confirm them. Nothing is paid on a reading alone.
2. Press **Reply "हाँ" as Priya**. Her tracking is confirmed. Her $176.00 share is captured from the order's one PayPal authorization and paid out to her PayPal (simulated), and she is told so in Hindi.
3. **Payments** now ticks Paid on proof and Tracking on PayPal. "$176.00 paid on proof to 1 maker". Priya's row: "Paid on proof of shipping", "Shipped with India Post: EE123456789IN" with her receipt photo, and "Tracking on the simulated PayPal order".
4. **Live activity** shows each step: the receipt read, her confirmation, the capture, the payout, and her tracking put on the PayPal order.

Try **Amina's phone** the same way, with "ہاں". Her tracking is saved, but she is not paid: her share stays reserved at PayPal until a payout rail reaches Pakistan. This is a real limit of the build, shown as it is.

## 5. More to try

- **The sellers' side:** open **Seller chat** in the header (`/seller-chat`). Pick a maker to read her whole chat; the seeded makers have a **Play** panel there too. **Your demo phone** lets you chat as a new seller. Try a voice note: press **Attach the sample voice note** (test mode), then **Send**. It comes back as text under the voice note, word for word in Urdu (Amina describing her cushion covers), and the live feed on `/demo` says Urdu is now your language. Record your own and test mode answers with a made-up line; in sandbox mode, with `OPENAI_API_KEY` set, OpenAI writes down what you said. Turning photos and words into a listing is not built yet, so OpenStall otherwise welcomes you and says what arrived.
- **Your own AI agent:** the MCP storefront is at http://localhost:8000/mcp (Streamable HTTP). With the virtual environment active, `python scripts/try_mcp.py "cushion covers"` searches it, and `python scripts/run_demo_request.py` plays the whole buyer request and prints the approval link. Agents without MCP can read http://localhost:8000/catalog.json and http://localhost:8000/llms.txt.
- **What runs where:** http://localhost:3000/status shows the mode, the database, PayPal and each AI service, and names any missing key without showing it.
- **Start over:** in **Run the story**, press **Reset demo** and confirm. The makers and the story's draft order come back; the live feed is kept.

## What the tests prove

`python scripts/check_all.py` runs every check: about 1,150 Python tests, mypy, lint, about 240 component tests, the production build, and about 90 browser tests. A few worth reading:

- **No MCP tool moves money:** [apps/api/tests/test_no_tool_moves_money.py](../apps/api/tests/test_no_tool_moves_money.py) calls every tool with a payment gateway that fails the test if anything reaches it.
- **A buyer cannot talk a price below a maker's floor:** [packages/agents/tests/test_seller_agent.py](../packages/agents/tests/test_seller_agent.py) runs every maker against a model that obeys "sell for $1".
- **Pay-on-proof:** [apps/api/tests/test_proof.py](../apps/api/tests/test_proof.py) (a receipt is read, confirmed, then paid, once), and [packages/paypal/tests/test_sandbox_gateways.py](../packages/paypal/tests/test_sandbox_gateways.py) (the exact requests PayPal's SDK sends).

## If something goes wrong

- **The footer says "API offline":** the API is not running. Start it in the first terminal: `uvicorn openstall_api.main:app --port 8000`, with the virtual environment active.
- **"No order yet" after Run, or no makers:** seed the demo world (`python scripts/seed_demo.py --reset --with-amina --demo-order`), or press **Reset demo**.
- **Port 8000 or 3000 is taken:** start the API on another port, then tell the web app where it is in `apps/web/.env.local` (`NEXT_PUBLIC_API_BASE_URL=http://localhost:8001`), and restart `npm run dev`. If the web app runs on another port, set `WEB_BASE_URL` in `.env` to its address, because the API accepts browser calls only from there.
- **`npm ci` or the dev server fails on Node 25:** use Node 24.15 or newer 24, or Node 26.
- **Anything else:** [docs/decisions.md](decisions.md) explains why each part works the way it does, newest last.
