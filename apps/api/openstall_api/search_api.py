"""The search log over HTTP, for the /demo page's "Agent searches" panel: GET /api/searches."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from openstall_api.db import get_session
from openstall_api.models import Search

router = APIRouter(prefix="/api", tags=["search"])


class SearchOut(BaseModel):
    """One search_products call: what was asked, the filters the agent gave, and how many results it found."""

    id: str
    query: str
    filters: dict[str, Any]
    result_count: int
    created_at: datetime

    @classmethod
    def of(cls, search: Search) -> "SearchOut":
        created_at = search.created_at
        if created_at.tzinfo is None:  # SQLite drops the zone; we always store UTC, so say so for the browser
            created_at = created_at.replace(tzinfo=UTC)
        return cls(
            id=search.id,
            query=search.query,
            filters=dict(search.filters_json),
            result_count=search.result_count,
            created_at=created_at,
        )


@router.get("/searches")
def recent_searches(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SearchOut]:
    """The most recent searches, newest first. New ones arrive on the event stream as search.logged events."""
    seeded = Search.filters_json["data_source"].as_string()
    rows = session.scalars(
        select(Search)
        .where(or_(seeded.is_(None), seeded != "seeded_demo"))  # Demand Radar's seeded searches are not agents'
        .order_by(Search.created_at.desc(), Search.id.desc())
        .limit(limit)
    )
    return [SearchOut.of(row) for row in rows]
