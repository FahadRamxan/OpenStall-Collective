"""Payments for orders (spec 3.5, pay-on-proof): send the human to PayPal to approve the whole order, reserve it when
they come back, then pay or release each seller's share. Every PayPal call goes through the payment gateway.

Each PayPal write that a caller can ask for twice (the checkout, the reserve, a share's capture and its void) is
claimed in our database first (claims.py), so two requests at once cannot both reach PayPal. On Postgres the second
waits on the order's row lock and then finds the stored result; on SQLite it is refused with ClaimHeld. A repeat
after the first finished returns the stored result, or, if PayPal did not answer the first, goes ahead with the
same PayPal-Request-Id, as before.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session, object_session, selectinload

from openstall_api.claims import paypal_claim
from openstall_api.events import EventType, record_event
from openstall_api.models import Order, OrderPart, OrderStatus, PartStatus, Seller
from openstall_api.orders import move_order, move_part
from openstall_api.settings import Settings, get_settings
from openstall_paypal import (
    WAITING_FOR_BUYER,
    Checkout,
    CheckoutPart,
    CheckoutRequest,
    PaymentError,
    PaymentGateway,
    PaymentUnavailable,
    Rail,
    Reservation,
    Share,
    Tracking,
    carrier_code,
    rail_for,
    sandbox_host,
    tracker_for,
)

# Only these orders can be sent to PayPal: a repeated press of Approve finds the order waiting for approval.
CHECKOUT_FROM = frozenset({OrderStatus.DRAFT, OrderStatus.AWAITING_APPROVAL})

STATUS_WORDS = {
    OrderStatus.DRAFT: "a draft",
    OrderStatus.AWAITING_APPROVAL: "waiting for approval",
    OrderStatus.AUTHORIZED: "reserved at PayPal",
    OrderStatus.PARTLY_SHIPPED: "partly shipped",
    OrderStatus.SHIPPED: "shipped",
    OrderStatus.COMPLETED: "completed",
    OrderStatus.CANCELLED: "cancelled",
}


# Orders whose money PayPal already holds, or has paid out: reserving them again changes nothing.
RESERVED = frozenset({OrderStatus.AUTHORIZED, OrderStatus.PARTLY_SHIPPED, OrderStatus.SHIPPED, OrderStatus.COMPLETED})
PAID = frozenset({PartStatus.CAPTURED, PartStatus.DELIVERED})


class OrderNotFound(LookupError):
    pass


class WrongStatus(ValueError):
    """The order's status does not allow this step, such as sending a reserved order to PayPal again."""


class NotApproved(WrongStatus):
    """The human has not approved the order at PayPal (yet), so there is nothing to reserve."""


def load_order(session: Session, order_id: str) -> Order:
    # Locked on Postgres, so two requests cannot reserve or settle the same order at once, and read again once
    # locked (populate_existing), so nothing loaded before the lock is trusted.
    order = session.get(
        Order,
        order_id,
        options=[selectinload(Order.parts).selectinload(OrderPart.seller)],
        with_for_update=True,
        populate_existing=True,
    )
    if order is None:
        raise OrderNotFound(f"There is no order called {order_id!r}.")
    return order


def share_description(part: OrderPart) -> str:
    """How a share reads at PayPal, for example "12 × Hand-embroidered cushion cover, Amina"."""
    title = part.product.title if part.product else "items"
    return f"{part.quantity} × {title}, {part.seller.name}"


def checkout_request(order: Order, web_base_url: str) -> CheckoutRequest:
    """The whole order for PayPal: one share per seller, amounts from our own rows, never from a caller."""
    return CheckoutRequest(
        order_id=order.id,
        parts=tuple(
            CheckoutPart(
                reference_id=part.reference_id,
                amount_usd=part.amount_usd,
                description=share_description(part),
                payee_merchant_id=part.seller.paypal_merchant_id,
                payee_email=part.seller.paypal_email,
            )
            for part in order.parts
        ),
        return_url=f"{web_base_url}/approve/{order.id}/return",
        cancel_url=f"{web_base_url}/approve/{order.id}?cancelled=1",
    )


