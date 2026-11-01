"""The event log over HTTP: GET /api/events, the live stream at /api/events/stream, and a test event in fake mode."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette import EventSourceResponse

from openstall_api.db import get_session
from openstall_api.events import (
    EventOut,
    EventType,
    event_stream,
    events_after,
    last_event_id,
    latest_events,
    record_event,
)
from openstall_api.settings import get_settings

router = APIRouter(prefix="/api", tags=["events"])

HEARTBEAT_SECONDS = 15


class EventPage(BaseModel):
    events: list[EventOut]


@router.get("/events")
def list_events(
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EventPage:
    """With after_id: the events after it, oldest first. Without: the most recent ones, oldest first."""
    events = events_after(after_id, limit) if after_id is not None else latest_events(limit)
    return EventPage(events=events)


def resume_point(last_event_id_header: str | None, after_id: int | None) -> int | None:
    """Where a stream starts: a reconnecting browser's Last-Event-ID wins, then ?after_id, else only new events."""
    if last_event_id_header and last_event_id_header.strip().isdigit():
        return int(last_event_id_header.strip())
    return after_id


@router.get("/events/stream")
async def stream_events(
    request: Request,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    start = resume_point(last_event_id_header, after_id)
    if start is None:
        start = await run_in_threadpool(last_event_id)
    # The ping is an SSE comment: it keeps proxies from closing a quiet connection.
    return EventSourceResponse(event_stream(start, request.is_disconnected), ping=HEARTBEAT_SECONDS)


class DevEventIn(BaseModel):
    summary: str = Field(default="A test event from POST /api/dev/events", min_length=1, max_length=200)


def fake_mode_only() -> None:
    """Dev endpoints exist only in fake mode; anywhere else they are simply not found."""
    if get_settings().OPENSTALL_MODE != "fake":
        raise HTTPException(status_code=404)


@router.post("/dev/events", dependencies=[Depends(fake_mode_only)], status_code=201)
def create_test_event(body: DevEventIn, session: Annotated[Session, Depends(get_session)]) -> EventOut:
    event = record_event(session, EventType.DEMO_TEST, body.summary)
    session.commit()
    return EventOut.of(event)
