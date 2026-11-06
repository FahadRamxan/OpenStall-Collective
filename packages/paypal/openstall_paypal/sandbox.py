"""The PayPal sandbox gateways, one for each payment path. PAYMENT_PATH picks one (docs/day-one-checks.md says why).

Both create the order with intent AUTHORIZE and authorize it when the buyer comes back, so approving only reserves
the money. They differ in who the payees are:

- MultipartyGateway: each seller is the payee of her own purchase unit, so each share has its own authorization.
  Paying a share captures her authorization; releasing it voids that authorization.
- PayoutsGateway: the platform is the only payee and holds one authorization for the whole order, with each share
  listed as an item. Paying a share captures just her amount and sends it to her with PayPal Payouts on her payout
  rail (rails.py: PayPal, or Venmo in the US). Releasing a share leaves her amount uncaptured; the order's last
  capture or void gives whatever is left back to the buyer. This is the path we run; multiparty is a dead end.

Every Orders and Payments call goes through APIMatic's PayPal Python SDK (sdk.py; the contract sheet is
paypal-plan.md). Payouts are not in that SDK, so they go through our own PayPalClient, which also verifies webhooks.

Every write uses an idempotency key made from our own ids, sent as PayPal-Request-Id, so repeating a call never
reserves or pays twice. Each capture carries our part id as its invoice_id, so PayPal's capture webhooks name the
share they are about.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from typing import Self, cast

from paypal.core import UnsetType
from paypal.models import (
    AmountBreakdown,
    AmountWithBreakdown,
    CaptureRequest,
    ItemRequest,
    Money,
    Order,
    OrderAuthorizeRequest,
    OrderAuthorizeResponse,
    OrderRequest,
    OrderTrackerRequest,
    PayeeBase,
    PaymentSource,
    PayPalWallet,
    PayPalWalletExperienceContext,
    PurchaseUnitRequest,
)
from paypal.models.enums import (
    CheckoutPaymentIntent,
    ItemCategory,
    OrderStatus,
    PayPalExperienceUserAction,
    PayPalWalletContextShippingPreference,
)

from openstall_paypal.client import PayPalClient, PayPalError, PayPalUnavailable
from openstall_paypal.gateway import (
    Advance,
    AdvancePayment,
    WHOLE_ORDER,
    Checkout,
    CheckoutRequest,
    OrderState,
    Payment,
    PaymentError,
    PaymentUnavailable,
    PayPalOrderStatus,
    Reservation,
    Share,
    Tracking,
)
from openstall_paypal.rails import DEFAULT_NOTE, payout_item, receiver, venmo_payouts_simulated
from openstall_paypal.sdk import REPRESENTATION, PayPalSdk
from openstall_paypal.tracking import OTHER, UNNAMED, tracker_for

BRAND_NAME = "OpenStall Collective"
TEXT_LIMIT = 127  # PayPal's limit for descriptions and item names


def money(amount: Decimal) -> Money:
    """US dollars as PayPal writes them: a string with two decimals, made from a Decimal, never a float."""
    return Money(currency_code="USD", value=f"{amount:.2f}")


def order_id_of(order: Order) -> str:
    return order.id if not isinstance(order.id, UnsetType) else "(no id)"


def approval_link(order: Order) -> str:
    """Where the buyer approves the order: rel "payer-action" for orders made with an experience context, "approve"
    on older responses."""
    links = {} if isinstance(order.links, UnsetType) else {link.rel: link.href for link in order.links}
    href = links.get("payer-action") or links.get("approve")
    if not href:
        raise PaymentError("NO_APPROVAL_LINK", f"PayPal created order {order_id_of(order)} without an approval link")
    return href


def holds_of(order: Order | OrderAuthorizeResponse) -> dict[str, str]:
    """The authorization on each purchase unit, by reference_id. Empty until the order is authorized."""
    holds: dict[str, str] = {}
    if isinstance(order.purchase_units, UnsetType):
        return holds
    for unit in order.purchase_units:
        if isinstance(unit.payments, UnsetType) or isinstance(unit.payments.authorizations, UnsetType):
            continue
        authorizations = unit.payments.authorizations
        if authorizations and not isinstance(authorizations[0].id, UnsetType):
            reference = unit.reference_id if not isinstance(unit.reference_id, UnsetType) else "default"
            holds[reference] = authorizations[0].id
    return holds


def trackers_of(order: Order) -> tuple[str, ...]:
    """The ids of the order's shipment trackers, on every purchase unit, oldest first as PayPal lists them."""
    found: list[str] = []
    if isinstance(order.purchase_units, UnsetType):
        return ()
    for unit in order.purchase_units:
        if isinstance(unit.shipping, UnsetType) or isinstance(unit.shipping.trackers, UnsetType):
            continue
        found += [tracker.id for tracker in unit.shipping.trackers if not isinstance(tracker.id, UnsetType)]
    return tuple(found)


