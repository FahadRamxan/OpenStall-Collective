"""The allocator on real quotes (spec 3.4): a quote's valid offers become a stored plan that viewers can see.

The core's allocate() decides the split, cheapest first; this module maps each maker's valid offer onto its Offer type,
stores the plan on the quote request (plan_json) and records allocation.planned. Planning the same quote again gives
the same plan, which replaces the stored one without a second event.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_allocator import Offer as CoreOffer
from openstall_allocator import Plan, allocate
from openstall_api.events import EventType, jsonable, record_event
from openstall_api.models import Offer, Seller
from openstall_api.models import QuoteRequest as QuoteRequestRow


class PlanLineOut(BaseModel):
    """One maker's share of the order."""

    seller_id: str
    seller_name: str
    offer_id: str | None
    quantity: int
    unit_price: Decimal  # sent as a string such as "29.00", so it stays exact
    line_total: Decimal
    delivery_date: date


class PlanOut(BaseModel):
    """How a quote's order is split across makers, cheapest first, as GET /api/quotes/{id}/plan gives it."""

    request_id: str
    requested_quantity: int
    total_quantity: int
    total_cost: Decimal
    complete: bool = Field(description="True when the plan fills the whole quantity.")
    shortfall: int = Field(description="Units no valid offer can supply; 0 for a complete plan.")
    reason: str | None = Field(description="Why the plan is short, in words; null for a complete plan.")
    lines: list[PlanLineOut] = Field(description="Each maker's share, in the order the allocator chose them.")


def valid_offers(session: Session, request_id: str) -> list[Offer]:
    """Each maker's valid offer for the request, one at most: her latest valid one, if a quote ever saved two."""
    rows = session.scalars(
        select(Offer)
        .where(Offer.request_id == request_id, Offer.is_valid.is_(True))
        .order_by(Offer.created_at, Offer.id)
    )
    latest: dict[str, Offer] = {}
    for row in rows:
        latest[row.seller_id] = row
    return list(latest.values())


def plan_quote(session: Session, request: QuoteRequestRow) -> PlanOut:
    """Split the request across its valid offers with the core allocator, and store the plan. The caller commits."""
    offers = valid_offers(session, request.id)
    plan = allocate(
        [
            CoreOffer(
                seller_id=offer.seller_id,
                unit_price=offer.unit_price,
                quantity=offer.quantity,
                delivery_date=offer.delivery_date,
                offer_id=offer.id,
            )
            for offer in offers
        ],
        request.quantity,
        request.deadline,
    )
    names = {offer.seller_id: offer.seller.name for offer in offers}
    out = plan_out(request.id, plan, names)
    stored = jsonable(out.model_dump())
    if request.plan_json != stored:
        request.plan_json = stored
        record_event(
            session,
            EventType.ALLOCATION_PLANNED,
            plan_summary(out),
            entity_id=request.id,
            payload=stored,
        )
    return out


def stored_plan(session: Session, request: QuoteRequestRow) -> PlanOut | None:
    """The plan stored on the request, with the makers' names as they are now; None until it is planned."""
    if request.plan_json is None:
        return None
    plan = PlanOut.model_validate(request.plan_json)
    sellers = {line.seller_id for line in plan.lines}
    names = {row.id: row.name for row in session.execute(select(Seller.id, Seller.name).where(Seller.id.in_(sellers)))}
    for line in plan.lines:
        line.seller_name = names.get(line.seller_id, line.seller_name)
    return plan


def plan_out(request_id: str, plan: Plan, names: dict[str, str]) -> PlanOut:
    return PlanOut(
        request_id=request_id,
        requested_quantity=plan.requested_quantity,
        total_quantity=plan.total_quantity,
        total_cost=plan.total_cost,
        complete=plan.complete,
        shortfall=plan.shortfall,
        reason=plan.reason,
        lines=[
            PlanLineOut(
                seller_id=line.seller_id,
                seller_name=names.get(line.seller_id, line.seller_id),
                offer_id=line.offer_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.line_total,
                delivery_date=line.delivery_date,
            )
            for line in plan.lines
        ],
    )


def plan_summary(plan: PlanOut) -> str:
    """The plan in one line for the live feed: 'Split 40 across 4 makers, cheapest first: Priya 11, Amina 12, ...'."""
    shares = ", ".join(f"{line.seller_name} {line.quantity}" for line in plan.lines)
    total = f"${plan.total_cost:,.2f}"
    makers = "1 maker" if len(plan.lines) == 1 else f"{len(plan.lines)} makers"
    if plan.complete:
        return f"Split {plan.total_quantity} across {makers}, cheapest first: {shares} ({total})"
    if not plan.lines:
        return f"No valid offer can supply any of the {plan.requested_quantity} asked for"
    return f"Only {plan.total_quantity} of {plan.requested_quantity} possible: {shares} ({total})"
