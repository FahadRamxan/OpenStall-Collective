"""Seller agents' offers over HTTP, for the /demo page's offers table: GET /api/offers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openstall_api.db import get_session
from openstall_api.models import Offer, Seller
from openstall_api.offers import OfferOut

router = APIRouter(prefix="/api", tags=["offers"])


@router.get("/offers")
def recent_offers(
    session: Annotated[Session, Depends(get_session)],
    request_id: Annotated[str | None, Query(max_length=32, description="Only this quote request's offers.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[OfferOut]:
    """The most recent proposals, newest first, valid and refused. New ones arrive on the event stream as
    offer.accepted and offer.rejected events."""
    query = select(Offer).options(selectinload(Offer.seller).selectinload(Seller.products), selectinload(Offer.request))
    if request_id is not None:
        query = query.where(Offer.request_id == request_id)
    rows = session.scalars(query.order_by(Offer.created_at.desc(), Offer.id.desc()).limit(limit))
    return [OfferOut.of(row) for row in rows]
