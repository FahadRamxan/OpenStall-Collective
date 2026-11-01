"""The event log: every important action, in order. It feeds the /demo page and doubles as the audit log.

record_event() adds an event to the caller's session, so it is saved in the same transaction as the action it
describes. Every event carries a one-line summary in plain English for the live feed.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openstall_api.db import new_session
from openstall_api.models import Event

POLL_SECONDS = 0.5  # how often the stream looks for new rows
BATCH = 100  # most events sent per look


class EventType(StrEnum):
    """Every kind of event, in one place. The part before the dot is the category the feed shows."""

    LISTING_DRAFT_UPDATED = "listing.draft_updated"
    LISTING_PUBLISHED = "listing.published"
    SEARCH_LOGGED = "search.logged"
    QUOTE_REQUESTED = "quote.requested"
    QUOTE_ROUND_FINISHED = "quote.round_finished"
    QUOTE_COMPLETED = "quote.completed"
    OFFER_PROPOSED = "offer.proposed"
    OFFER_REJECTED = "offer.rejected"
    OFFER_ACCEPTED = "offer.accepted"
    ALLOCATION_PLANNED = "allocation.planned"
    ORDER_DRAFTED = "order.drafted"
    ORDER_CHECKOUT_STARTED = "order.checkout_started"
    ORDER_AUTHORIZED = "order.authorized"
    ORDER_REPLANNED = "order.replanned"
    ORDER_COMPLETED = "order.completed"
    PART_RESERVED = "part.reserved"
    PART_CAPTURED = "part.captured"
    PART_RELEASED = "part.released"
    PART_DROPPED = "part.dropped"
    TOPUP_CREATED = "topup.created"
    ADVANCE_REQUESTED = "advance.requested"
    ADVANCE_PAID = "advance.paid"
    PAYMENT_WEBHOOK = "payment.webhook"
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    MESSAGE_TRANSCRIBED = "message.transcribed"
    TRACKING_READ = "tracking.read"
    TRACKING_CONFIRMED = "tracking.confirmed"
    DELIVERY_CONFIRMED = "delivery.confirmed"
    PASSPORT_ISSUED = "passport.issued"
    PASSPORT_UPDATED = "passport.updated"
    SECURITY_REJECTED = "security.rejected"
    DEMO_TEST = "demo.test"  # made with POST /api/dev/events, in fake mode only


class EventOut(BaseModel):
    id: int
    type: str
    entity_id: str | None
    summary: str
    payload: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, event: Event) -> "EventOut":
        payload = dict(event.payload_json)
        summary = payload.pop("summary", "") or event.type
        created_at = event.created_at
        if created_at.tzinfo is None:  # SQLite drops the zone; we always store UTC, so say so for the browser
            created_at = created_at.replace(tzinfo=UTC)
        return cls(
            id=event.id,
            type=event.type,
            entity_id=event.entity_id,
            summary=summary,
            payload=payload,
            created_at=created_at,
        )


def jsonable(value: Any) -> Any:
    """Make a payload safe for a JSON column. Money stays exact: a Decimal becomes a string such as "216.00"."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"cannot store a {type(value).__name__} in an event payload")


def record_event(
    session: Session,
    type: EventType,
    summary: str,
    *,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    """Add an event to the session and give it its id. The caller commits, together with the action itself."""
    if not isinstance(type, EventType):
        raise ValueError(f"unknown event type {type!r}: add it to EventType first")
    if not summary.strip():
        raise ValueError("every event needs a one-line summary for the live feed")
    event = Event(
        type=type.value,
        entity_id=entity_id,
        payload_json={"summary": summary.strip(), **jsonable(payload or {})},
    )
    session.add(event)
    session.flush()
    return event


def events_after(after_id: int, limit: int) -> list[EventOut]:
    """Events with an id above after_id, oldest first."""
    with new_session() as session:
        rows = session.scalars(select(Event).where(Event.id > after_id).order_by(Event.id).limit(limit))
        return [EventOut.of(row) for row in rows]


def latest_events(limit: int) -> list[EventOut]:
    """The most recent events, oldest first, so a page can show them and then follow the stream."""
    with new_session() as session:
        rows = session.scalars(select(Event).order_by(Event.id.desc()).limit(limit)).all()
        return [EventOut.of(row) for row in reversed(rows)]


def last_event_id() -> int:
    with new_session() as session:
        return session.scalar(select(func.max(Event.id))) or 0


async def event_stream(
    after_id: int,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_seconds: float = POLL_SECONDS,
) -> AsyncIterator[dict[str, str]]:
    """Server-sent events for every event after `after_id`, as they are written, until the client goes away.

    It polls the table rather than listening in-process, so it also sees events written by another server
    instance. Each message's id is the event id, so a reconnecting browser sends it back as Last-Event-ID.
    """
    cursor = after_id
    while not await is_disconnected():
        events = await run_in_threadpool(events_after, cursor, BATCH)
        for event in events:
            cursor = event.id
            yield {"id": str(event.id), "data": event.model_dump_json()}
        if len(events) < BATCH:
            await asyncio.sleep(poll_seconds)
