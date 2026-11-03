"""Dev endpoints for UI tests and demos, in fake mode only. In sandbox mode they do not exist."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.adapters import AdapterRegistry, get_registry
from openstall_api.db import get_session
from openstall_api.events_api import fake_mode_only
from openstall_api.models import OrderPart, PartStatus
from openstall_api.orders_api import OrderOut, _load, order_out, payment_errors
from openstall_api.payments import pay_share, release_share
from openstall_api.seed import story_order
from openstall_api.webhooks import deliver_fake_webhooks

router = APIRouter(prefix="/api/dev", tags=["dev"], dependencies=[Depends(fake_mode_only)])

SessionDep = Annotated[Session, Depends(get_session)]

# The carrier code PayPal's tracking API takes for a courier it does not list.
SIMULATED_CARRIER = "OTHER"


class NewOrder(BaseModel):
    order_id: str


class Released(BaseModel):
    released: int  # shares released


@router.post("/story-orders", status_code=201)
def create_story_order(session: SessionDep) -> NewOrder:
    """A fresh draft of the story's order (12/11/10/7, $815.00), so each UI test can pay for an order of its own.
    The seeded makers must exist (scripts/seed_demo.py)."""
    order = story_order(session, datetime.now(UTC).date())
    session.commit()
    return NewOrder(order_id=order.id)


@router.post("/parts/{part_id}/proof")
def simulate_proof(
    part_id: str,
    session: SessionDep,
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
    background: BackgroundTasks,
) -> OrderOut:
    """Simulated proof of shipping for one share: a made-up tracking number (SIMULATED-<part id>, carrier OTHER),
    then the same pay_share the receipt photo will call (prompt 32), so the receipt can show paid shares now.

    A share with tracking of its own keeps it. A share that cannot be paid (released, or no payout rail can reach
    her) is refused with 409, and nothing is saved.
    """
    part = session.get(OrderPart, part_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"There is no order share called {part_id!r}.")
    if not part.tracking_number:
        part.tracking_number = f"SIMULATED-{part.id}"[:64]
        part.carrier = SIMULATED_CARRIER
    with payment_errors():
        pay_share(session, part_id, registry.payment_gateway)
    session.commit()
    background.add_task(deliver_fake_webhooks)  # simulated PayPal's capture and payout confirmations follow
    return order_out(session, _load(session, part.order_id))


@router.post("/release-reserved-shares")
def release_reserved_shares(
    session: SessionDep,
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
    background: BackgroundTasks,
) -> Released:
    """Release every reserved share, as if each of those makers had dropped out, so every maker has her seed capacity
    back: reserved shares are her committed units (offer_rules.py). UI tests that check the seed table's numbers call
    it first, because earlier spec files reserve story orders in the same database.
    """
    part_ids = session.scalars(
        select(OrderPart.id).where(OrderPart.status == PartStatus.AUTHORIZED).order_by(OrderPart.id)
    ).all()
    with payment_errors():
        for part_id in part_ids:
            release_share(session, part_id, registry.payment_gateway)
    session.commit()
    background.add_task(deliver_fake_webhooks)  # simulated PayPal's VOIDED confirmations follow
    return Released(released=len(part_ids))
