"""The PayPal sandbox gateways, one for each payment path. PAYMENT_PATH picks one (docs/day-one-checks.md says why).

Both create the order with intent AUTHORIZE and authorize it when the buyer comes back, so approving only reserves
the money. They differ in who the payees are:

- MultipartyGateway: each seller is the payee of her own purchase unit, so each share has its own authorization.
  Paying a share captures her authorization; releasing it voids that authorization.
- PayoutsGateway: the platform is the only payee and holds one authorization for the whole order, with each share
  listed as an item. Paying a share captures just her amount and sends it to her with PayPal Payouts. Releasing a
  share leaves her amount uncaptured; the order's last capture or void gives whatever is left back to the buyer.

Every write uses an idempotency key made from our own ids, so repeating a call never reserves or pays twice.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from openstall_paypal.client import PayPalClient, PayPalError, PayPalUnavailable
from openstall_paypal.gateway import (
    WHOLE_ORDER,
    Checkout,
    CheckoutRequest,
    OrderState,
    Payment,
    PaymentError,
    PaymentUnavailable,
    Reservation,
    Share,
)

BRAND_NAME = "OpenStall Collective"
TEXT_LIMIT = 127  # PayPal's limit for descriptions and item names


def money(amount: Decimal) -> dict[str, str]:
    return {"currency_code": "USD", "value": f"{amount:.2f}"}


def approval_link(order: dict[str, Any]) -> str:
    """Where the buyer approves the order: rel "payer-action" for orders made with an experience context, "approve"
    on older responses."""
    links = {link.get("rel"): link.get("href") for link in order.get("links", [])}
    href = links.get("payer-action") or links.get("approve")
    if not href:
        raise PaymentError("NO_APPROVAL_LINK", f"PayPal created order {order.get('id')} without an approval link")
    return href


def holds_of(order: dict[str, Any]) -> dict[str, str]:
    """The authorization on each purchase unit, by reference_id. Empty until the order is authorized."""
    holds: dict[str, str] = {}
    for unit in order.get("purchase_units", []):
        authorizations = (unit.get("payments") or {}).get("authorizations") or []
        if authorizations:
            holds[unit.get("reference_id", "default")] = authorizations[0]["id"]
    return holds


@contextmanager
def paypal_errors() -> Iterator[None]:
    """PayPal client errors as the gateway's errors, keeping PayPal's issue code."""
    try:
        yield
    except PayPalUnavailable as error:
        raise PaymentUnavailable(error.issue or "PAYPAL_UNAVAILABLE", str(error)) from error
    except PayPalError as error:
        raise PaymentError(error.issue or "PAYPAL_ERROR", str(error)) from error


class SandboxGateway:
    """What both paths share: the order is made with intent AUTHORIZE, read back, and authorized on return."""

    path = ""

    def __init__(self, client: PayPalClient) -> None:
        self.client = client

    def purchase_units(self, request: CheckoutRequest) -> list[dict[str, Any]]:
        raise NotImplementedError

    def order_body(self, request: CheckoutRequest) -> dict[str, Any]:
        return {
            "intent": "AUTHORIZE",
            "purchase_units": self.purchase_units(request),
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": BRAND_NAME,
                        "shipping_preference": "NO_SHIPPING",  # the agent's request already says where it goes
                        "user_action": "PAY_NOW",
                        "return_url": request.return_url,
                        "cancel_url": request.cancel_url,
                    }
                }
            },
        }

    def create_checkout(self, request: CheckoutRequest) -> Checkout:
        with paypal_errors():
            order = self.client.post(
                "/v2/checkout/orders", self.order_body(request), idempotency_key=f"openstall-checkout-{request.order_id}"
            )
        return Checkout(order["id"], approval_link(order))

    def get_order(self, paypal_order_id: str) -> OrderState:
        with paypal_errors():
            order = self.client.get(f"/v2/checkout/orders/{paypal_order_id}")
        return OrderState(order["status"], holds_of(order))

    def reserve(self, paypal_order_id: str) -> Reservation:
        with paypal_errors():
            order = self.client.post(
                f"/v2/checkout/orders/{paypal_order_id}/authorize",
                {},
                idempotency_key=f"openstall-reserve-{paypal_order_id}",
            )
        holds = holds_of(order)
        if not holds:
            raise PaymentError("NO_AUTHORIZATION", f"PayPal authorized order {paypal_order_id} but sent no authorization")
        return Reservation(paypal_order_id, holds)

    def capture(self, share: Share, body: dict[str, Any]) -> dict[str, Any]:
        with paypal_errors():
            return self.client.post(
                f"/v2/payments/authorizations/{share.hold_id}/capture",
                body,
                idempotency_key=f"openstall-capture-{share.part_id}",
            )

    def void(self, share: Share) -> None:
        with paypal_errors():
            self.client.post(
                f"/v2/payments/authorizations/{share.hold_id}/void",
                None,
                idempotency_key=f"openstall-release-{share.part_id}",
            )


class MultipartyGateway(SandboxGateway):
    """Each seller is a payee on the one PayPal order, so each share has its own authorization."""

    path = "multiparty"

    def purchase_units(self, request: CheckoutRequest) -> list[dict[str, Any]]:
        units = []
        for part in request.parts:
            if part.payee_merchant_id:
                payee = {"merchant_id": part.payee_merchant_id}
            elif part.payee_email:
                payee = {"email_address": part.payee_email}
            else:
                raise PaymentError("PAYEE_MISSING", f"no PayPal account is linked for {part.description}")
            units.append(
                {
                    "reference_id": part.reference_id,
                    "custom_id": request.order_id,
                    "description": part.description[:TEXT_LIMIT],
                    "amount": money(part.amount_usd),
                    "payee": payee,
                }
            )
        return units

    def pay_share(self, share: Share) -> Payment:
        capture = self.capture(share, {"final_capture": True})
        return Payment(capture_id=capture["id"])

    def release_share(self, share: Share) -> None:
        self.void(share)


class PayoutsGateway(SandboxGateway):
    """The platform holds one authorization for the whole order and pays each seller with Payouts when she ships."""

    path = "payouts"

    def purchase_units(self, request: CheckoutRequest) -> list[dict[str, Any]]:
        total = request.total_usd
        return [
            {
                "reference_id": WHOLE_ORDER,
                "custom_id": request.order_id,
                "description": f"{BRAND_NAME} order {request.order_id}"[:TEXT_LIMIT],
                "amount": {**money(total), "breakdown": {"item_total": money(total)}},
                # One line per maker, so the buyer sees at PayPal who makes what.
                "items": [
                    {
                        "name": part.description[:TEXT_LIMIT],
                        "sku": part.reference_id,
                        "quantity": "1",
                        "unit_amount": money(part.amount_usd),
                        "category": "PHYSICAL_GOODS",
                    }
                    for part in request.parts
                ],
            }
        ]

    def pay_share(self, share: Share) -> Payment:
        receiver = self.receiver(share)  # before capturing, so a seller with no account is never half paid
        capture = self.capture(share, {"amount": money(share.amount_usd), "final_capture": share.last})
        with paypal_errors():
            payout = self.client.post(
                "/v1/payments/payouts",
                {
                    "sender_batch_header": {
                        "sender_batch_id": f"openstall-{share.part_id}",  # PayPal refuses a batch id it has seen
                        "email_subject": "You have been paid for your OpenStall order",
                        "email_message": share.note or "Your share of an OpenStall Collective order.",
                    },
                    "items": [
                        {
                            **receiver,
                            "amount": {"currency": "USD", "value": f"{share.amount_usd:.2f}"},
                            "sender_item_id": share.part_id,
                            "note": share.note or "Your share of an OpenStall Collective order.",
                        }
                    ],
                },
                idempotency_key=f"openstall-payout-{share.part_id}",
            )
        return Payment(capture_id=capture["id"], payout_batch_id=payout["batch_header"]["payout_batch_id"])

    def release_share(self, share: Share) -> None:
        # Her amount is never captured. Only the last open share closes the hold, giving back whatever is left.
        if share.last:
            self.void(share)

    @staticmethod
    def receiver(share: Share) -> dict[str, str]:
        if share.payee_email:
            return {"recipient_type": "EMAIL", "receiver": share.payee_email}
        if share.payee_merchant_id:
            return {"recipient_type": "PAYPAL_ID", "receiver": share.payee_merchant_id}
        raise PaymentError("PAYEE_MISSING", f"no PayPal account is linked for share {share.part_id}")
