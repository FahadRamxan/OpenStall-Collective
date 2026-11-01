"""The event log: record_event, GET /api/events, the live stream, and the fake-mode test endpoint."""

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_api.db import session_scope
from openstall_api.events import EventOut, EventType, event_stream, last_event_id, record_event
from openstall_api.events_api import resume_point
from openstall_api.main import app
from openstall_api.models import Event, PartStatus

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)


def add_events(db, count: int) -> list[int]:
    ids = [record_event(db, EventType.DEMO_TEST, f"event {n}").id for n in range(1, count + 1)]
    db.commit()
    return ids


def event_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Event))


# ---------- record_event ----------


def test_an_event_keeps_its_summary_and_its_payload_is_made_json_safe(db):
    event = record_event(
        db,
        EventType.PART_CAPTURED,
        "Amina was paid $216.00 on proof",
        entity_id="op_1",
        payload={
            "amount": Decimal("216.00"),
            "ship_by": date(2026, 11, 30),
            "status": PartStatus.CAPTURED,
            "sellers": ("s_amina",),
        },
    )
    db.commit()

    out = EventOut.of(event)

    assert isinstance(event.id, int)
    assert out.type == "part.captured"
    assert out.entity_id == "op_1"
    assert out.summary == "Amina was paid $216.00 on proof"
    # Money stays exact as a string, not a float.
    assert out.payload == {"amount": "216.00", "ship_by": "2026-11-30", "status": "captured", "sellers": ["s_amina"]}


def test_unknown_types_empty_summaries_and_unsafe_payloads_are_refused(db):
    with pytest.raises(ValueError, match="EventType"):
        record_event(db, "made.up", "anything")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="summary"):
        record_event(db, EventType.DEMO_TEST, "   ")
    with pytest.raises(TypeError):
        record_event(db, EventType.DEMO_TEST, "anything", payload={"bad": object()})


def test_an_event_is_saved_together_with_its_action_or_not_at_all(db):
    record_event(db, EventType.ORDER_AUTHORIZED, "Order reserved")
    db.rollback()

    assert event_count(db) == 0


# ---------- GET /api/events ----------


def test_without_after_id_the_latest_events_come_back_oldest_first(db):
    add_events(db, 5)

    events = client.get("/api/events", params={"limit": 3}).json()["events"]

    assert [event["summary"] for event in events] == ["event 3", "event 4", "event 5"]


def test_after_id_returns_what_came_next_in_order(db):
    ids = add_events(db, 5)

    events = client.get("/api/events", params={"after_id": ids[1], "limit": 2}).json()["events"]

    assert [event["id"] for event in events] == ids[2:4]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"after_id": -1}])
def test_bad_paging_is_refused(db, params):
    assert client.get("/api/events", params=params).status_code == 422


# ---------- the stream ----------


def run_stream(after_id: int, wanted: int, write_later=None, timeout: float = 5.0) -> list[dict]:
    """Read the stream until `wanted` messages arrive. `write_later` runs in a thread once the stream is running."""

    async def go() -> list[dict]:
        received: list[dict] = []

        async def disconnected() -> bool:
            return len(received) >= wanted

        stream = event_stream(after_id, disconnected, poll_seconds=0.02)

        async def read() -> None:
            async for message in stream:
                received.append(message)
                if len(received) >= wanted:
                    break

        reader = asyncio.create_task(read())
        if write_later is not None:
            await asyncio.sleep(0.1)  # the stream has looked once and found nothing new
            await asyncio.to_thread(write_later)
        await asyncio.wait_for(reader, timeout)
        await stream.aclose()
        return received

    return asyncio.run(go())


def test_the_stream_sends_the_events_after_its_starting_point_in_order(db):
    ids = add_events(db, 3)

    messages = run_stream(after_id=ids[0], wanted=2)

    assert [int(message["id"]) for message in messages] == ids[1:]
    assert [json.loads(message["data"])["summary"] for message in messages] == ["event 2", "event 3"]


def test_the_stream_sends_an_event_written_after_the_client_connected(db):
    add_events(db, 1)
    start = last_event_id()

    def write() -> None:
        with session_scope() as session:
            record_event(session, EventType.ORDER_AUTHORIZED, "Order ord_1 reserved: $815.00 across 4 makers")

    messages = run_stream(after_id=start, wanted=1, write_later=write)

    assert json.loads(messages[0]["data"])["summary"] == "Order ord_1 reserved: $815.00 across 4 makers"
    assert int(messages[0]["id"]) == start + 1


def test_the_stream_stops_as_soon_as_the_client_goes_away(db):
    add_events(db, 2)

    async def go() -> list[dict]:
        async def disconnected() -> bool:
            return True

        return [message async for message in event_stream(0, disconnected, poll_seconds=0.02)]

    assert asyncio.run(asyncio.wait_for(go(), 2)) == []


@pytest.mark.parametrize(
    ("header", "after_id", "expected"),
    [
        ("41", None, 41),  # a reconnecting browser resumes after the last event it saw
        ("41", 7, 41),  # and that wins over the query string
        (" 41 ", None, 41),
        ("not-a-number", 7, 7),
        (None, 7, 7),
        (None, None, None),  # nothing given: only events from now on
    ],
)
def test_where_a_stream_starts(header, after_id, expected):
    assert resume_point(header, after_id) == expected


# ---------- POST /api/dev/events ----------


def test_the_dev_endpoint_records_a_test_event_in_fake_mode(db):
    response = client.post("/api/dev/events", json={"summary": "Hello from a test"})

    assert response.status_code == 201
    assert response.json()["type"] == "demo.test"
    assert client.get("/api/events").json()["events"][-1]["summary"] == "Hello from a test"


def test_the_dev_endpoint_does_not_exist_in_sandbox_mode(db, use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    response = client.post("/api/dev/events", json={"summary": "Should not be saved"})

    assert response.status_code == 404
    assert event_count(db) == 0


@pytest.mark.parametrize("summary", ["", "x" * 201])
def test_the_dev_endpoint_refuses_an_empty_or_huge_summary(db, summary):
    assert client.post("/api/dev/events", json={"summary": summary}).status_code == 422
