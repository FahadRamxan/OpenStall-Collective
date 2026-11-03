"""The payment gateway (spec 3.5, pay-on-proof): the only way our code reaches PayPal, and a deterministic fake of it.

Approving an order only reserves the money: the PayPal order has intent AUTHORIZE, so nothing is taken when the
human approves. Each seller's share is captured on its own when her proof of shipping is confirmed (pay_share), or
released if she cannot deliver (release_share). The sandbox gateways are in sandbox.py; FakeGateway stands in for them
in fake mode, and its orders are approved on the simulated PayPal page.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

# PayPal's names for the state of an order. An order made with an experience context starts as
# PAYER_ACTION_REQUIRED rather than CREATED; both mean the buyer has not approved it yet.
PayPalOrderStatus = Literal["CREATED", "PAYER_ACTION_REQUIRED", "SAVED", "APPROVED", "VOIDED", "COMPLETED"]
WAITING_FOR_BUYER: frozenset[str] = frozenset({"CREATED", "PAYER_ACTION_REQUIRED"})

# The key of a reservation whose one authorization holds every share (the payouts path).
WHOLE_ORDER = "whole_order"

# How a maker is paid once her share is captured (spec 3.5a; rails.py decides which). "unavailable": no rail can
# reach her yet, so her share is never captured. "hyperwallet" is for prompt 52 and is not connected yet.
PayoutRail = Literal["paypal", "venmo", "hyperwallet", "unavailable"]

# Which payment path a gateway follows (docs/decisions.md, "Payment path: payouts only").
PaymentPath = Literal["payouts", "multiparty"]


class PaymentError(Exception):
    """PayPal refused a request. `issue` is PayPal's issue code, for example "ORDER_NOT_APPROVED"."""

    def __init__(self, issue: str, message: str) -> None:
        super().__init__(f"{issue}: {message}")
        self.issue = issue
        self.message = message


class PaymentUnavailable(PaymentError):
    """PayPal did not answer, so the request may or may not have taken effect. Read the state back before acting
    again; never repeat a payment blindly (spec 3.5).

    `outcome_unknown` is False only when the request provably never reached PayPal (the connection was refused, or
    getting a token failed first), so nothing happened there. True means it may have landed.
    """

    def __init__(self, issue: str, message: str, *, outcome_unknown: bool = True) -> None:
        super().__init__(issue, message)
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True)
class CheckoutPart:
    """One seller's share of an order."""

    reference_id: str  # our order part's reference, for example "op_001"
    amount_usd: Decimal  # worked out on the server, to the cent
    description: str  # for example "12 cushion covers, Amina"
    payee_merchant_id: str | None = None  # the seller's PayPal merchant id, when she has one
    payee_email: str | None = None  # her PayPal email, when there is no merchant id


@dataclass(frozen=True)
class CheckoutRequest:
    """What the human approves at PayPal: one order for the whole amount, with every seller's share."""

    order_id: str  # our order id: a repeated checkout for it must not create a second PayPal order
    parts: tuple[CheckoutPart, ...]
    return_url: str
    cancel_url: str

    @property
    def total_usd(self) -> Decimal:
        return sum((part.amount_usd for part in self.parts), Decimal("0.00"))


@dataclass(frozen=True)
class Checkout:
    """A PayPal order waiting for the human, who approves it at `approval_url`."""

    paypal_order_id: str
    approval_url: str


@dataclass(frozen=True)
class Reservation:
    """The money PayPal holds for an approved order: the authorization holding each share.

    `holds` maps each share's reference_id to its authorization id. On the payouts path one authorization holds every
    share, under the key WHOLE_ORDER.
    """

    paypal_order_id: str
    holds: Mapping[str, str]

    def hold_for(self, reference_id: str) -> str | None:
        return self.holds.get(reference_id) or self.holds.get(WHOLE_ORDER)


