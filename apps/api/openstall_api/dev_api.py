"""Dev endpoints for UI tests and demos, in fake mode only. In sandbox mode they do not exist."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from openstall_api.db import get_session
from openstall_api.events_api import fake_mode_only
from openstall_api.seed import story_order

router = APIRouter(prefix="/api/dev", tags=["dev"], dependencies=[Depends(fake_mode_only)])


class NewOrder(BaseModel):
    order_id: str


@router.post("/story-orders", status_code=201)
def create_story_order(session: Annotated[Session, Depends(get_session)]) -> NewOrder:
    """A fresh draft of the story's order (12/11/10/7, $815.00), so each UI test can pay for an order of its own.
    The seeded makers must exist (scripts/seed_demo.py)."""
    order = story_order(session, datetime.now(UTC).date())
    session.commit()
    return NewOrder(order_id=order.id)
