"""Orders over HTTP, for the approval page: the order, its total check, and checkout at PayPal."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from openstall_allocator import usd
from openstall_api.adapters import AdapterRegistry, AdapterUnavailable, get_registry
from openstall_api.catalog import photo_path
from openstall_api.claims import ClaimHeld
from openstall_api.collective import link_issued
from openstall_api.db import get_session
from openstall_api.delivery import confirm_delivery, delivered_utc, on_time, tell_maker_delivered
from openstall_api.healing import drop_out
from openstall_api.models import DataSource, Order, OrderPart, OrderStatus, PartStatus, Passport
from openstall_api.notices import NoticeState, notice_states, notify_order, ship_by
from openstall_api.orders import server_total
from openstall_api.payments import PAID, OrderNotFound, WrongStatus, reserve_order, seller_rail, start_checkout
from openstall_api.settings import Settings, get_settings
from openstall_api.tracking import track_order
from openstall_api.webhooks import PayPalConfirmation, confirmations, deliver_fake_webhooks
from openstall_paypal import RAIL_NAMES, PaymentError, PaymentUnavailable, PayoutRail, venmo_payouts_simulated
from openstall_trust import trust_score

router = APIRouter(prefix="/api", tags=["orders"])

SessionDep = Annotated[Session, Depends(get_session)]
RegistryDep = Annotated[AdapterRegistry, Depends(get_registry)]


class SellerBrief(BaseModel):
    id: str
    name: str
    city: str | None
    country: str | None


class NoticeOut(BaseModel):
    """Whether the maker was told about her share once PayPal held the order (notices.py)."""

    # sent; sending (on its way to WhatsApp); failed (WhatsApp refused it: tried again when the order is reserved again)
    state: Literal["sent", "sending", "failed"]
    channel: Literal["whatsapp", "web"] | None  # where she was told: WhatsApp, or the web chat on /seller-chat
    language: str | None  # the language she was told in, ISO 639-1
    at: datetime
    reason: str | None = None  # why it failed, in words

    @classmethod
    def of(cls, notice: NoticeState) -> "NoticeOut":
        return cls(
            state=notice.state, channel=notice.channel, language=notice.language, at=_utc(notice.at), reason=notice.reason
        )


class ProofOut(BaseModel):
    """Her proof of shipping (proof.py): the courier receipt photo she sent and what was read from it or typed."""

    state: Literal["awaiting_confirmation", "awaiting_number", "confirmed"]
    photo_url: str | None  # her receipt photo, a path on the API
    carrier: str | None
    tracking_number: str | None  # as read or typed; the share's own tracking once confirmed
    source: Literal["photo", "typed"] | None
    read_by: str | None  # who read the photo, in words for people

    @classmethod
    def of(cls, proof: dict[str, Any] | None) -> "ProofOut | None":
        if not proof or proof.get("state") not in ("awaiting_confirmation", "awaiting_number", "confirmed"):
            return None
        return cls(
            state=proof["state"],
            photo_url=proof.get("photo_url"),
            carrier=proof.get("carrier"),
            tracking_number=proof.get("tracking_number"),
            source=proof.get("source") if proof.get("source") in ("photo", "typed") else None,
            read_by=proof.get("read_by"),
        )


class DropOut(BaseModel):
    """She said she cannot make her share (healing.py): asked to confirm, kept after all, or dropped; and the
    top-up order that took her units, once there is one."""

    state: Literal["asked", "kept", "dropped"]
    asked_at: datetime | None
    dropped_at: datetime | None
    top_up_order_id: str | None
    replan_failed: str | None = None  # why her units could not be re-planned

    @classmethod
    def of(cls, drop: dict[str, Any] | None) -> "DropOut | None":
        shown = drop_out(drop)
        return cls.model_validate(shown) if shown else None


class AdvanceOut(BaseModel):
    """A materials advance on her share (advance.py): offered, accepted, or paid by OpenStall ahead of her proof."""

    state: Literal["asked", "accepted", "paid"]
    amount_usd: Decimal
    paid_at: datetime | None = None

    @classmethod
    def of(cls, advance: dict[str, Any] | None) -> "AdvanceOut | None":
        if not advance or advance.get("state") not in ("asked", "accepted", "paid"):
            return None
        return cls(
            state=advance["state"], amount_usd=Decimal(str(advance["amount_usd"])), paid_at=advance.get("paid_at")
        )


class PartOut(BaseModel):
    id: str
    reference_id: str
    seller: SellerBrief
    product_title: str | None
    photo: str | None
    quantity: int
    unit_price_usd: Decimal
    amount_usd: Decimal
    delivery_date: date | None  # when her share must reach the buyer
    ship_by: date | None  # when it must leave her: the delivery date less her listing's ship days
    status: PartStatus
    notice: NoticeOut | None  # whether she was told about her share; None until the order is reserved
    carrier: str | None  # her courier, once she confirmed her tracking
    tracking_number: str | None  # set only once she confirmed it: she is paid on it
    proof: ProofOut | None  # her receipt photo and what was read, from the moment she sends it
    drop: DropOut | None = None  # she said she cannot make it (healing.py); None while she has not
    advance: AdvanceOut | None = None  # a materials advance on her share (advance.py)
    tracking_on_paypal: bool  # her tracking is on her capture at PayPal (simulated PayPal in fake mode)
    # When the buyer confirmed her parcel arrived (prompt 34), and whether by its delivery date. None before.
    delivered_at: datetime | None = None
    on_time: bool | None = None
    confirmed_by_paypal: bool  # a verified PayPal webhook confirmed this share's status
    attention: str | None  # PayPal reported a problem with it, such as a denied payment
    # Who confirms it: the real PayPal sandbox's verified webhooks, or fake mode's simulated PayPal. The page must
    # never say "Confirmed by PayPal" for a simulated confirmation (spec 3.5).
    confirmation_source: Literal["paypal_sandbox", "simulated"]
    # Released while the order's one hold still serves other shares: never captured, so PayPal has nothing to say.
    nothing_to_confirm: bool
    payout_rail: PayoutRail  # how she is paid once her share is captured (spec 3.5a)
    payout_label: str  # the rail in words, for example "Paid to Venmo (simulated)"
    payout_via_paypal: bool  # her payout goes through (simulated) PayPal Payouts, so its webhook will confirm it
    payout_confirmed: bool  # PayPal said her payout succeeded (PAYMENT.PAYOUTS-ITEM.SUCCEEDED)
    trust_score: Decimal | None
    trust_data_source: DataSource | None


class RequestOut(BaseModel):
    """What the buyer agent asked for."""

    summary: str
    quantity: int
    max_unit_price: Decimal
    deadline: date
    ship_to: str
    # The plan in words, from the request's plan (prompt 26): shown at the top of /approve/{id}. None without a plan.
    explanation: str | None = None
    explanation_by: str | None = None


class ApprovalLinkOut(BaseModel):
    """The approval link a buyer agent was given (MCP checkout), and when it first was."""

    url: str
    issued_at: datetime


class ReplacesOut(BaseModel):
    """The dropped share a top-up order replaces: the order she left, and her units."""

    order_id: str
    part_id: str
    seller_name: str
    quantity: int


class TopUpOut(BaseModel):
    """A top-up order that repairs this order (healing.py): other makers' units for a share that was dropped.
    The buyer approves it on its own approval page, like any order."""

    id: str
    status: OrderStatus
    total_usd: Decimal
    units: int
    created_at: datetime
    approved_at: datetime | None
    replaces: ReplacesOut | None
    parts: list[PartOut]


class OrderOut(BaseModel):
    id: str
    status: OrderStatus
    total_usd: Decimal
    # Where the total went, worked out here: paid to makers on proof, and released back to the buyer.
    paid_usd: Decimal = Decimal("0.00")
    released_usd: Decimal = Decimal("0.00")
    units: int
    created_at: datetime
    approved_at: datetime | None
    paypal_order_id: str | None
    parent_order_id: str | None
    request: RequestOut | None
    parts: list[PartOut]
    # Drafted by a buyer agent through MCP (create_collective_order): /approve says so (prompt 28).
    requested_by_agent: bool = False
    # The approval link a buyer agent was given to send its human, once it was (MCP checkout).
    approval_link: ApprovalLinkOut | None = None
    # Top-up orders that repair this one, oldest first (healing.py); on a top-up, the dropped share it replaces.
    top_ups: list[TopUpOut] = []
    replaces: ReplacesOut | None = None


SANDBOX_VENMO = "simulated: Venmo payouts don't run in PayPal's sandbox"


def payout_words(part: OrderPart, settings: Settings) -> tuple[PayoutRail, str, bool]:
    """Her rail, its label, and whether her payout goes through (simulated) PayPal Payouts."""
    rail = seller_rail(part.seller, settings)
    if part.status == PartStatus.RELEASED:
        return rail.kind, "No payout: her share was released", False
    if not rail.available:
        return rail.kind, rail.reason or "Payout rail not connected yet", False
    name = RAIL_NAMES[rail.kind]
    # "Paid to" only once her share is captured; until then the chip says where the money will go.
    paid = part.status in (PartStatus.CAPTURED, PartStatus.DELIVERED)
    words = f"Paid to {name}" if paid else f"Paid to {name} when she ships"
    if settings.OPENSTALL_MODE == "fake":
        return rail.kind, f"{words} (simulated)", True
    if rail.kind == "venmo" and venmo_payouts_simulated(settings.PAYPAL_API_BASE):
        return rail.kind, f"{words} ({SANDBOX_VENMO})", False
    return rail.kind, words, True


def _part(
    session: Session, part: OrderPart, paypal: PayPalConfirmation, notice: NoticeState | None, settings: Settings
) -> PartOut:
    passport = session.get(Passport, part.seller_id)
    payout_rail, payout_label, payout_via_paypal = payout_words(part, settings)
    metrics = passport.metrics_json if passport else None
    product = part.product
    return PartOut(
        id=part.id,
        reference_id=part.reference_id,
        seller=SellerBrief(
            id=part.seller.id, name=part.seller.name, city=part.seller.city, country=part.seller.country
        ),
        product_title=product.title if product else None,
        photo=photo_path(product.photos_json[0]) if product and product.photos_json else None,
        quantity=part.quantity,
        unit_price_usd=part.unit_price_usd,
        amount_usd=part.amount_usd,
        delivery_date=part.delivery_date,
        ship_by=ship_by(part),
        status=part.status,
        notice=NoticeOut.of(notice) if notice else None,
        carrier=part.carrier,
        tracking_number=part.tracking_number,
        proof=ProofOut.of(part.proof_json),
        drop=DropOut.of(part.drop_json),
        advance=AdvanceOut.of(part.advance_json),
        tracking_on_paypal=part.paypal_tracker_id is not None,
        delivered_at=delivered_utc(part),
        on_time=on_time(part),
        confirmed_by_paypal=paypal.confirmed,
        attention=paypal.attention,
        confirmation_source="simulated" if settings.OPENSTALL_MODE == "fake" else "paypal_sandbox",
        nothing_to_confirm=paypal.nothing_to_confirm,
        payout_rail=payout_rail,
        payout_label=payout_label,
        payout_via_paypal=payout_via_paypal,
        payout_confirmed=paypal.payout_confirmed,
        trust_score=(
            trust_score(metrics["on_time_rate"], metrics["dispute_rate"], metrics["photo_originality"])
            if metrics
            else None
        ),
        trust_data_source=passport.data_source if passport else None,
    )


def order_out(session: Session, order: Order) -> OrderOut:
    settings = get_settings()
    paypal = confirmations(session, order.parts)
    notices = notice_states(session, order.parts)
    issued = link_issued(session, order.id)
    request = order.request
    items = request.items_json if request else []
    summary = next((item.get("query") for item in items if isinstance(item, dict) and item.get("query")), None)
    return OrderOut(
        id=order.id,
        status=order.status,
        total_usd=server_total(order),
        paid_usd=sum((part.amount_usd for part in order.parts if part.status in PAID), Decimal("0.00")),
        released_usd=sum(
            (part.amount_usd for part in order.parts if part.status == PartStatus.RELEASED), Decimal("0.00")
        ),
        units=sum(part.quantity for part in order.parts),
        created_at=order.created_at,
        approved_at=order.approved_at,
        paypal_order_id=order.paypal_order_id,
        parent_order_id=order.parent_order_id,
        request=(
            RequestOut(
                summary=summary or f"{request.quantity} items",
                quantity=request.quantity,
                max_unit_price=request.max_unit_price,
                deadline=request.deadline,
                ship_to=request.ship_to,
                explanation=(request.plan_json or {}).get("explanation"),
                explanation_by=(request.plan_json or {}).get("explanation_by"),
            )
            if request
            else None
        ),
        requested_by_agent=order.source == "mcp",
        approval_link=(
            ApprovalLinkOut(url=str(issued.payload_json.get("url", "")), issued_at=_utc(issued.created_at))
            if issued is not None
            else None
        ),
        parts=[_part(session, part, paypal[part.id], notices.get(part.id), settings) for part in order.parts],
        top_ups=_top_ups(session, order, settings),
        replaces=_replaces(session.get(Order, order.parent_order_id) if order.parent_order_id else None, order),
    )


def _top_ups(session: Session, order: Order, settings: Settings) -> list[TopUpOut]:
    """The top-up orders that repair this order, oldest first, each with its makers' shares."""
    rows = session.scalars(
        select(Order)
        .where(Order.parent_order_id == order.id)
        .options(selectinload(Order.parts).selectinload(OrderPart.seller))
        .order_by(Order.created_at, Order.id)
    ).all()
    top_ups = []
    for top_up in rows:
        paypal = confirmations(session, top_up.parts)
        notices = notice_states(session, top_up.parts)
        top_ups.append(
            TopUpOut(
                id=top_up.id,
                status=top_up.status,
                total_usd=server_total(top_up),
                units=sum(part.quantity for part in top_up.parts),
                created_at=top_up.created_at,
                approved_at=top_up.approved_at,
                replaces=_replaces(order, top_up),
                parts=[
                    _part(session, part, paypal[part.id], notices.get(part.id), settings) for part in top_up.parts
                ],
            )
        )
    return top_ups