def start_checkout(session: Session, order_id: str, gateway: PaymentGateway, web_base_url: str) -> Checkout:
    """Create the PayPal order for the whole amount and say where the human approves it. The caller commits.

    Pressing Approve again returns the same PayPal order (the gateway's idempotency key is our order id). If the
    human already approved it and only the reservation is missing, they go straight to the return page instead.
    """
    order = load_order(session, order_id)
    if order.status not in CHECKOUT_FROM:
        raise WrongStatus(f"Order {order.id} is {STATUS_WORDS[order.status]}, so it cannot go to PayPal again.")
    request = checkout_request(order, web_base_url)
    with paypal_claim(
        session,
        f"checkout:{order.id}",
        f"openstall-checkout-{order.id}",
        busy=f"Order {order.id} is being sent to PayPal by another request. Try again in a moment.",
    ) as claim:
        checkout = gateway.create_checkout(request)
        claim.result = checkout.paypal_order_id
    repeated = order.paypal_order_id == checkout.paypal_order_id
    if order.status == OrderStatus.DRAFT:
        move_order(order, OrderStatus.AWAITING_APPROVAL)
    elif repeated and gateway.get_order(checkout.paypal_order_id).status == "APPROVED":
        return Checkout(checkout.paypal_order_id, request.return_url)
    order.paypal_order_id = checkout.paypal_order_id
    if not repeated:
        makers = len(order.parts)
        record_event(
            session,
            EventType.ORDER_CHECKOUT_STARTED,
            f"Order {order.id} went to PayPal: ${request.total_usd:,.2f} to reserve for {makers} "
            f"{'maker' if makers == 1 else 'makers'}",
            entity_id=order.id,
            payload={"paypal_order_id": checkout.paypal_order_id, "total_usd": request.total_usd},
        )
    return checkout


def reserve_order(session: Session, order_id: str, gateway: PaymentGateway) -> Order:
    """Reserve an approved order at PayPal, exactly once. The caller commits.

    PayPal's own state decides: the order is read first and reserved only if it is APPROVED. If PayPal does not
    answer the reserve call, the order is read again to learn whether it went through; it is never sent twice blindly.
    """
    order = load_order(session, order_id)
    if order.status in RESERVED:
        return order
    if order.status != OrderStatus.AWAITING_APPROVAL or not order.paypal_order_id:
        raise WrongStatus(f"Order {order.id} is {STATUS_WORDS[order.status]}, so there is nothing to reserve.")
    paypal_order_id = order.paypal_order_id
    state = gateway.get_order(paypal_order_id)
    if state.holds:  # reserved before, but our side was not saved
        reservation = Reservation(paypal_order_id, state.holds)
    elif state.status in WAITING_FOR_BUYER:
        raise NotApproved("PayPal does not have your approval for this order yet. Go back to the order and approve it.")
    elif state.status != "APPROVED":
        raise NotApproved(
            f"PayPal says this approval is no longer valid ({state.status.lower()}). Go back to the order and approve "
            "it again."
        )
    else:
        with paypal_claim(
            session,
            f"reserve:{order.id}",
            f"openstall-reserve-{paypal_order_id}",
            busy=f"Order {order.id} is being reserved at PayPal by another request. Try again in a moment.",
        ) as claim:
            try:
                reservation = gateway.reserve(paypal_order_id)
            except PaymentUnavailable as no_answer:
                try:
                    state = gateway.get_order(paypal_order_id)
                except PaymentError:
                    raise no_answer  # the reserve's own outcome decides its claim, not this read's
                if not state.holds:
                    raise
                reservation = Reservation(paypal_order_id, state.holds)
            claim.result = paypal_order_id
    for part in order.parts:
        hold = reservation.hold_for(part.reference_id)
        if hold is None:
            raise WrongStatus(f"PayPal sent no authorization for share {part.reference_id} of order {order.id}.")
        part.authorization_id = hold
        move_part(part, PartStatus.AUTHORIZED)
        record_event(
            session,
            EventType.PART_RESERVED,
            f"{part.seller.name}'s share is reserved: ${part.amount_usd:,.2f}, paid when she ships",
            entity_id=part.id,
            payload={"order_id": order.id, "seller_id": part.seller_id, "amount_usd": part.amount_usd},
        )
    move_order(order, OrderStatus.AUTHORIZED)
    order.approved_at = datetime.now(UTC)
    record_event(
        session,
        EventType.ORDER_AUTHORIZED,
        f"PayPal reserved ${order.total_usd:,.2f} for order {order.id}. Nothing is taken until each maker ships",
        entity_id=order.id,
        payload={"paypal_order_id": paypal_order_id, "total_usd": order.total_usd},
    )
    return order


def load_part(session: Session, part_id: str) -> OrderPart:
    part = session.get(OrderPart, part_id)
    if part is None:
        raise OrderNotFound(f"There is no order share called {part_id!r}.")
    load_order(session, part.order_id)  # lock the order: whether this is its last open share depends on the others
    return part


def seller_rail(seller: Seller, settings: Settings | None = None) -> Rail:
    """The rail she is paid on (spec 3.5a). In sandbox mode the PayPal rail needs her (sandbox) PayPal account;
    fake mode simulates every payout, so it needs none. Hyperwallet, which is simulated, never runs on PayPal's
    live host."""
    settings = settings or get_settings()
    return rail_for(
        seller.country,
        seller.venmo_handle,
        seller.paypal_email,
        seller.paypal_merchant_id,
        override=seller.payout_rail.value if seller.payout_rail else None,
        payee_required=settings.OPENSTALL_MODE == "sandbox",
        live_money=settings.OPENSTALL_MODE == "sandbox" and not sandbox_host(settings.PAYPAL_API_BASE),
    )