def order_status(order: Order) -> PayPalOrderStatus:
    """The order's status as PayPal's wire value. A value newer than the SDK arrives as a plain string and is kept."""
    status = order.status
    if isinstance(status, UnsetType):
        raise PaymentUnavailable("PAYPAL_UNREADABLE", f"PayPal sent order {order_id_of(order)} without a status")
    return cast(PayPalOrderStatus, status.value if isinstance(status, OrderStatus) else status)


@contextmanager
def paypal_errors() -> Iterator[None]:
    """Our PayPalClient's errors (payouts, webhook checks) as the gateway's errors, keeping PayPal's issue code."""
    try:
        yield
    except PayPalUnavailable as error:
        raise PaymentUnavailable(error.issue or "PAYPAL_UNAVAILABLE", str(error)) from error
    except PayPalError as error:
        raise PaymentError(error.issue or "PAYPAL_ERROR", str(error)) from error


class SandboxGateway:
    """What both paths share: the order is made with intent AUTHORIZE, read back, and authorized on return.

    `sdk` makes the Orders and Payments calls; `client` (our own PayPalClient) sends payouts, verifies webhooks and
    gives the status page its token check.
    """

    path = ""

    def __init__(self, client: PayPalClient, sdk: PayPalSdk) -> None:
        self.client = client
        self.sdk = sdk

    @classmethod
    def connect(cls, base_url: str, client_id: str, secret: str) -> Self:
        """Both clients for one PayPal REST app. Made once per process: each keeps its token and connections."""
        return cls(PayPalClient(base_url, client_id, secret), PayPalSdk(base_url, client_id, secret))

    def close(self) -> None:
        self.sdk.close()
        self.client.close()

    def purchase_units(self, request: CheckoutRequest) -> list[PurchaseUnitRequest]:
        raise NotImplementedError

    def order_body(self, request: CheckoutRequest) -> OrderRequest:
        return OrderRequest(
            intent=CheckoutPaymentIntent.AUTHORIZE,
            purchase_units=self.purchase_units(request),
            payment_source=PaymentSource(
                paypal=PayPalWallet(
                    experience_context=PayPalWalletExperienceContext(
                        brand_name=BRAND_NAME,
                        # The agent's request already says where it goes.
                        shipping_preference=PayPalWalletContextShippingPreference.NO_SHIPPING,
                        user_action=PayPalExperienceUserAction.PAY_NOW,
                        return_url=request.return_url,
                        cancel_url=request.cancel_url,
                    )
                )
            ),
        )

    def create_checkout(self, request: CheckoutRequest) -> Checkout:
        body = self.order_body(request)  # first, so a seller with no PayPal account stops it before PayPal is asked
        order = self.sdk.call(
            lambda: self.sdk.client.orders.create_order(
                body, pay_pal_request_id=f"openstall-checkout-{request.order_id}", prefer=REPRESENTATION
            )
        )
        if isinstance(order.id, UnsetType):  # it may have been created: read it back rather than guess
            raise PaymentUnavailable("PAYPAL_UNREADABLE", f"PayPal sent no order id for order {request.order_id}")
        return Checkout(order.id, approval_link(order))

    def get_order(self, paypal_order_id: str) -> OrderState:
        order = self.sdk.call(lambda: self.sdk.client.orders.get_order(paypal_order_id))
        return OrderState(order_status(order), holds_of(order), trackers_of(order))

    def add_tracking(self, tracking: Tracking) -> str:
        """Her tracking on her capture (`create_order_tracking`). This route takes no PayPal-Request-Id, so the caller
        has read the order's trackers first (`tracking.known_trackers`); ours in the answer is the tracker holding the
        tracking number, or the one new tracker. Without either, the outcome is unknown: read back, never resent."""
        # carrier_name_other only with OTHER, as PayPal asks; left out (UNSET) otherwise. notify_payer False: PayPal's
        # app may still tell the payer, and we send no extra email per parcel.
        if tracking.carrier == OTHER:
            body = OrderTrackerRequest(
                capture_id=tracking.capture_id,
                tracking_number=tracking.tracking_number,
                carrier=OTHER,
                carrier_name_other=tracking.carrier_name_other or UNNAMED,
                notify_payer=False,
            )
        else:
            body = OrderTrackerRequest(
                capture_id=tracking.capture_id,
                tracking_number=tracking.tracking_number,
                carrier=tracking.carrier,
                notify_payer=False,
            )
        order = self.sdk.call(
            lambda: self.sdk.client.orders.create_order_tracking(tracking.paypal_order_id, body)
        )
        tracker = tracker_for(trackers_of(order), tracking.tracking_number, tracking.known_trackers)
        if tracker is None:
            raise PaymentUnavailable(
                "PAYPAL_UNREADABLE", f"PayPal's answer showed no new tracker for share {tracking.part_id}"
            )
        return tracker

    def reserve(self, paypal_order_id: str) -> Reservation:
        answer = self.sdk.call(
            lambda: self.sdk.client.orders.authorize_order(
                paypal_order_id,
                pay_pal_request_id=f"openstall-reserve-{paypal_order_id}",
                prefer=REPRESENTATION,
                body=OrderAuthorizeRequest(),
            )
        )
        holds = holds_of(answer)
        if not holds:
            raise PaymentError("NO_AUTHORIZATION", f"PayPal authorized order {paypal_order_id} but sent no authorization")
        return Reservation(paypal_order_id, holds)

    def capture(self, share: Share, body: CaptureRequest) -> str:
        """Capture from the share's authorization; PayPal's capture id."""
        capture = self.sdk.call(
            lambda: self.sdk.client.payments.capture_authorized_payment(
                share.hold_id,
                pay_pal_request_id=f"openstall-capture-{share.part_id}",
                prefer=REPRESENTATION,
                body=body,
            )
        )
        if isinstance(capture.id, UnsetType):  # it may have been captured: never assume it was not
            raise PaymentUnavailable("PAYPAL_UNREADABLE", f"PayPal sent no capture id for share {share.part_id}")
        return capture.id

    def void(self, share: Share) -> None:
        try:
            self.sdk.call(
                lambda: self.sdk.client.payments.void_payment(
                    share.hold_id, pay_pal_request_id=f"openstall-release-{share.part_id}", prefer=REPRESENTATION
                )
            )
        except PaymentUnavailable:
            # 204 No Content is a successful void too; the SDK cannot decode its empty body, and we read none of it.
            if self.sdk.wire.last().status == 204:
                return
            raise