@dataclass(frozen=True)
class OrderState:
    """PayPal's view of an order: its status, and the authorizations once it is reserved."""

    status: PayPalOrderStatus
    holds: Mapping[str, str]


@dataclass(frozen=True)
class Share:
    """One seller's share, to pay on proof of shipping or to release."""

    part_id: str  # our order part id: every payment of it uses it as the idempotency key, so it is never paid twice
    hold_id: str  # the authorization holding it
    amount_usd: Decimal
    payee_merchant_id: str | None = None
    payee_email: str | None = None
    note: str = ""  # shown to the seller with her payment
    last: bool = True  # no other share of the order is still reserved, so whatever the hold has left can be freed
    payout_rail: PayoutRail = "paypal"  # how she is paid once her share is captured (rails.rail_for)
    venmo_handle: str | None = None  # her Venmo handle, on the Venmo rail


@dataclass(frozen=True)
class Payment:
    """A share that was paid: the capture, and on the payouts path the payout batch that sent it to the seller.

    `payout_simulated`: her payout was not sent at all, only recorded (Venmo payouts in PayPal's sandbox, which refuses
    them). Her capture is real either way.
    """

    capture_id: str
    payout_batch_id: str | None = None
    payout_rail: PayoutRail | None = None
    payout_simulated: bool = False


@runtime_checkable
class PaymentGateway(Protocol):
    def create_checkout(self, request: CheckoutRequest) -> Checkout:
        """Create the PayPal order. The same order_id always gives back the same PayPal order."""
        ...

    def get_order(self, paypal_order_id: str) -> OrderState:
        """PayPal's current state for the order: read it before reserving, and after a call that failed."""
        ...

    def reserve(self, paypal_order_id: str) -> Reservation:
        """Authorize an approved order: the whole amount is held, and nothing is taken yet. Safe to repeat."""
        ...

    def pay_share(self, share: Share) -> Payment:
        """Capture one seller's share and pay her. Safe to repeat: a share is paid at most once."""
        ...

    def release_share(self, share: Share) -> None:
        """Give one seller's share back to the buyer. Refused once the share is paid."""
        ...


@dataclass
class _FakeOrder:
    request: CheckoutRequest
    status: PayPalOrderStatus = "PAYER_ACTION_REQUIRED"
    holds: dict[str, str] = field(default_factory=dict)


@dataclass
class _FakeAuthorization:
    """The payouts path's one authorization for a whole order: how much it holds, and how much is captured."""

    paypal_order_id: str
    amount: Decimal
    captured: Decimal = Decimal("0.00")
    captures: int = 0
    # CREATED: open. CAPTURED: closed by a final capture. VOIDED: closed by a void. A closed hold takes nothing more.
    state: Literal["CREATED", "CAPTURED", "VOIDED"] = "CREATED"

    @property
    def remaining(self) -> Decimal:
        return self.amount - self.captured


@dataclass(frozen=True)
class FakeOrderView:
    """What the simulated PayPal page shows: the order as the buyer sees it at PayPal."""

    paypal_order_id: str
    status: PayPalOrderStatus
    request: CheckoutRequest


def _money(amount: Decimal) -> dict[str, str]:
    return {"currency_code": "USD", "value": f"{amount:.2f}"}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16].upper()