def paid_ahead(part: OrderPart) -> Decimal:
    """What OpenStall paid her ahead on this share as a materials advance (advance.py): taken off her payout when
    she ships."""
    advance = part.advance_json or {}
    return Decimal(str(advance["amount_usd"])) if advance.get("state") == "paid" else Decimal("0.00")


def share_of(part: OrderPart) -> Share:
    """A reserved share as the gateway needs it. `last`: no other share of the order is still reserved."""
    assert part.authorization_id is not None
    others_open = any(other.status == PartStatus.AUTHORIZED for other in part.order.parts if other.id != part.id)
    return Share(
        part_id=part.id,
        hold_id=part.authorization_id,
        amount_usd=part.amount_usd,
        payee_merchant_id=part.seller.paypal_merchant_id,
        payee_email=part.seller.paypal_email,
        note=f"Your share of OpenStall order {part.order_id}: {share_description(part)}",
        last=not others_open,
        payout_rail=seller_rail(part.seller).kind,
        venmo_handle=part.seller.venmo_handle,
        paid_ahead_usd=paid_ahead(part),
    )


def pay_share(session: Session, part_id: str, gateway: PaymentGateway) -> OrderPart:
    """Pay one maker her share on proof of shipping: only once her tracking is confirmed, and only once.
    The caller commits."""
    part = load_part(session, part_id)
    name = part.seller.name
    if part.status in PAID:
        return part
    if part.status != PartStatus.AUTHORIZED:
        raise WrongStatus(f"{name}'s share is {part.status.value}, so it cannot be paid.")
    if not part.tracking_number:
        raise WrongStatus(f"{name}'s share is paid when her tracking is confirmed, and there is none yet.")
    rail = seller_rail(part.seller)
    if not rail.available:  # never captured without a way to pay her: she would be left half paid
        raise WrongStatus(f"{name}'s share stays reserved and is not captured. {rail.reason}.")
    share = share_of(part)
    with paypal_claim(
        session,
        f"capture:{part.id}",
        f"openstall-capture-{part.id}",
        busy=f"{name}'s share is being paid by another request. Try again in a moment.",
    ) as claim:
        payment = gateway.pay_share(share)
        claim.result = payment.capture_id
    part.capture_id = payment.capture_id
    move_part(part, PartStatus.CAPTURED)
    record_event(
        session,
        EventType.PART_CAPTURED,
        f"{name} was paid ${part.amount_usd:,.2f} on proof of shipping"
        + (
            f" (${share.paid_ahead_usd:,.2f} of it ahead, as OpenStall's advance; "
            f"${part.amount_usd - share.paid_ahead_usd:,.2f} sent now)"
            if share.paid_ahead_usd
            else ""
        )
        + (", to her bank through Hyperwallet (simulated)" if share.payout_rail == "hyperwallet" else ""),
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "capture_id": payment.capture_id,
            "payout_batch_id": payment.payout_batch_id,
            "payout_rail": payment.payout_rail or share.payout_rail,
            "payout_simulated": payment.payout_simulated,
            "amount_usd": part.amount_usd,
        },
    )
    settle_order(part.order)
    return part


def release_share(session: Session, part_id: str, gateway: PaymentGateway) -> OrderPart:
    """Give one maker's share back to the buyer when she cannot deliver; never once she is paid. The caller commits."""
    part = load_part(session, part_id)
    name = part.seller.name
    if part.status == PartStatus.RELEASED:
        return part
    if part.status in PAID:
        raise WrongStatus(f"{name}'s share was already paid, so it cannot be released.")
    voided_hold = False
    if part.status == PartStatus.AUTHORIZED:
        # Her release closes the hold when no other share still uses it: the gateway voids it then (each share's own
        # hold on the multiparty path, the last open share on the payouts path), and PayPal's VOIDED event follows.
        voided_hold = not any(
            other.authorization_id == part.authorization_id and other.status == PartStatus.AUTHORIZED
            for other in part.order.parts
            if other.id != part.id
        )
        with paypal_claim(
            session,
            f"release:{part.id}",
            f"openstall-release-{part.id}",
            busy=f"{name}'s share is being released by another request. Try again in a moment.",
        ) as claim:
            share = share_of(part)
            gateway.release_share(share)
            claim.result = share.hold_id
    move_part(part, PartStatus.RELEASED)
    record_event(
        session,
        EventType.PART_RELEASED,
        f"{name}'s share of ${part.amount_usd:,.2f} was released back to the buyer",
        entity_id=part.id,
        payload={"order_id": part.order_id, "amount_usd": part.amount_usd, "voided_hold": voided_hold},
    )
    settle_order(part.order)
    return part


