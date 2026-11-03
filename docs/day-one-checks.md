# Day-one checks

Results of the October 30 checks from section 6 of the spec. Fill in each row as it is done.

**The repo is public. Never write passwords, client secrets or tokens in this file.** At submission time, the README gets the sandbox buyer login, and nothing else.

| # | Check | Status | Notes |
|---|---|---|---|
| 1 | Register on Devpost | Eligibility checked Oct 30: Pakistan is not excluded. Registration pending | Representative: |
| 2 | PayPal Developer account and sandbox REST app | Pending | Whose account: |
| 3 | Sandbox accounts: 1 platform, 4 sellers, 2 buyers | Pending | Fill in the table below |
| 4 | Create and capture one order with 2 or more payees | Pending | |
| 5 | Payouts fallback (only if check 4 fails) | Pending | |
| 6 | Public repo with MIT license, `.gitignore`, `.env.example` | Repo created Oct 30. Scaffold committed locally; push waits for collaborator access | https://github.com/FahadRamxan/OpenStall-Collective |
| 7 | Twilio WhatsApp sandbox: one photo and one voice note logged | Pending | |
| 8 | Minimal MCP server with a fake `search_products`, called from an MCP client | Done Oct 30: `scripts/try_mcp.py` and `pytest` pass against `/mcp` | MCP Python SDK 2.3 |

## Payment path

Chosen path: multi-seller order / payouts fallback (keep one)

Why:

Date decided:

## PayPal webhooks

Once the hosted API is up (prompt 12) and the sandbox REST app exists:

1. In the PayPal developer dashboard, open the sandbox app, then **Add Webhook**.
2. Webhook URL: `https://openstall-collective-api.onrender.com/api/webhooks/paypal` (the hosted `PUBLIC_BASE_URL` plus `/api/webhooks/paypal`).
3. Events: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`, and for the payouts path `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` and `PAYMENT.PAYOUTS-ITEM.FAILED`.
4. Copy the webhook's **Webhook ID** into `PAYPAL_WEBHOOK_ID`, in `.env` and in the Render dashboard. It is not a secret, but without it every event is refused.
5. Check it: approve an order on the hosted demo as the sandbox buyer and watch the receipt's rows turn to "Confirmed by PayPal". Then resend one event from the dashboard's webhook events page: the API answers `{"status": "repeat"}` and nothing changes twice.

In fake mode the fake gateway sends the same events to the same endpoint, signed with a fixed fake key, so none of this is needed offline.

## Sandbox accounts

Sandbox emails and merchant IDs only.

| Role | Sandbox email | Merchant ID | Country |
|---|---|---|---|
| Platform | | | |
| Seller: Amina | | | |
| Seller: Priya | | | |
| Seller: Lucía | | | |
| Seller: Grace | | | |
| Buyer 1 | | | |
| Buyer 2 | | | |

## Model providers

Vision and text:

Speech to text (Urdu):