class FakeGateway:
    """PayPal without the network, following the same rules. Records every gateway call in `calls`.

    PayPal order ids come from our order id, so they are the same on every run, and a repeated checkout returns the
    first PayPal order, as PayPal does for a repeated PayPal-Request-Id. Like PayPal, it sends a webhook event for
    each approval, authorization, capture, void and payout: they wait in `outbox` until the app delivers them to its
    own webhook endpoint.

    `path` follows the sandbox gateway of the same name:
    - "payouts" (the default, and the path we run): one authorization holds the whole order. Paying a share is a
      partial capture of her amount (final_capture only on the last), then a simulated Payouts item to her rail.
      Releasing a share captures nothing; only the last release voids whatever the hold has left.
    - "multiparty" (a recorded dead end): each share has its own authorization, captured or voided whole.
    """

    def __init__(self, web_base_url: str = "http://localhost:3000", path: PaymentPath = "payouts") -> None:
        self.web_base_url = web_base_url.rstrip("/")
        self.path = path
        self.calls: list[tuple[str, object]] = []
        self.outbox: list[dict[str, Any]] = []
        self._orders: dict[str, _FakeOrder] = {}
        self._holds: dict[str, Literal["CREATED", "CAPTURED", "VOIDED"]] = {}  # multiparty: one per share
        self._authorizations: dict[str, _FakeAuthorization] = {}  # payouts: one per order
        self._hold_orders: dict[str, str] = {}  # authorization id -> PayPal order id
        self._payments: dict[str, Payment] = {}

    def take_outbox(self) -> list[dict[str, Any]]:
        """The webhook events waiting to be sent, oldest first; the outbox is then empty."""
        events, self.outbox = self.outbox, []
        return events

    def _send_event(self, event_type: str, resource_type: str, resource: dict[str, Any], summary: str) -> None:
        from openstall_paypal.webhooks import fake_event  # webhooks imports the sandbox module, which imports this

        self.outbox.append(fake_event(event_type, resource_type, resource, summary))

    def create_checkout(self, request: CheckoutRequest) -> Checkout:
        self.calls.append(("create_checkout", request))
        paypal_order_id = "FAKE-" + hashlib.sha256(request.order_id.encode()).hexdigest()[:16].upper()
        self._orders.setdefault(paypal_order_id, _FakeOrder(request))
        return Checkout(paypal_order_id, f"{self.web_base_url}/fake-paypal?token={paypal_order_id}")

    # The simulated PayPal page's side. These are the buyer's actions, not ours, so they are not recorded in calls.

    def view(self, paypal_order_id: str) -> FakeOrderView:
        order = self._order(paypal_order_id)
        return FakeOrderView(paypal_order_id, order.status, order.request)

    def approve(self, paypal_order_id: str) -> FakeOrderView:
        """The buyer approves the order. Approving it again changes nothing."""
        order = self._order(paypal_order_id)
        if order.status in WAITING_FOR_BUYER:
            order.status = "APPROVED"
            self._send_event(
                "CHECKOUT.ORDER.APPROVED",
                "checkout-order",
                {"id": paypal_order_id, "status": "APPROVED", "intent": "AUTHORIZE"},
                f"An order for ${order.request.total_usd:.2f} was approved",
            )
        return FakeOrderView(paypal_order_id, order.status, order.request)

    # PaymentGateway.

    def get_order(self, paypal_order_id: str) -> OrderState:
        self.calls.append(("get_order", paypal_order_id))
        order = self._order(paypal_order_id)
        return OrderState(order.status, dict(order.holds))

    def reserve(self, paypal_order_id: str) -> Reservation:
        self.calls.append(("reserve", paypal_order_id))
        order = self._order(paypal_order_id)
        if order.status == "COMPLETED":  # already reserved: PayPal answers a repeated request with the first answer
            return Reservation(paypal_order_id, dict(order.holds))
        if order.status != "APPROVED":
            raise PaymentError("ORDER_NOT_APPROVED", f"the buyer has not approved order {paypal_order_id}")
        if self.path == "payouts":
            self._reserve_whole_order(paypal_order_id, order)
        else:
            self._reserve_each_share(paypal_order_id, order)
        order.status = "COMPLETED"
        return Reservation(paypal_order_id, dict(order.holds))

    def _authorization_event(self, hold: str, amount: Decimal, order: _FakeOrder, paypal_order_id: str) -> None:
        self._send_event(
            "PAYMENT.AUTHORIZATION.CREATED",
            "authorization",
            {
                "id": hold,
                "status": "CREATED",
                "amount": _money(amount),
                "custom_id": order.request.order_id,
                "supplementary_data": {"related_ids": {"order_id": paypal_order_id}},
            },
            f"A payment of ${amount:.2f} was authorized",
        )

    def _reserve_whole_order(self, paypal_order_id: str, order: _FakeOrder) -> None:
        hold = f"{paypal_order_id}-AUTH"
        order.holds[WHOLE_ORDER] = hold
        self._authorizations[hold] = _FakeAuthorization(paypal_order_id, order.request.total_usd)
        self._hold_orders[hold] = paypal_order_id
        self._authorization_event(hold, order.request.total_usd, order, paypal_order_id)

    def _reserve_each_share(self, paypal_order_id: str, order: _FakeOrder) -> None:
        for number, part in enumerate(order.request.parts, start=1):
            hold = f"{paypal_order_id}-AUTH-{number}"
            order.holds[part.reference_id] = hold
            self._holds[hold] = "CREATED"
            self._hold_orders[hold] = paypal_order_id
        for part in order.request.parts:
            self._authorization_event(order.holds[part.reference_id], part.amount_usd, order, paypal_order_id)

    def pay_share(self, share: Share) -> Payment:
        self.calls.append(("pay_share", share))
        if share.part_id in self._payments:
            return self._payments[share.part_id]
        if self.path == "payouts":
            return self._capture_and_pay_out(share)
        state = self._hold(share.hold_id)
        if state == "VOIDED":
            raise PaymentError("AUTHORIZATION_VOIDED", f"authorization {share.hold_id} was voided, so it cannot be paid")
        if state == "CAPTURED":
            raise PaymentError("AUTHORIZATION_ALREADY_CAPTURED", f"authorization {share.hold_id} was already captured")
        self._holds[share.hold_id] = "CAPTURED"
        payment = Payment(capture_id=f"{share.hold_id}-CAP")
        self._payments[share.part_id] = payment
        self._capture_event(share, payment.capture_id, final_capture=True)
        return payment

    def _capture_event(self, share: Share, capture_id: str, *, final_capture: bool) -> None:
        self._send_event(
            "PAYMENT.CAPTURE.COMPLETED",
            "capture",
            {
                "id": capture_id,
                "status": "COMPLETED",
                "amount": _money(share.amount_usd),
                "invoice_id": share.part_id,
                "final_capture": final_capture,
                "supplementary_data": {
                    "related_ids": {
                        "order_id": self._hold_orders.get(share.hold_id),
                        "authorization_id": share.hold_id,
                    }
                },
            },
            f"A payment of ${share.amount_usd:.2f} was captured",
        )

    def _capture_and_pay_out(self, share: Share) -> Payment:
        """The payouts path: a partial capture of her amount from the order's one authorization, then her payout."""
        # Checked before capturing, as PayoutsGateway does, so a share is never captured without a way to pay her.
        if share.payout_rail not in ("paypal", "venmo"):
            raise PaymentError(
                "PAYOUT_RAIL_UNAVAILABLE", f"no payout rail can reach the maker of share {share.part_id} yet"
            )
        hold = self._authorization(share.hold_id)
        if hold.state == "VOIDED":
            raise PaymentError("AUTHORIZATION_VOIDED", f"authorization {share.hold_id} was voided, so it cannot be paid")
        if hold.state == "CAPTURED":
            raise PaymentError(
                "AUTHORIZATION_ALREADY_CAPTURED", f"authorization {share.hold_id} was closed by its final capture"
            )
        if share.amount_usd > hold.remaining:
            raise PaymentError(
                "EXCEEDS_REMAINING_AUTHORIZATION",
                f"${share.amount_usd:.2f} is more than the ${hold.remaining:.2f} left on authorization {share.hold_id}",
            )
        hold.captured += share.amount_usd
        hold.captures += 1
        if share.last:
            hold.state = "CAPTURED"
        capture_id = f"{share.hold_id}-CAP-{hold.captures}"
        self._capture_event(share, capture_id, final_capture=share.last)

        batch_id = f"FAKE-BATCH-{_digest(share.part_id)}"
        venmo = share.payout_rail == "venmo"
        item: dict[str, Any] = {
            "recipient_type": "USER_HANDLE" if venmo else "EMAIL",
            "recipient_wallet": "Venmo" if venmo else "PAYPAL",
            "amount": {"currency": "USD", "value": f"{share.amount_usd:.2f}"},
            "note": share.note or "Your share of an OpenStall Collective order.",
            "sender_item_id": share.part_id,
        }
        receiver = share.venmo_handle if venmo else share.payee_email or share.payee_merchant_id
        if receiver:
            item["receiver"] = receiver
        self._send_event(
            "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
            "payouts_item",
            {
                "payout_item_id": f"FAKE-ITEM-{_digest(share.part_id)}",
                "transaction_id": f"FAKE-TXN-{_digest(share.part_id)}",
                "transaction_status": "SUCCESS",
                "payout_batch_id": batch_id,
                "payout_item": item,
            },
            f"A payout of ${share.amount_usd:.2f} to {'Venmo' if venmo else 'PayPal'} succeeded",
        )
        payment = Payment(capture_id=capture_id, payout_batch_id=batch_id, payout_rail=share.payout_rail)
        self._payments[share.part_id] = payment
        return payment

    def release_share(self, share: Share) -> None:
        self.calls.append(("release_share", share))
        if self.path == "payouts":
            self._release_from_whole_order(share)
            return
        if self._hold(share.hold_id) == "CAPTURED":
            raise PaymentError(
                "AUTHORIZATION_ALREADY_CAPTURED", f"authorization {share.hold_id} was captured, so it cannot be voided"
            )
        if self._holds[share.hold_id] == "VOIDED":
            return
        self._holds[share.hold_id] = "VOIDED"
        self._send_event(
            "PAYMENT.AUTHORIZATION.VOIDED",
            "authorization",
            {"id": share.hold_id, "status": "VOIDED", "amount": _money(share.amount_usd)},
            f"A payment of ${share.amount_usd:.2f} was voided",
        )

    def _release_from_whole_order(self, share: Share) -> None:
        """Her amount is simply never captured. Only the last open share voids what the hold has left."""
        if share.part_id in self._payments:
            raise PaymentError("SHARE_ALREADY_CAPTURED", f"share {share.part_id} was paid, so it cannot be released")
        hold = self._authorization(share.hold_id)
        if not share.last or hold.state != "CREATED":
            return
        hold.state = "VOIDED"
        self._send_event(
            "PAYMENT.AUTHORIZATION.VOIDED",
            "authorization",
            {"id": share.hold_id, "status": "VOIDED", "amount": _money(hold.remaining)},
            f"The remaining ${hold.remaining:.2f} was voided",
        )

    def authorization(self, hold_id: str) -> tuple[Decimal, Decimal, str]:
        """The payouts path's hold as tests see it: (amount held, amount captured, state)."""
        hold = self._authorization(hold_id)
        return hold.amount, hold.captured, hold.state

    def _order(self, paypal_order_id: str) -> _FakeOrder:
        try:
            return self._orders[paypal_order_id]
        except KeyError:
            raise PaymentError("RESOURCE_NOT_FOUND", f"no order {paypal_order_id}") from None

    def _hold(self, hold_id: str) -> Literal["CREATED", "CAPTURED", "VOIDED"]:
        try:
            return self._holds[hold_id]
        except KeyError:
            raise PaymentError("RESOURCE_NOT_FOUND", f"no authorization {hold_id}") from None

    def _authorization(self, hold_id: str) -> _FakeAuthorization:
        try:
            return self._authorizations[hold_id]
        except KeyError:
            raise PaymentError("RESOURCE_NOT_FOUND", f"no authorization {hold_id}") from None
