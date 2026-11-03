"""The /demo page's own API: GET /api/demo/limits, what the offer rules allow each live maker (spec 3.3).

The numbers come from the allocator core through offer_rules.py, the same rules every offer is checked against, so
viewers see each maker's limits before the offers arrive. POST /api/demo/run plays the story with the scripted buyer
agent (buyer.py) and POST /api/demo/reset puts the demo world back as seeded: always in fake mode, and in sandbox mode
only with the DEMO_RUN_TOKEN header.
"""

import hmac
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from mcp import Client
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_allocator import Clock, SystemClock
from openstall_api import quotes
from openstall_api.buyer import BuyerError, run_story
from openstall_api.db import get_session
from openstall_api.events import EventType, record_event
from openstall_api.models import DataSource
from openstall_api.offer_rules import MakerLimits, default_deadline, limits_by_deadline
from openstall_api.seed import DEMO_ORDER_ID, reset_demo_world
from openstall_api.settings import Settings, get_settings
from openstall_api.storefront import storefront

router = APIRouter(prefix="/api/demo", tags=["demo"])

# Where "today" comes from: UTC, like the offer rules and search. Tests fix it with a FixedClock.
clock: Clock = SystemClock()


class MakerLimitsOut(BaseModel):
    """One live listing's maker, and what the offer rules let her agent offer by the deadline."""

    seller_id: str
    seller_name: str
    city: str | None
    product_id: str
    product_title: str
    list_price_usd: Decimal  # sent as a string such as "18.00", so it stays exact
    floor_price_usd: Decimal
    max_discount_pct: Decimal
    lowest_price_usd: Decimal = Field(
        description="The lowest unit price her agent may offer: her floor, or her list price less her maximum "
        "discount, whichever is higher."
    )
    capacity_per_week: int
    ship_days: int
    min_lead_days: int
    committed_units: int = Field(description="Units she has promised to reserved orders and not shipped yet.")
    capacity_by_deadline: int = Field(
        description="Units she can still make and ship by the deadline, after her committed units."
    )
    data_source: DataSource

    @classmethod
    def of(cls, limits: MakerLimits) -> "MakerLimitsOut":
        product, policy = limits.product, limits.policy
        return cls(
            seller_id=product.seller_id,
            seller_name=product.seller.name,
            city=product.seller.city,
            product_id=product.id,
            product_title=product.title,
            list_price_usd=product.price_usd,
            floor_price_usd=policy.floor_price_usd,
            max_discount_pct=policy.max_discount_pct,
            lowest_price_usd=limits.lowest_price,
            capacity_per_week=policy.capacity_per_week,
            ship_days=product.ship_days,
            min_lead_days=policy.min_lead_days,
            committed_units=limits.committed,
            capacity_by_deadline=limits.capacity,
            data_source=product.seller.data_source,
        )


class LimitsOut(BaseModel):
    """Every live maker's limits by one deadline."""

    today: date = Field(description="Today in UTC, the day capacity is counted from.")
    deadline: date
    makers: list[MakerLimitsOut] = Field(description="One row per live listing, oldest listing first.")
    unreadable: list[str] = Field(
        description="Live makers left out because their limits cannot be read, each said in words."
    )


@router.get("/limits")
def get_limits(
    session: Annotated[Session, Depends(get_session)],
    deadline: Annotated[
        date | None, Query(description="The date an order must arrive by, YYYY-MM-DD. 30 days from today if left out.")
    ] = None,
) -> LimitsOut:
    """What the offer rules allow each live maker by the deadline: the lowest price her agent may offer, and how many
    she can still make and ship by then. This only reads."""
    today = clock.today()
    deadline = deadline or default_deadline(today)
    if deadline <= today:
        raise HTTPException(
            status_code=422,
            detail=f"The deadline {deadline.isoformat()} must be after today, {today.isoformat()} (UTC).",
        )
    makers, unreadable = limits_by_deadline(session, today, deadline)
    return LimitsOut(
        today=today,
        deadline=deadline,
        makers=[MakerLimitsOut.of(limits) for limits in makers],
        unreadable=unreadable,
    )


# The header that unlocks the demo controls in sandbox mode, where DEMO_RUN_TOKEN is set.
TOKEN_HEADER = "X-Demo-Run-Token"


def demo_controls_allowed(
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Header(alias=TOKEN_HEADER)] = None,
) -> None:
    """Fake mode: always. Sandbox mode: only with the DEMO_RUN_TOKEN header, so strangers cannot run up model calls
    or wipe the hosted demo. Without a DEMO_RUN_TOKEN set, sandbox mode keeps the controls off."""
    if settings.OPENSTALL_MODE == "fake":
        return
    expected = settings.DEMO_RUN_TOKEN.get_secret_value() if settings.DEMO_RUN_TOKEN else None
    if expected is None:
        raise HTTPException(status_code=403, detail="The demo controls are off: DEMO_RUN_TOKEN is not set.")
    if token is None or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail=f"The demo controls need the {TOKEN_HEADER} header.")


class DemoRun(BaseModel):
    """What the scripted buyer agent did."""

    steps: list[str] = Field(description="Each step, as scripts/run_demo_request.py prints it.")
    request_id: str
    order_id: str
    total_usd: Decimal
    shares: list[tuple[str, int]] = Field(description="(maker, units) in the plan's order, cheapest first.")
    approval_url: str


class DemoReset(BaseModel):
    sellers: int
    products: int
    passports: int
    order_id: str


@router.post("/run", dependencies=[Depends(demo_controls_allowed)])
async def run_demo(session: Annotated[Session, Depends(get_session)]) -> DemoRun:
    """The scripted buyer agent runs the story's request through the real MCP storefront, in process, as
    scripts/run_demo_request.py does over HTTP: search, quote, draft, approval link. /demo follows it live."""
    record_event(session, EventType.DEMO_RUN, "The scripted buyer agent started the story's request")
    session.commit()
    try:
        async with Client(storefront) as client:
            run = await run_story(client, quotes.clock.today(), say=lambda line: None)
    except BuyerError as error:
        raise HTTPException(status_code=409, detail=f"The buyer agent stopped: {error}") from None
    assert run.request_id and run.order_id and run.total_usd and run.approval_url
    return DemoRun(
        steps=run.lines,
        request_id=run.request_id,
        order_id=run.order_id,
        total_usd=Decimal(run.total_usd),
        shares=run.shares,
        approval_url=run.approval_url,
    )


@router.post("/reset", dependencies=[Depends(demo_controls_allowed)])
def reset_demo(session: Annotated[Session, Depends(get_session)]) -> DemoReset:
    """The demo world as seeded: the five makers, their listings and passports, and the story's draft order. Every
    other row goes, except the live feed's events, so pages that are open keep following it."""
    report = reset_demo_world(session, quotes.clock.today())
    record_event(
        session,
        EventType.DEMO_RESET,
        "The demo was reset: the seeded makers and the story's draft order are back, and nothing else",
    )
    session.commit()
    return DemoReset(
        sellers=report.sellers, products=report.products, passports=report.passports, order_id=DEMO_ORDER_ID
    )
