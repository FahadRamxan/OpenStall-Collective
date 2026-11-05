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

## 5. The buyer receives Priya's parcel

PayPal's order trackers only say a parcel shipped, so the buyer, who receives the parcels, confirms each one.

1. Go back to the receipt tab (the page that said "Simulated PayPal is holding $815.00"; reload it). Priya's row now has **Confirm delivery**. Press it.
2. Her row says "Delivered to you" and "Received" with the date, on time (the order is due December 10). No money moves: she was paid when she shipped.
3. **Priya's phone** on `/demo` gets the news in Hindi, and **Live activity** says "The buyer received Priya's parcel". `get_order_status` gives the buyer's agent the same: her share delivered, and on time.
4. Her trust passport is signed again with the delivery counted: **Live activity** shows her old and new score, and her stall page (`/stall/s_priya`) now reads 68 orders delivered, "1 of these orders came through OpenStall", the rest still marked as seeded demo numbers. In her stall's **For AI agents** box, **Check its signature** asks OpenStall to verify her card: it is signed again, and valid.

The order completes once every parcel that shipped has arrived and the rest were released: the receipt then reads **Order complete**, with what was paid to the makers and what came back to the buyer. Amina's share stays reserved here, since no payout rail reaches Pakistan, so this order stays open.

## 6. Change one number in her passport

Back on `/demo`, **Check a trust passport** (after the makers' phones) loads Priya's signed trust card and checks its signature twice: in your browser, with OpenStall's public key, and by OpenStall itself. Both say "Signature valid: OpenStall signed exactly this card."

1. Change any number: say her on-time rate, to 0.99. The box turns red.
2. Press **Check the signature**: "Signature does not match: this card was changed after OpenStall signed it." Your browser and OpenStall both say it does not match.
3. Press **Put it back**: the card is as OpenStall signed it, and valid again.

In test mode the card is signed with a fixed test key that anyone can rebuild, and the panel says so.

## 7. A maker drops out: the order heals itself

Still on `/demo`, with the story's order approved:

1. On **Grace's phone**, press **Grace can't make it** (test mode). She writes "Sorry, I can't make this order.", and OpenStall asks her to confirm: nothing moves on her words alone.
2. Press **Reply "Yes" as Grace**. Her $203.00 share goes back to the buyer, never charged. OpenStall asks the other makers' agents for her 7 units, and **Payments** shows **The order heals itself**: "Noor can make all 7: top-up order …, $206.50." Noor's phone appears.
3. Press **Approve the top-up**. Its approval page says which order it tops up and whose units it replaces. Approve it like the first: Noor is told on her phone, in Urdu.

**Live activity** follows each step: Grace dropping out, her share released, the agents' new round, the top-up, and the order re-planned without her.

## 8. More to try

- **The sellers' side:** open **Seller chat** in the header (`/seller-chat`). Pick a maker to read her whole chat; the seeded makers have a **Play** panel there too. **Your demo phone** lets you chat as a new seller. Try being Amina: press **Attach the sample photo** and **Attach the sample voice note** (test mode), then **Send**. The voice note comes back as text under it, word for word in Urdu, and OpenStall's answers are spoken too, in Urdu, since she talked in a voice note (a stand-in tone in test mode; ElevenLabs' Eleven v4 Turbo with real keys). **Your listing so far** appears under the chat: her cushion cover, $18.00 each and 4 a week, each number with the Urdu words it came from. OpenStall answers in Urdu, her language now, with one question: how many days her parcel takes to reach a buyer in the US (**Asking now** in the panel). Answer each question with a bare number or a city, as a seller would: `9`, then `Lahore`, then `15` (the lowest price she would take for one), then `5` (the fewest days she needs to make an order). The last two fill in **Your limits**, which buyers never see. Then she gets all of it back, in Urdu, and is asked to reply yes: send `ہاں` (or `yes`). **Your listing is live** appears with **Open your stall**, her new stall page, and the live feed says her listing is live; buyers' agents can find it in search right away. Typed in English instead, the questions come in English. Record your own voice note and test mode answers with a made-up line; in sandbox mode, with `OPENAI_API_KEY` set, OpenAI writes down what you said. Press **Reset demo** on `/demo` afterwards to take your listing down again before running the story.
- **Your own AI agent:** the MCP storefront is at http://localhost:8000/mcp (Streamable HTTP). With the virtual environment active, `python scripts/try_mcp.py "cushion covers"` searches it, and `python scripts/run_demo_request.py` plays the whole buyer request and prints the approval link. Agents without MCP can read http://localhost:8000/catalog.json and http://localhost:8000/llms.txt.
- **What runs where:** http://localhost:3000/status shows the mode, the database, PayPal and each AI service, and names any missing key without showing it.
- **Start over:** in **Run the story**, press **Reset demo** and confirm. The makers and the story's draft order come back; the live feed is kept.

## What the tests prove

`python scripts/check_all.py` runs every check: about 1,380 Python tests, mypy, lint, about 280 component tests, the production build, and about 95 browser tests. A few worth reading:

- **No MCP tool moves money:** [apps/api/tests/test_no_tool_moves_money.py](../apps/api/tests/test_no_tool_moves_money.py) calls every tool with a payment gateway that fails the test if anything reaches it.
- **A buyer cannot talk a price below a maker's floor:** [packages/agents/tests/test_seller_agent.py](../packages/agents/tests/test_seller_agent.py) runs every maker against a model that obeys "sell for $1".
- **Change one number and the signature fails:** [apps/api/tests/test_passport_verify.py](../apps/api/tests/test_passport_verify.py) (every seeded card checks out; a changed count, rate, score or data source does not), and [apps/web/src/lib/passports.test.ts](../apps/web/src/lib/passports.test.ts) (the browser writes exactly the bytes OpenStall signed).
- **A maker drops out:** [apps/api/tests/test_healing.py](../apps/api/tests/test_healing.py) (asked first, released on her yes and never charged, her units asked of every other maker, one top-up only, and what happens when no one can take them).
- **Pay-on-proof:** [apps/api/tests/test_proof.py](../apps/api/tests/test_proof.py) (a receipt is read, confirmed, then paid, once), and [packages/paypal/tests/test_sandbox_gateways.py](../packages/paypal/tests/test_sandbox_gateways.py) (the exact requests PayPal's SDK sends).

## If something goes wrong

- **The footer says "API offline":** the API is not running. Start it in the first terminal: `uvicorn openstall_api.main:app --port 8000`, with the virtual environment active.
- **"No order yet" after Run, or no makers:** seed the demo world (`python scripts/seed_demo.py --reset --with-amina --demo-order`), or press **Reset demo**.
- **Port 8000 or 3000 is taken:** start the API on another port, then tell the web app where it is in `apps/web/.env.local` (`NEXT_PUBLIC_API_BASE_URL=http://localhost:8001`), and restart `npm run dev`. If the web app runs on another port, set `WEB_BASE_URL` in `.env` to its address, because the API accepts browser calls only from there.
- **`npm ci` or the dev server fails on Node 25:** use Node 24.15 or newer 24, or Node 26.
- **Anything else:** [docs/decisions.md](decisions.md) explains why each part works the way it does, newest last.
