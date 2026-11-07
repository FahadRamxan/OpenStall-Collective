# OpenStall's PayPal integration, built with APIMatic's PayPal Context Plugin

Every PayPal Orders and Payments call OpenStall makes goes through **APIMatic's PayPal Python SDK**, and the integration was written by a coding agent (Claude Code) with **APIMatic's PayPal Context Plugin** installed, following the plugin's own process: a contract sheet first, then code, then tests at the SDK's seam. This page shows where each piece of that is in the repository, so it can be checked.

## What was used

| | |
| --- | --- |
| The plugin | APIMatic's PayPal Context Plugin, from the Context Plugins marketplace: `npx context-plugins install paypal --targets claude` |
| The coding agent | Claude Code, with the plugin's Python skills: `python-integrate-paypal` (the order of work and its gates), `python-getting-started` (the lookup layer), and the companion skills its plan requires (see [paypal-plan.md, "REQUIRED READING"](../paypal-plan.md#required-reading)) |
| The SDK | APIMatic's PayPal Python SDK, version 2.29, from [context-plugins/paypal-python-sdk](https://github.com/context-plugins/paypal-python-sdk), pinned in `pyproject.toml` to its full commit, `143e57f2a3729d7df3727386b8c9ddf023d9a5df` |
| When | November 3, 2026: commit `027960f`, "orders and payments on APIMatic's PayPal SDK, proven on the sandbox"; tracking was added through the SDK on November 5 (`38836c0`) |

The plugin's skills are installed on the machine that runs the agent, so they are not in this repository. What the plugin produces is: its contract sheet, the code it shaped, and the gates it asks for.

## The plugin's process, step by step, and where to see it

1. **A plan and contract sheet before any code.** [paypal-plan.md](../paypal-plan.md) is the sheet the plugin's `python-integrate-paypal` skill requires at the repository root. Every SDK fact the code relies on was looked up in the SDK's own map and source, not recalled, and written there first: the client's construction, each operation's signature, the keywords we pass, the request models and their real defaults, the enums, the response members we read, the error unions, the retry policy, and a table of duplicate claims (how each write is kept from being sent twice). No project file changed until the sheet had no open lookups.
2. **The SDK makes every Orders and Payments call.** One sync client per process, made in [packages/paypal/openstall_paypal/sdk.py](../packages/paypal/openstall_paypal/sdk.py) with one error boundary (`PayPalSdk.call`); the gateways that use it are in [sandbox.py](../packages/paypal/openstall_paypal/sandbox.py).
3. **Type checks.** `mypy --strict` on the PayPal package, in every run of `python scripts/check_all.py`.
4. **Tests at the SDK's own seam.** PayPal is faked as a transport passed to the SDK (`custom_http_client`), so the tests check the request the SDK really builds and every failure kind the plugin lists: refusals with PayPal's issue codes, bad credentials, a request that never left, one that may have landed, an answer the SDK cannot read, and the retry policy (reads only; a write is never resent blindly).
5. **Checked again on every run.** The APIMatic cross-check ([crosscheck.py](../packages/paypal/openstall_paypal/crosscheck.py), on `/status` and in `python scripts/doctor.py`) checks that the sheet, the code and the installed SDK still agree: every SDK call in the code has its row in the sheet and every row is called; each call passes exactly the keywords its row says; the installed SDK has each operation with those parameters, by its own signatures; and the sheet, the pin and the installed SDK are one commit. [test_crosscheck.py](../packages/paypal/tests/test_crosscheck.py) runs it with the tests, so a new SDK call cannot land without its row.

## Each SDK operation, where it is called, and how far it has got

| SDK operation (a row of the sheet) | What OpenStall uses it for | Called in `sandbox.py` | On PayPal's real sandbox |
| --- | --- | --- | --- |
| `orders.create_order` | One AUTHORIZE order for the whole collective order, each maker's share an item | `SandboxGateway.create_checkout` | Proven November 3 |
| `orders.get_order` | PayPal's state before reserving, and after any call that got no answer | `SandboxGateway.get_order` | Proven November 3 |
| `orders.authorize_order` | Reserve the approved order: the whole total held, nothing taken | `SandboxGateway.reserve` | Proven November 3 |
| `payments.capture_authorized_payment` | Each maker's share, captured when she proves she shipped (`final_capture` on the last) | `SandboxGateway.capture` | Proven November 3, including PayPal answering a resent capture with the first one |
| `payments.void_payment` | Release what is left when a maker drops out | `SandboxGateway.void`, from `PayoutsGateway.release_share` | Proven November 3 |
| `orders.create_order_tracking` | Her courier and tracking number on her capture | `SandboxGateway.add_tracking` | Built and tested; on the sandbox, tracking was proven by hand on November 3, not yet through the SDK. `python scripts/sandbox_proof.py` does it through the SDK once a person approves its orders |

The tests for each are in [packages/paypal/tests/test_sandbox_gateways.py](../packages/paypal/tests/test_sandbox_gateways.py) (the exact requests the SDK sends, and every failure kind) and [test_tracking.py](../packages/paypal/tests/test_tracking.py). The sandbox run is recorded in [docs/day-one-checks.md](day-one-checks.md) ("Sandbox proof").

## What is not on the SDK, and why

APIMatic's PayPal SDK covers Orders and Payments. OpenStall also uses PayPal APIs it does not have, on our own small client ([client.py](../packages/paypal/openstall_paypal/client.py)):

- **Payouts**, to pay each maker on her rail.
- **Webhook verification** (`verify-webhook-signature`) and the registered webhook, read back by the doctor.
- **Disputes**: answering a buyer's dispute with the maker's proof (`provide-evidence`).
- **PayPal's own MCP server** (`@paypal/mcp`), which the ops agent reads orders and disputes through, with tools that only read.

## The decisions behind it

[docs/decisions.md](decisions.md), "November 3: the APIMatic PayPal SDK", explains each choice: the sync client, retries on reads only, the 401 resent once with a fresh token, one error boundary, and the duplicate-claims store.
