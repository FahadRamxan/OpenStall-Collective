"""The dashboard's API (spec 3.9, prompt 44), and the home page's numbers (prompt 41).

GET /api/dashboard gives /dashboard's AG Grid tables in one answer: the recent orders, each maker's share with her
payout and her parcel's tracking, the trust passports with whether each signature holds, and Demand Radar (radar.py).
POST /api/radar/{key}/tip sends a Radar group's tip to its maker: always in fake mode, and in sandbox mode only with
the demo token, since it messages a real maker. GET /api/overview counts what the home page shows.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from openstall_api.adapters import AdapterRegistry, get_registry
from openstall_api.db import get_session
from openstall_api.delivery import delivered_utc, on_time
from openstall_api.demo_api import demo_controls_allowed
from openstall_api.healing import DROPPED
from openstall_api.models import (
    DataSource,
    Order,
    OrderPart,
    OrderStatus,
    PartStatus,
    Passport,
    Product,
    ProductStatus,
    Search,
    utcnow,
)
from openstall_api.notices import ship_by
from openstall_api.orders import server_total
from openstall_api.orders_api import payout_words
from openstall_api.passports import MissingSigningKey, TrustCard, verify_card
from openstall_api.payments import PAID
from openstall_api.radar import SEEDED, WEEK, RadarGroup, TipError, radar, send_tip
from openstall_api.settings import get_settings

router = APIRouter(prefix="/api", tags=["dashboard"])

SessionDep = Annotated[Session, Depends(get_session)]

RECENT_ORDERS = 50  # the most orders the dashboard lists, newest first


class OrderRow(BaseModel):
    id: str
    status: OrderStatus
    created_at: datetime
    approved_at: datetime | None
    total_usd: Decimal
    paid_usd: Decimal  # captured for makers who proved they shipped
    released_usd: Decimal  # given back to the buyer, never charged
    units: int
    makers: int
    top_up_of: str | None  # the order a top-up repairs (healing.py)
    requested_by_agent: bool
    from_stall: bool  # a person bought it on a stall page (prompt 42)


class ShareRow(BaseModel):
    """One maker's share of an order: her payout, and her parcel's tracking."""

    part_id: str
    order_id: str
    reference_id: str
    seller_id: str
    maker: str
    quantity: int
    amount_usd: Decimal
    status: PartStatus
    payout: str  # her payout rail, in words
    paid: bool
    carrier: str | None
    tracking_number: str | None
    tracking_on_paypal: bool
    ship_by: date | None
    delivered_at: datetime | None
    on_time: bool | None
    dropped_out: bool


class PassportRow(BaseModel):
    seller_id: str
    name: str
    orders_delivered: int
    on_time_rate: float
    dispute_rate: float
    photo_originality: float
    score: float
    live_deliveries: int
    data_source: DataSource
    issued_at: datetime
    signature_valid: bool | None  # whether OpenStall's key signed exactly this card; None without a key to check


class DashboardOut(BaseModel):
    simulated: bool  # test mode: PayPal and the payouts are simulated
    orders: list[OrderRow]
    shares: list[ShareRow]
    passports: list[PassportRow]
    radar: list[RadarGroup]


@router.get("/dashboard")
def dashboard(session: SessionDep) -> DashboardOut:
    """Everything /dashboard shows, worked out now. It only reads."""
    settings = get_settings()
    orders = session.scalars(
        select(Order)
        .options(selectinload(Order.parts).selectinload(OrderPart.seller))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(RECENT_ORDERS)
    ).all()
    shares = []
    for order in orders:
        for part in order.parts:
            _, payout, _ = payout_words(part, settings)
            shares.append(
                ShareRow(
                    part_id=part.id,
                    order_id=order.id,
                    reference_id=part.reference_id,
                    seller_id=part.seller_id,
                    maker=part.seller.name,
                    quantity=part.quantity,
                    amount_usd=part.amount_usd,
                    status=part.status,
                    payout=payout,
                    paid=part.status in PAID,
                    carrier=part.carrier,
                    tracking_number=part.tracking_number,
                    tracking_on_paypal=part.paypal_tracker_id is not None,
                    ship_by=ship_by(part),
                    delivered_at=delivered_utc(part),
                    on_time=on_time(part),
                    dropped_out=(part.drop_json or {}).get("state") == DROPPED,
                )
            )
    return DashboardOut(
        simulated=settings.OPENSTALL_MODE == "fake",
        orders=[_order_row(order) for order in orders],
        shares=shares,
        passports=[
            _passport_row(passport) for passport in session.scalars(select(Passport).order_by(Passport.seller_id))
        ],
        radar=radar(session),
    )


class Overview(BaseModel):
    """The home page's numbers, worked out now."""

    makers: int  # makers with a live listing
    listings: int  # live listings
    orders_approved: int  # orders a person approved at PayPal
    paid_usd: Decimal  # paid to makers on proof of shipping
    makers_paid: int  # makers paid at least once
    deliveries: int  # parcels a buyer confirmed she received
    agent_searches: int  # agents' searches in the last 7 days (Demand Radar's seeded ones left out)
    simulated: bool  # test mode: PayPal is simulated