class _NoAdvances:
    def pay_advance(self, advance: Advance) -> AdvancePayment:
        raise PaymentError("ADVANCE_UNAVAILABLE", "advances are paid out by the platform, on the payouts path")


class MultipartyGateway(_NoAdvances, SandboxGateway):
    """Each seller is a payee on the one PayPal order, so each share has its own authorization.

    A recorded dead end, kept out of the demo and the README: the Orders v2 schema (v2.36) says intent AUTHORIZE "is
    not supported when you have more than one purchase_unit", and PayPal's multi-seller guide requires CAPTURE, so
    this path cannot do pay-on-proof (docs/decisions.md, "Payment path: payouts only").
    """

    path = "multiparty"

    def purchase_units(self, request: CheckoutRequest) -> list[PurchaseUnitRequest]:
        units = []
        for part in request.parts:
            if part.payee_merchant_id:
                payee = PayeeBase(merchant_id=part.payee_merchant_id)
            elif part.payee_email:
                payee = PayeeBase(email_address=part.payee_email)
            else:
                raise PaymentError("PAYEE_MISSING", f"no PayPal account is linked for {part.description}")
            units.append(
                PurchaseUnitRequest(
                    reference_id=part.reference_id,
                    custom_id=request.order_id,
                    description=part.description[:TEXT_LIMIT],
                    amount=AmountWithBreakdown(currency_code="USD", value=f"{part.amount_usd:.2f}"),
                    payee=payee,
                )
            )
        return units

    def pay_share(self, share: Share) -> Payment:
        return Payment(capture_id=self.capture(share, CaptureRequest(invoice_id=share.part_id, final_capture=True)))

    def release_share(self, share: Share) -> None:
        self.void(share)