def _replaces(parent: Order | None, top_up: Order) -> ReplacesOut | None:
    """The dropped share of `parent` whose re-plan drafted `top_up`: the share that asked for its quote."""
    if parent is None or top_up.request_id is None:
        return None
    for part in parent.parts:
        if (part.drop_json or {}).get("request_id") == top_up.request_id:
            return ReplacesOut(
                order_id=parent.id, part_id=part.id, seller_name=part.seller.name, quantity=part.quantity
            )
    return None


def _load(session: Session, order_id: str) -> Order:
    order = session.get(
        Order,
        order_id,
        options=[selectinload(Order.parts).selectinload(OrderPart.seller), selectinload(Order.request)],
    )
    if order is None:
        raise HTTPException(status_code=404, detail=f"There is no order called {order_id!r}.")
    return order


@router.get("/orders")
def recent_orders(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    top_ups: bool = True,
    stall: bool = True,
) -> list[OrderOut]:
    """The most recent orders, newest first. A new draft arrives on the event stream as order.drafted. With
    top_ups=false, top-up orders are left out: /demo follows the order a top-up repairs, which lists its top-ups
    (healing.py). With stall=false, a person's purchases on stall pages are left out too: /demo follows the
    collective orders."""
    query = (
        select(Order)
        .options(selectinload(Order.parts).selectinload(OrderPart.seller), selectinload(Order.request))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    if not top_ups:
        query = query.where(Order.parent_order_id.is_(None))
    if not stall:
        query = query.where(or_(Order.source.is_(None), Order.source != "stall"))
    rows = session.scalars(query)
    return [order_out(session, order) for order in rows]


@router.get("/orders/{order_id}")
def get_order(order_id: str, session: SessionDep) -> OrderOut:
    return order_out(session, _load(session, order_id))


class TotalIn(BaseModel):
    total_usd: Decimal


class TotalCheck(BaseModel):
    total_usd: Decimal


@router.post("/orders/{order_id}/verify-total")
def verify_total(order_id: str, body: TotalIn, session: SessionDep) -> TotalCheck:
    """Spec 3.5: never trust a total from an agent or a browser. A different total is refused with 409."""
    order = _load(session, order_id)
    expected = server_total(order)
    try:
        claimed = usd(body.total_usd)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if claimed != expected:
        raise HTTPException(
            status_code=409,
            detail=f"The total is ${expected:,.2f}, not ${claimed:,.2f}. Totals are worked out on the server.",
        )
    return TotalCheck(total_usd=expected)


class CheckoutOut(BaseModel):
    paypal_order_id: str
    approval_url: str


# PayPal refusals the human can do something about, in words they can act on.
REFUSALS = {
    "INSTRUMENT_DECLINED": "PayPal declined the way you chose to pay. Nothing was reserved. Approve the order again "
    "and choose another way to pay.",
    "ORDER_EXPIRED": "Your approval at PayPal expired before the money was reserved. Approve the order again.",
    "ORDER_NOT_APPROVED": "PayPal does not have your approval for this order yet. Go back to the order and approve it.",
}


@contextmanager
def payment_errors() -> Iterator[None]:
    """Payment failures as HTTP errors a person can read. When one is raised, nothing was reserved or paid."""
    try:
        yield
    except OrderNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (WrongStatus, ClaimHeld) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except AdapterUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except PaymentUnavailable:
        raise HTTPException(
            status_code=503, detail="PayPal did not answer, so nothing was reserved or paid. Try again in a moment."
        ) from None
    except PaymentError as error:
        if error.issue in REFUSALS:
            raise HTTPException(status_code=409, detail=REFUSALS[error.issue]) from None
        raise HTTPException(
            status_code=502, detail=f"PayPal refused this ({error.issue}), so nothing was reserved or paid."
        ) from None


@router.post("/orders/{order_id}/checkout")
def checkout(order_id: str, session: SessionDep, registry: RegistryDep) -> CheckoutOut:
    """Spec 3.5: one PayPal order for the whole amount. Approving it at PayPal only reserves the money."""
    with payment_errors():
        result = start_checkout(session, order_id, registry.payment_gateway, registry.settings.WEB_BASE_URL)
    session.commit()
    return CheckoutOut(paypal_order_id=result.paypal_order_id, approval_url=result.approval_url)


@router.post("/orders/{order_id}/reserve")
def reserve(order_id: str, session: SessionDep, registry: RegistryDep, background: BackgroundTasks) -> OrderOut:
    """The human is back from PayPal: reserve the whole order, once. Safe to call again; it changes nothing then.

    Once it is reserved, each maker is told about her share (notices.py), after the answer is sent, so WhatsApp never
    slows the receipt. Calling it again tells any maker who could not be reached before, and nobody twice."""
    with payment_errors():
        reserve_order(session, order_id, registry.payment_gateway)
    session.commit()
    background.add_task(notify_order, order_id, lambda: registry.messenger)
    # Tracking PayPal did not take yet, for a share already paid, is tried again (prompt 33).
    background.add_task(track_order, order_id, lambda: registry.payment_gateway)
    background.add_task(deliver_fake_webhooks)  # fake mode: PayPal's confirmations follow, as they would for real
    return order_out(session, _load(session, order_id))


@router.post("/orders/{order_id}/parts/{part_id}/delivered")
def delivered(
    order_id: str, part_id: str, session: SessionDep, registry: RegistryDep, background: BackgroundTasks
) -> OrderOut:
    """The buyer received one maker's parcel (prompt 34): her share is delivered, the order is completed if it was the
    last, and she is told in her language, after the answer is sent. No money moves: she was paid when she shipped.
    Safe to call again; it changes nothing then."""
    part = session.get(OrderPart, part_id)
    if part is None or part.order_id != order_id:
        raise HTTPException(status_code=404, detail=f"Order {order_id!r} has no share called {part_id!r}.")
    with payment_errors():
        newly = confirm_delivery(session, part_id)
    session.commit()
    if newly:
        background.add_task(tell_maker_delivered, part_id, lambda: registry.messenger)
    session.expire_all()
    return order_out(session, _load(session, order_id))


def _utc(moment: datetime) -> datetime:
    """SQLite drops the zone; we always store UTC, so say so for the browser."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