@router.get("/overview")
def overview(session: SessionDep) -> Overview:
    """What the home page counts: live makers and listings, approved orders, what makers were paid on proof, the
    parcels delivered, and the agents' searches this week. It only reads."""
    live = select(Product).where(Product.status == ProductStatus.LIVE).subquery()
    paid = session.scalars(select(OrderPart).where(OrderPart.status.in_(PAID))).all()  # exact, in Decimal
    seeded = Search.filters_json["data_source"].as_string()
    return Overview(
        makers=session.scalar(select(func.count(func.distinct(live.c.seller_id)))) or 0,
        listings=session.scalar(select(func.count()).select_from(live)) or 0,
        orders_approved=session.scalar(select(func.count()).where(Order.approved_at.is_not(None))) or 0,
        paid_usd=sum((part.amount_usd for part in paid), Decimal("0.00")),
        makers_paid=len({part.seller_id for part in paid}),
        deliveries=session.scalar(
            select(func.count()).select_from(OrderPart).where(OrderPart.status == PartStatus.DELIVERED)
        )
        or 0,
        agent_searches=session.scalar(
            select(func.count())
            .select_from(Search)
            .where(Search.created_at >= utcnow() - WEEK, or_(seeded.is_(None), seeded != SEEDED))
        )
        or 0,
        simulated=get_settings().OPENSTALL_MODE == "fake",
    )


@router.post("/radar/{key}/tip", dependencies=[Depends(demo_controls_allowed)])
def tip(key: str, registry: Annotated[AdapterRegistry, Depends(get_registry)]) -> RadarGroup:
    """Send a Demand Radar group's tip to its maker, in her language, once a week. 409, in words, when it cannot be."""
    try:
        return send_tip(key, lambda: registry.messenger)
    except TipError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


def _order_row(order: Order) -> OrderRow:
    return OrderRow(
        id=order.id,
        status=order.status,
        created_at=_utc(order.created_at),
        approved_at=_utc(order.approved_at) if order.approved_at else None,
        total_usd=server_total(order),
        paid_usd=sum((part.amount_usd for part in order.parts if part.status in PAID), Decimal("0.00")),
        released_usd=sum(
            (part.amount_usd for part in order.parts if part.status == PartStatus.RELEASED), Decimal("0.00")
        ),
        units=sum(part.quantity for part in order.parts),
        makers=len(order.parts),
        top_up_of=order.parent_order_id,
        requested_by_agent=order.source == "mcp",
        from_stall=order.source == "stall",
    )


def _passport_row(passport: Passport) -> PassportRow:
    card = TrustCard.of(passport)
    try:
        valid: bool | None = verify_card(card.model_dump(mode="json"))
    except MissingSigningKey:
        valid = None
    return PassportRow(
        seller_id=passport.seller_id,
        name=passport.seller.name,
        orders_delivered=card.orders_delivered,
        on_time_rate=card.on_time_rate,
        dispute_rate=card.dispute_rate,
        photo_originality=card.photo_originality,
        score=card.score,
        live_deliveries=card.live_deliveries,
        data_source=passport.data_source,
        issued_at=_utc(passport.issued_at),
        signature_valid=valid,
    )


def _utc(moment: datetime) -> datetime:
    """SQLite drops the zone; we always store UTC, so say so for the browser."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