class PayoutsGateway(SandboxGateway):
    """The platform holds one authorization for the whole order and pays each seller with Payouts when she ships.

    `simulate_venmo`: record a Venmo payout instead of sending it. PayPal's sandbox refuses every Venmo payout
    ("Recipient wallet not supported in sandbox"), and a refusal after the capture would leave her half paid, so on
    the sandbox her capture is real and her payout is simulated (and labelled so). By default it follows the host.
    """

    path = "payouts"

    def __init__(self, client: PayPalClient, sdk: PayPalSdk, *, simulate_venmo: bool | None = None) -> None:
        super().__init__(client, sdk)
        self.simulate_venmo = venmo_payouts_simulated(client.base_url) if simulate_venmo is None else simulate_venmo

    def purchase_units(self, request: CheckoutRequest) -> list[PurchaseUnitRequest]:
        total = request.total_usd
        return [
            PurchaseUnitRequest(
                reference_id=WHOLE_ORDER,
                custom_id=request.order_id,
                description=f"{BRAND_NAME} order {request.order_id}"[:TEXT_LIMIT],
                amount=AmountWithBreakdown(
                    currency_code="USD", value=f"{total:.2f}", breakdown=AmountBreakdown(item_total=money(total))
                ),
                # One line per maker, so the buyer sees at PayPal who makes what.
                items=[
                    ItemRequest(
                        name=part.description[:TEXT_LIMIT],
                        sku=part.reference_id,
                        quantity="1",
                        unit_amount=money(part.amount_usd),
                        category=ItemCategory.PHYSICAL_GOODS,
                    )
                    for part in request.parts
                ],
            )
        ]

    def pay_share(self, share: Share) -> Payment:
        # Her rail and her payout item first, so a maker no rail can reach is never captured and left half paid.
        if share.payout_rail == "unavailable":
            raise PaymentError(
                "PAYOUT_RAIL_UNAVAILABLE", f"no payout rail can reach the maker of share {share.part_id} yet"
            )
        item = payout_item(share)
        capture_id = self.capture(
            share, CaptureRequest(amount=money(share.amount_usd), invoice_id=share.part_id, final_capture=share.last)
        )
        if share.payout_rail == "venmo" and self.simulate_venmo:
            return Payment(capture_id=capture_id, payout_rail="venmo", payout_simulated=True)
        with paypal_errors():
            payout = self.client.post(
                "/v1/payments/payouts",
                {
                    "sender_batch_header": {
                        "sender_batch_id": f"openstall-{share.part_id}",  # PayPal refuses a batch id it has seen
                        "email_subject": "You have been paid for your OpenStall order",
                        "email_message": share.note or DEFAULT_NOTE,
                    },
                    "items": [item],
                },
                idempotency_key=f"openstall-payout-{share.part_id}",
            )
        return Payment(
            capture_id=capture_id,
            payout_batch_id=payout["batch_header"]["payout_batch_id"],
            payout_rail=share.payout_rail,
        )

    def pay_advance(self, advance: Advance) -> AdvancePayment:
        # A payout from the platform's own balance: nothing is captured from the buyer's hold for it.
        share = advance.share
        ahead = replace(
            share, part_id=f"{share.part_id}-advance", amount_usd=advance.amount_usd, paid_ahead_usd=Decimal("0.00")
        )
        item = payout_item(ahead)  # refuses a maker no rail reaches
        if share.payout_rail == "venmo" and self.simulate_venmo:
            return AdvancePayment(None, "venmo", payout_simulated=True)
        with paypal_errors():
            payout = self.client.post(
                "/v1/payments/payouts",
                {
                    "sender_batch_header": {
                        "sender_batch_id": f"openstall-advance-{share.part_id}",
                        "email_subject": "An advance for your OpenStall order",
                        "email_message": ahead.note or DEFAULT_NOTE,
                    },
                    "items": [item],
                },
                idempotency_key=f"openstall-advance-{share.part_id}",
            )
        return AdvancePayment(payout["batch_header"]["payout_batch_id"], share.payout_rail)

    def release_share(self, share: Share) -> None:
        # Her amount is never captured. Only the last open share closes the hold, giving back whatever is left.
        if share.last:
            self.void(share)

    @staticmethod
    def receiver(share: Share) -> dict[str, str]:
        """Who a PayPal-rail payout goes to (rails.receiver)."""
        return receiver(share)
