"""Orders over HTTP, for the approval page: the order, its total check, and checkout at PayPal."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openstall_allocator import usd
from openstall_api.adapters import AdapterRegistry, AdapterUnavailable, get_registry
from openstall_api.catalog import photo_path
from openstall_api.claims import ClaimHeld
from openstall_api.collective import link_issued
from openstall_api.db import get_session
from openstall_api.models import DataSource, Order, OrderPart, OrderStatus, PartStatus, Passport
from openstall_api.orders import server_total
from openstall_api.payments import OrderNotFound, WrongStatus, reserve_order, seller_rail, start_checkout
from openstall_api.settings import Settings, get_settings
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


class PartOut(BaseModel):
    id: str
    reference_id: str
    seller: SellerBrief
    product_title: str | None
    photo: str | None
    quantity: int
    unit_price_usd: Decimal
    amount_usd: Decimal
    delivery_date: date | None
    status: PartStatus
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


class OrderOut(BaseModel):
    id: str
    status: OrderStatus
    total_usd: Decimal
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


def _part(session: Session, part: OrderPart, paypal: PayPalConfirmation, settings: Settings) -> PartOut:
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
        status=part.status,
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
    issued = link_issued(session, order.id)
    request = order.request
    items = request.items_json if request else []
    summary = next((item.get("query") for item in items if isinstance(item, dict) and item.get("query")), None)
    return OrderOut(
        id=order.id,
        status=order.status,
        total_usd=server_total(order),
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
        parts=[_part(session, part, paypal[part.id], settings) for part in order.parts],
    )


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
def recent_orders(session: SessionDep, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> list[OrderOut]:
    """The most recent orders, newest first. A new draft arrives on the event stream as order.drafted."""
    rows = session.scalars(
        select(Order)
        .options(selectinload(Order.parts).selectinload(OrderPart.seller), selectinload(Order.request))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
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
    """The human is back from PayPal: reserve the whole order, once. Safe to call again; it changes nothing then."""
    with payment_errors():
        reserve_order(session, order_id, registry.payment_gateway)
    session.commit()
    background.add_task(deliver_fake_webhooks)  # fake mode: PayPal's confirmations follow, as they would for real
    return order_out(session, _load(session, order_id))


def _utc(moment: datetime) -> datetime:
    """SQLite drops the zone; we always store UTC, so say so for the browser."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
