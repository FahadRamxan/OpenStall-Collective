"""The /demo page's own API: GET /api/demo/limits, what the offer rules allow each live maker (spec 3.3).

The numbers come from the allocator core through offer_rules.py, the same rules every offer is checked against, so
viewers see each maker's limits before the offers arrive. Prompt 29 adds the run and reset controls here.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_allocator import Clock, SystemClock
from openstall_api.db import get_session
from openstall_api.models import DataSource
from openstall_api.offer_rules import MakerLimits, default_deadline, limits_by_deadline

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
