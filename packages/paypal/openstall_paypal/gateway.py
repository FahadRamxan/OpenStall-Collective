"""The payment gateway (spec 3.5): the only way our code reaches PayPal, and a deterministic fake of it.

The real adapter uses the PayPal sandbox client. FakeGateway stands in for it in fake mode: orders are approved by
calling approve(), as the simulated PayPal page will, and nothing leaves the process.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

# PayPal's names for the state of an order.
OrderStatus = Literal["CREATED", "APPROVED", "COMPLETED"]


class PaymentError(Exception):
    """PayPal refused a request. `issue` is PayPal's issue code, for example "ORDER_NOT_APPROVED"."""

    def __init__(self, issue: str, message: str) -> None:
        super().__init__(f"{issue}: {message}")
        self.issue = issue


@dataclass(frozen=True)
class CheckoutPart:
    """One seller's share of an order: one PayPal purchase unit."""

    reference_id: str  # our order part id, for example "op_001"
    amount_usd: Decimal  # worked out on the server, to the cent
    description: str  # for example "12 cushion covers, Amina"
    payee_merchant_id: str | None = None  # the seller's PayPal merchant id; None pays the platform account


@dataclass(frozen=True)
class CheckoutRequest:
    """What the human approves at PayPal: one order, with one part per seller."""

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
class Capture:
    """The money taken for an approved order: PayPal's capture id for each part, by reference_id."""

    paypal_order_id: str
    capture_ids: Mapping[str, str]


@runtime_checkable
class PaymentGateway(Protocol):
    def create_checkout(self, request: CheckoutRequest) -> Checkout:
        """Create the PayPal order. The same order_id always gives back the same PayPal order."""
        ...

    def get_order_status(self, paypal_order_id: str) -> OrderStatus:
        """PayPal's current state for the order: read it before capturing, and after a capture that failed."""
        ...

    def capture(self, paypal_order_id: str) -> Capture:
        """Take the money for an approved order. Raises PaymentError if PayPal refuses."""
        ...


@dataclass
class _FakeOrder:
    request: CheckoutRequest
    status: OrderStatus = "CREATED"


class FakeGateway:
    """PayPal without the network. Records every gateway call in `calls`, as (method name, argument).

    PayPal order ids come from our order id, so they are the same on every run, and a repeated checkout returns the
    first PayPal order, as PayPal does for a repeated PayPal-Request-Id.
    """

    def __init__(self, web_base_url: str = "http://localhost:3000") -> None:
        self.web_base_url = web_base_url.rstrip("/")
        self.calls: list[tuple[str, object]] = []
        self._orders: dict[str, _FakeOrder] = {}

    def create_checkout(self, request: CheckoutRequest) -> Checkout:
        self.calls.append(("create_checkout", request))
        paypal_order_id = "FAKE-" + hashlib.sha256(request.order_id.encode()).hexdigest()[:16].upper()
        self._orders.setdefault(paypal_order_id, _FakeOrder(request))
        return Checkout(paypal_order_id, f"{self.web_base_url}/fake-paypal?token={paypal_order_id}")

    def approve(self, paypal_order_id: str) -> None:
        """The buyer approves the order on the simulated PayPal page. Not part of PaymentGateway, so not recorded."""
        order = self._order(paypal_order_id)
        if order.status == "CREATED":
            order.status = "APPROVED"

    def get_order_status(self, paypal_order_id: str) -> OrderStatus:
        self.calls.append(("get_order_status", paypal_order_id))
        return self._order(paypal_order_id).status

    def capture(self, paypal_order_id: str) -> Capture:
        self.calls.append(("capture", paypal_order_id))
        order = self._order(paypal_order_id)
        if order.status == "COMPLETED":
            raise PaymentError("ORDER_ALREADY_CAPTURED", f"order {paypal_order_id} was already captured")
        if order.status != "APPROVED":
            raise PaymentError("ORDER_NOT_APPROVED", f"the buyer has not approved order {paypal_order_id}")
        order.status = "COMPLETED"
        return Capture(
            paypal_order_id,
            {part.reference_id: f"{paypal_order_id}-CAP-{n}" for n, part in enumerate(order.request.parts, start=1)},
        )

    def _order(self, paypal_order_id: str) -> _FakeOrder:
        try:
            return self._orders[paypal_order_id]
        except KeyError:
            raise PaymentError("RESOURCE_NOT_FOUND", f"no order {paypal_order_id}") from None
