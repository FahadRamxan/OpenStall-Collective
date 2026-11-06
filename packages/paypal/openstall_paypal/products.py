"""The PayPal products OpenStall uses or plans to (prompt 53): what each one does here, the calls it makes, where it is
in the code, and how far it has got.

This one list feeds `GET /api/paypal/doctor`, the /status page, `scripts/doctor.py` and the README's table, which
`scripts/tests/test_docs.py` checks against it. A product's state is only as strong as its evidence:

- proven: run against PayPal's real sandbox, with the date (docs/day-one-checks.md)
- built: in the code and tested, but not yet run end to end against the sandbox, and why not
- simulated: in the code, with the payout only recorded and labelled so wherever it shows, and why
- not built: a later prompt
"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["PRODUCTS", "STATE_WORDS", "Product", "ProductState"]

ProductState = Literal["proven", "built", "simulated", "not built"]

STATE_WORDS: dict[ProductState, str] = {
    "proven": "Proven on the sandbox",
    "built": "Built, not yet run on the sandbox",
    "simulated": "Simulated",
    "not built": "Not built yet",
}


@dataclass(frozen=True)
class Product:
    key: str
    name: str  # PayPal's name for it
    used_for: str  # what OpenStall does with it
    calls: tuple[str, ...]  # the routes we call, or the script we load
    code: str  # where it is in the code, from the repository root; empty when not built
    state: ProductState
    evidence: str  # why that state
    prompts: str  # the build prompts that made it


PRODUCTS: tuple[Product, ...] = (
    Product(
        key="oauth",
        name="OAuth 2.0 access tokens",
        used_for="A token for every PayPal call, from the app's client id and secret",
        calls=("POST /v1/oauth2/token",),
        code="packages/paypal/openstall_paypal/client.py, sdk.py",
        state="proven",
        evidence="Granted on the sandbox on November 3, and asked for again by /status and the doctor in sandbox mode",
        prompts="07",
    ),
    Product(
        key="orders",
        name="Orders v2, intent AUTHORIZE",
        used_for="One order for the buyer's whole total, read back, and authorized when the buyer approves: "
        "PayPal holds the money and takes nothing yet",
        calls=("POST /v2/checkout/orders", "GET /v2/checkout/orders/{id}", "POST /v2/checkout/orders/{id}/authorize"),
        code="packages/paypal/openstall_paypal/sandbox.py",
        state="proven",
        evidence="Run on the sandbox on November 3 through APIMatic's PayPal Python SDK: created, approved by the "
        "sandbox buyer and authorized, $815.00 held",
        prompts="09, 10, 11, 58",
    ),
    Product(
        key="payments",
        name="Payments v2: captures and voids",
        used_for="A partial capture of each maker's share when she proves she shipped, final_capture on the last, "
        "and a void of whatever is left",
        calls=("POST /v2/payments/authorizations/{id}/capture", "POST /v2/payments/authorizations/{id}/void"),
        code="packages/paypal/openstall_paypal/sandbox.py",
        state="proven",
        evidence="Run on the sandbox on November 3 through the SDK: partial captures, a final capture and a void; the "
        "same capture sent again with its PayPal-Request-Id returned the same capture",
        prompts="11, 51, 58",
    ),
    Product(
        key="tracking",
        name="Order tracking",
        used_for="Each maker's courier and tracking number, on her capture",
        calls=("POST /v2/checkout/orders/{id}/track",),
        code="packages/paypal/openstall_paypal/sandbox.py, tracking.py",
        state="built",
        evidence="The route was proven on the sandbox on November 3 by a direct call; through the SDK's "
        "create_order_tracking it has not run on the sandbox yet",
        prompts="33",
    ),
    Product(
        key="payouts",
        name="Payouts",
        used_for="Each maker's payout to her PayPal account when she ships, and a materials advance from OpenStall's "
        "own balance",
        calls=("POST /v1/payments/payouts",),
        code="packages/paypal/openstall_paypal/sandbox.py, rails.py",
        state="proven",
        evidence="A $1.00 payout to a sandbox PayPal account succeeded on November 3. The seeded makers' own sandbox "
        "accounts are not made yet, so in sandbox mode their rails say not connected",
        prompts="37, 51",
    ),
    Product(
        key="venmo",
        name="Payouts to Venmo",
        used_for="The payout of a US maker with a Venmo handle (Grace), by recipient_wallet Venmo and her handle",
        calls=("POST /v1/payments/payouts",),
        code="packages/paypal/openstall_paypal/rails.py",
        state="simulated",
        evidence="PayPal's sandbox refuses Venmo payouts (\"Recipient wallet not supported in sandbox\", November 3), "
        "so on the sandbox her capture is real and her payout is simulated and labelled",
        prompts="51",
    ),
    Product(
        key="hyperwallet",
        name="Hyperwallet",
        used_for="The payout to her bank account of a maker in Pakistan (Amina), where PayPal Payouts does not reach",
        calls=(),
        code="packages/paypal/openstall_paypal/rails.py",
        state="simulated",
        evidence="No Hyperwallet account is connected: her capture is real and her bank payout is simulated and "
        "labelled, and on PayPal's live host she has no rail rather than a pretend payout",
        prompts="52",
    ),
    Product(
        key="webhooks",
        name="Webhooks",
        used_for="PayPal's events confirm each step (the approval, the authorization, each capture and void, each "
        "payout), each verified with PayPal and applied once",
        calls=("POST /v1/notifications/verify-webhook-signature", "GET /v1/notifications/webhooks/{id}"),
        code="apps/api/openstall_api/webhooks.py, packages/paypal/openstall_paypal/webhooks.py",
        state="built",
        evidence="PayPal cannot send events to a computer at home, so real events wait for the hosted demo and its "
        "PAYPAL_WEBHOOK_ID; test mode signs its own events and sends them through the same code",
        prompts="13",
    ),
    Product(
        key="js_sdk",
        name="JavaScript SDK buttons",
        used_for="Buy buttons on each maker's stall page, intent authorize, PayPal only",
        calls=("https://www.paypal.com/sdk/js",),
        code="apps/web/src/components/stall-buy.tsx",
        state="built",
        evidence="The buttons load with the sandbox client id; approving in PayPal's window needs a person with the "
        "sandbox buyer login",
        prompts="42",
    ),
    Product(
        key="disputes",
        name="Disputes",
        used_for="A buyer's dispute that a parcel never came, answered with the maker's proof of shipping: her courier, "
        "her tracking number and her courier receipt photo",
        calls=("POST /v1/customer/disputes/{id}/provide-evidence",),
        code="apps/api/openstall_api/disputes.py, packages/paypal/openstall_paypal/disputes.py",
        state="built",
        evidence="A sandbox dispute needs the sandbox buyer to open one in PayPal's resolution centre, so it has not run "
        "there yet. The evidence's JSON part is named input, as in PayPal's own examples; the spec does not name it",
        prompts="56",
    ),
    Product(
        key="braintree",
        name="Braintree",
        used_for="Pay-on-proof on the Braintree sandbox",
        calls=(),
        code="",
        state="not built",
        evidence="Prompt 54, gated",
        prompts="54",
    ),
    Product(
        key="mcp",
        name="PayPal's MCP server",
        used_for="An ops agent that works through PayPal's own MCP server",
        calls=(),
        code="",
        state="not built",
        evidence="Prompt 55",
        prompts="55",
    ),
    Product(
        key="pay_later",
        name="Venmo and Pay Later at checkout",
        used_for="More ways for the buyer to pay at the approval",
        calls=(),
        code="",
        state="not built",
        evidence="Prompt 57; Pay Later only if it is proven to work with intent authorize",
        prompts="57",
    ),
)
assert len({product.key for product in PRODUCTS}) == len(PRODUCTS), "each product once"
