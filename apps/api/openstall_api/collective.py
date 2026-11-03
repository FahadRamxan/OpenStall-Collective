"""A quote's plan turned into one draft collective order (spec 3.5): each maker's share, and a total worked out here.

The shares come from the plan stored on the quote request (allocation.py), and each share's listing from the offer it
came from; create_draft_order (orders.py) numbers them and works out the total. No price or total is ever taken from
an agent. A request gets one draft: asked again, it gives back the same one.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.allocation import PlanLineOut, stored_plan
from openstall_api.catalog import ID_PATTERN
from openstall_api.models import Offer, Order
from openstall_api.models import QuoteRequest as QuoteRequestRow
from openstall_api.orders import DraftPart, create_draft_order, server_total


class DraftError(ValueError):
    """The request cannot be drafted as asked. The message says why, in words a buyer agent can act on."""


class DraftOrder(BaseModel):
    """A draft order: each maker's share and the total, worked out by OpenStall. Nothing is reserved or paid yet."""

    order_id: str
    request_id: str
    status: str
    total_usd: Decimal = Field(description="The total of the shares, worked out by OpenStall, in whole cents.")
    units: int
    shares: list[PlanLineOut] = Field(description="Each maker's share: units, unit price, line total, delivery date.")
    next_step: str


def draft_from_plan(session: Session, request_id: str, *, accept_partial: bool = False) -> Order:
    """The request's draft order, made from its plan, or the one already made. Raises DraftError in words."""
    request = session.get(QuoteRequestRow, request_id) if ID_PATTERN.fullmatch(request_id) else None
    if request is None:
        raise DraftError(f"There is no quote request called {request_id!r}. request_quote gives each request's id.")
    existing = session.scalars(
        select(Order)
        .where(Order.request_id == request.id, Order.parent_order_id.is_(None))
        .order_by(Order.created_at, Order.id)
    ).first()
    if existing is not None:
        return existing
    plan = stored_plan(session, request)
    if plan is None:
        raise DraftError(f"Quote request {request.id!r} has no plan yet: its rounds are not done.")
    if not plan.lines:
        raise DraftError(
            f"No maker can supply any of the {plan.requested_quantity} units by {_day(request.deadline)}, so there "
            "is nothing to order. Ask for a new quote with a later deadline or a higher maximum price."
        )
    if not plan.complete and not accept_partial:
        raise DraftError(
            f"The plan covers only {plan.total_quantity} of the {plan.requested_quantity} units. Call again with "
            f"accept_partial true to order those {plan.total_quantity}, or ask for a new quote."
        )
    offer_ids = [line.offer_id for line in plan.lines if line.offer_id]
    listings = {row.id: row.product_id for row in session.execute(select(Offer.id, Offer.product_id).where(Offer.id.in_(offer_ids)))}
    parts = [
        DraftPart(
            seller_id=line.seller_id,
            product_id=listings.get(line.offer_id) if line.offer_id else None,
            quantity=line.quantity,
            unit_price=line.unit_price,
            delivery_date=line.delivery_date,
        )
        for line in plan.lines
    ]
    return create_draft_order(session, parts, request_id=request.id)


def draft_out(order: Order) -> DraftOrder:
    """The draft as a buyer agent reads it."""
    return DraftOrder(
        order_id=order.id,
        request_id=order.request_id or "",
        status=order.status.value,
        total_usd=server_total(order),
        units=sum(part.quantity for part in order.parts),
        shares=[
            PlanLineOut(
                seller_id=part.seller_id,
                seller_name=part.seller.name,
                offer_id=None,
                quantity=part.quantity,
                unit_price=part.unit_price_usd,
                line_total=part.amount_usd,
                delivery_date=part.delivery_date,
            )
            for part in order.parts
        ],
        next_step=(
            "A person must approve this draft on OpenStall before any money is reserved: PayPal then holds the "
            "total, and each maker's share is captured only when she proves she shipped."
        ),
    )


def _day(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"