def track_share(session: Session, part_id: str, gateway: PaymentGateway) -> OrderPart:
    """Put a paid share's tracking on her capture at PayPal, once (prompt 33). The caller commits.

    PayPal takes no PayPal-Request-Id on this route, so it never dedupes a repeat: the order's trackers are read
    first, and a tracker already there for her tracking number is recorded instead of being sent again. The call is
    claimed like every other PayPal write, so two requests never send it at once.
    """
    part = load_part(session, part_id)  # locks the order: two requests cannot both send it
    name = part.seller.name
    if part.paypal_tracker_id:
        return part
    if part.status not in PAID or not part.capture_id:
        raise WrongStatus(f"{name}'s share is not captured yet, so PayPal has no payment to put her tracking on.")
    if not part.tracking_number:
        raise WrongStatus(f"{name}'s share has no confirmed tracking to put on the PayPal order.")
    paypal_order_id = part.order.paypal_order_id
    if not paypal_order_id:
        raise WrongStatus(f"Order {part.order_id} has no PayPal order to put {name}'s tracking on.")
    carrier, carrier_other = carrier_code(part.carrier)
    known = gateway.get_order(paypal_order_id).trackers  # read first: this write is not deduped at PayPal
    tracker = tracker_for(known, part.tracking_number)
    if tracker is None:
        with paypal_claim(
            session,
            f"track:{part.id}",
            f"openstall-track-{part.id}",
            busy=f"{name}'s tracking is being added to PayPal by another request. Try again in a moment.",
        ) as claim:
            tracker = gateway.add_tracking(
                Tracking(
                    part_id=part.id,
                    paypal_order_id=paypal_order_id,
                    capture_id=part.capture_id,
                    tracking_number=part.tracking_number,
                    carrier=carrier,
                    carrier_name_other=carrier_other,
                    known_trackers=known,
                )
            )
            claim.result = tracker[:64]
    part.paypal_tracker_id = tracker[:128]
    simulated = get_settings().OPENSTALL_MODE == "fake"
    courier = carrier_other or part.carrier or carrier
    record_event(
        session,
        EventType.TRACKING_ADDED,
        f"{name}'s tracking ({courier} {part.tracking_number}) is on {'simulated ' if simulated else ''}PayPal order "
        f"{paypal_order_id}, on her payment",
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "paypal_order_id": paypal_order_id,
            "capture_id": part.capture_id,
            "tracker_id": part.paypal_tracker_id,
            "carrier": carrier,
            "carrier_name_other": carrier_other,
            "tracking_number": part.tracking_number,
        },
    )
    return part


def settle_order(order: Order) -> None:
    """The order's status from its shares: partly shipped while some are paid and some still wait, shipped once
    none waits, and cancelled if every share was released. A shipped order is completed once every paid share is
    delivered (prompt 34, delivery.py), whichever share settled last: delivered, or released."""
    statuses = [part.status for part in order.parts]
    if order.status in (OrderStatus.AUTHORIZED, OrderStatus.PARTLY_SHIPPED):
        paid = any(status in PAID for status in statuses)
        waiting = any(status == PartStatus.AUTHORIZED for status in statuses)
        if waiting:
            target = OrderStatus.PARTLY_SHIPPED if paid else order.status
        else:
            target = OrderStatus.SHIPPED if paid else OrderStatus.CANCELLED
        if target != order.status:
            move_order(order, target)
    if order.status == OrderStatus.SHIPPED and PartStatus.CAPTURED not in statuses:
        complete_order(order)


def complete_order(order: Order) -> None:
    """The end of an order: every maker who shipped is paid and her parcel arrived, and nothing is left reserved at
    PayPal. Recorded in the order's own transaction."""
    move_order(order, OrderStatus.COMPLETED)
    delivered = [part for part in order.parts if part.status == PartStatus.DELIVERED]
    released = len(order.parts) - len(delivered)
    units = sum(part.quantity for part in delivered)
    paid = sum((part.amount_usd for part in delivered), Decimal("0.00"))
    makers = "1 maker" if len(delivered) == 1 else f"{len(delivered)} makers"
    session = object_session(order)
    assert session is not None, "an order is completed in its own session"
    record_event(
        session,
        EventType.ORDER_COMPLETED,
        f"Order {order.id} is complete: {makers} delivered {units} units and were paid ${paid:,.2f}"
        + (f"; {released} share{'s were' if released > 1 else ' was'} released" if released else ""),
        entity_id=order.id,
        payload={"delivered": len(delivered), "released": released, "units": units, "paid_usd": paid},
    )
