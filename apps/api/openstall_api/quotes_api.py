"""Quote requests over HTTP, for the /demo page's Request card: GET /api/quotes and GET /api/quotes/{id}."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openstall_api.allocation import PlanOut, stored_plan
from openstall_api.db import get_session
from openstall_api.models import Offer
from openstall_api.models import QuoteRequest as QuoteRequestRow

router = APIRouter(prefix="/api", tags=["quotes"])

SessionDep = Annotated[Session, Depends(get_session)]


class QuoteOut(BaseModel):
    """A buyer agent's quote request and how far its negotiation has got."""

    id: str
    queries: list[str] = Field(description="What the buyer asked for, in their words: one entry per item.")
    quantity: int
    max_unit_price: Decimal  # sent as a string such as "30.00", so it stays exact
    deadline: date
    ship_to: str
    created_at: datetime
    rounds: int = Field(description="Rounds run so far: 0 until the first round ends.")
    completed_at: datetime | None = Field(description="When the last round ended; null while agents are asked.")
    asked: int = Field(description="Makers whose agents were asked.")
    valid_offers: int = Field(description="Makers with a valid offer.")
    total_capacity: int = Field(description="Units the valid offers add up to.")

    @classmethod
    def of(cls, session: Session, request: QuoteRequestRow) -> "QuoteOut":
        asked, valid, capacity = session.execute(
            select(
                func.count(func.distinct(Offer.seller_id)),
                func.count(Offer.id).filter(Offer.is_valid.is_(True)),
                func.coalesce(func.sum(Offer.quantity).filter(Offer.is_valid.is_(True)), 0),
            ).where(Offer.request_id == request.id)
        ).one()
        return cls(
            id=request.id,
            queries=[str(item.get("query", "")) for item in request.items_json if isinstance(item, dict)],
            quantity=request.quantity,
            max_unit_price=request.max_unit_price,
            deadline=request.deadline,
            ship_to=request.ship_to,
            created_at=_utc(request.created_at),
            rounds=request.rounds,
            completed_at=None if request.completed_at is None else _utc(request.completed_at),
            asked=max(asked, request.asked or 0),
            valid_offers=valid,
            total_capacity=int(capacity),
        )


def _utc(moment: datetime) -> datetime:
    """SQLite drops the zone; we always store UTC, so say so for the browser."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@router.get("/quotes")
def recent_quotes(session: SessionDep, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> list[QuoteOut]:
    """The most recent quote requests, newest first. A request's progress arrives as quote.* events."""
    rows = session.scalars(select(QuoteRequestRow).order_by(QuoteRequestRow.created_at.desc()).limit(limit))
    return [QuoteOut.of(session, row) for row in rows]


@router.get("/quotes/{request_id}")
def get_quote(request_id: str, session: SessionDep) -> QuoteOut:
    request = session.get(QuoteRequestRow, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"There is no quote request called {request_id!r}.")
    return QuoteOut.of(session, request)


@router.get("/quotes/{request_id}/plan")
def get_plan(request_id: str, session: SessionDep) -> PlanOut:
    """How the quote's order is split across makers, cheapest first, and whether it is complete or short."""
    request = session.get(QuoteRequestRow, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"There is no quote request called {request_id!r}.")
    plan = stored_plan(session, request)
    if plan is None:
        raise HTTPException(
            status_code=404, detail=f"Quote request {request_id!r} has no plan yet: its rounds are not done."
        )
    return plan
