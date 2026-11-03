# Day-one checks

Results of the October 30 checks from section 6 of the spec. Fill in each row as it is done.

**The repo is public. Never write passwords, client secrets or tokens in this file.** At submission time, the README gets the sandbox buyer login, and nothing else.

| # | Check | Status | Notes |
|---|---|---|---|
| 1 | Register on Devpost | Eligibility checked Oct 30: Pakistan is not excluded. Registration pending | Representative: |
| 2 | PayPal Developer account and sandbox REST app | Done Nov 3: the team's developer account, registered in Saudi Arabia (Pakistan is not on PayPal's country list) | Sandbox REST app `APP-782636354A163394T`; its keys are in `.env`, never in git |
| 3 | Sandbox accounts: 1 platform, 4 sellers, 2 buyers | Partly: the app's default business account (platform) and one personal buyer (SA) | Still to create: personal accounts for Priya (IN), Lucía (MX) and Noor (GB) as payout receivers, and a US buyer for Venmo and Pay Later tests |
| 4 | Create and capture one order with 2 or more payees | Answered Nov 3, no: Orders v2 (schema v2.36) does not support intent AUTHORIZE with more than one purchase unit, so a multi-payee order cannot do pay-on-proof | See "Payment path" |
| 5 | Payouts path | Done Nov 3: one authorization, several partial captures, tracking on each capture, a final capture, a void and a payout all work in the sandbox | See "Sandbox proof" below |
| 6 | Public repo with MIT license, `.gitignore`, `.env.example` | Repo created Oct 30. Scaffold committed locally; push waits for collaborator access | https://github.com/FahadRamxan/OpenStall-Collective |
| 7 | Twilio WhatsApp sandbox: one photo and one voice note logged | Pending | |
| 8 | Minimal MCP server with a fake `search_products`, called from an MCP client | Done Oct 30: `scripts/try_mcp.py` and `pytest` pass against `/mcp` | MCP Python SDK 2.3 |

## Payment path

Chosen path: **payouts**. One PayPal order with intent AUTHORIZE and a single purchase unit to the platform, one authorization for the whole total, a partial capture for each maker's share when she ships (`final_capture` only on the last), a void of whatever is left, and each maker paid with Payouts.

Why: Orders v2 refuses AUTHORIZE with several purchase units, and every step of this path worked on the real sandbox on November 3 (below).

Date decided: November 3, 2026.

## Sandbox proof (November 3)

Run against the real PayPal sandbox with the app above. The sandbox buyer approved each order in a browser.

| Check | Result |
|---|---|
| OAuth token | Granted; scopes include authorize and capture, Payouts, disputes, refunds, invoicing and webhooks |
| Order with intent AUTHORIZE and one purchase unit (four makers as items, $815.00) | Created, then approved by the buyer |
| Authorize | $815.00 held, valid for 29 days |
| Partial capture $216.00, `final_capture` false | Captured |
| Tracking on that capture, carrier DHL | Accepted (`POST /v2/checkout/orders/{id}/track`) |
| Second partial capture $176.00, `final_capture` false | Captured: several captures on one authorization work |
| Tracking on the second capture, carrier `OTHER` with `carrier_name_other` "Leopards Courier" | Accepted |
| A dropped share ($220.00) | Never captured |
| Final capture $203.00, `final_capture` true | Captured; the authorization closed. The buyer paid $595.00 of $815.00 |
| A second order: one partial capture, then void | The remaining $599.00 voided |
| Payout $1.00 to a PayPal account | Batch SUCCESS, fee $0.02 |
| Payout $1.00 to a Venmo handle (`recipient_wallet` Venmo) | Refused: "Recipient wallet not supported in sandbox." |
| OpenStall's own flow: Approve on `/approve/ord_demo`, approval at PayPal, the receipt page | The API created the order, read it and authorized it through APIMatic's PayPal SDK; the receipt said "PayPal is holding $815.00" with every share reserved |
| The SDK gateway's capture and void on that authorization, and the same capture sent again with the same PayPal-Request-Id | Captured, then voided; the repeat returned the same capture, so PayPal dedupes our retries |

Consequences:
- Venmo payouts cannot run in the sandbox, so Grace's Venmo payout is labelled simulated there.
- Authorizations expire after 29 days, so the orders judges use (December 1-15) must be created fresh then.
- Locally the receipt keeps "Waiting for PayPal": PayPal cannot send webhooks to localhost. They arrive on the hosted demo once its webhook is set up (below).

## PayPal webhooks

Once the hosted API is up (prompt 12) and the sandbox REST app exists:

1. In the PayPal developer dashboard, open the sandbox app, then **Add Webhook**.
2. Webhook URL: `https://openstall-collective-api.onrender.com/api/webhooks/paypal` (the hosted `PUBLIC_BASE_URL` plus `/api/webhooks/paypal`).
3. Events: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`, and for the payouts path `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` and `PAYMENT.PAYOUTS-ITEM.FAILED`.
4. Copy the webhook's **Webhook ID** into `PAYPAL_WEBHOOK_ID`, in `.env` and in the Render dashboard. It is not a secret, but without it every event is refused.
5. Check it: approve an order on the hosted demo as the sandbox buyer and watch the receipt's rows turn to "Confirmed by PayPal". Then resend one event from the dashboard's webhook events page: the API answers `{"status": "repeat"}` and nothing changes twice.

In fake mode the fake gateway sends the same events to the same endpoint, signed with a fixed fake key, so none of this is needed offline.

## Twilio WhatsApp

Once the hosted API is up and the Twilio account exists:

1. In the Twilio console, open **Messaging > Try it out > Send a WhatsApp message**, and join the sandbox from each demo phone (send the sandbox's join code to its number).
2. In the sandbox's settings, set **When a message comes in** to `https://openstall-collective-api.onrender.com/api/webhooks/twilio`, method POST. The URL must be exactly `PUBLIC_BASE_URL` plus `/api/webhooks/twilio`: Twilio signs the URL it calls, and the API checks the signature against that address.
3. Put `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env` and in the Render dashboard. `TWILIO_WHATSAPP_FROM` is the sandbox number, `whatsapp:+14155238886` unless Twilio shows another.
4. Check it (row 7): from a joined phone, send a photo and a voice note. Both appear on the hosted `/seller-chat` within a few seconds. Send a PDF: it is refused, and the phone gets a polite WhatsApp reply.

In fake mode, `POST /api/dev/inbound` plays a seller's message with a made-up photo or voice note, so none of this is needed offline.

## Sandbox accounts

Sandbox emails and merchant IDs only.

| Role | Sandbox email | Merchant ID | Country |
|---|---|---|---|
| Platform | The default business account of app `APP-782636354A163394T` | | |
| Seller: Amina | | | |
| Seller: Priya | | | |
| Seller: Lucía | | | |
| Seller: Grace | | | |
| Buyer 1 | sb-3xa9q53624080@personal.example.com | Payer id MH7HMZY6WN7NL | SA |
| Buyer 2 | | | |

## Model providers

Vision and text:

Speech to text (Urdu):
