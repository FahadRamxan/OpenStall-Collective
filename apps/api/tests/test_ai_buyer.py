"""A real AI agent as the buyer (prompt 30): POST /api/demo/run-agent hands the story's request, in words, to a buyer's
AI agent that chooses the MCP storefront's tools itself, in process. In test mode the stand-in chooses; in sandbox mode
it is Claude, which needs ANTHROPIC_API_KEY."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.demo_api import story_request_words
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order
from openstall_api.seed import reset_demo_world

client = TestClient(app)
TODAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def world(db):
    reset_demo_world(db, TODAY)
    db.commit()
    return db


def test_the_request_reads_as_a_person_would_give_it():
    assert story_request_words(TODAY) == (
        "Please buy 40 hand-embroidered cushion covers for corporate gifts, at most $30.00 each, delivered to "
        "Chicago by 2026-12-10. Get me the approval link: I approve the payment myself."
    )


def test_the_agent_chooses_the_tools_and_gets_its_person_the_approval_link(world, fakes):
    response = client.post("/api/demo/run-agent")

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["agent"] == "test mode's stand-in for Claude" and run["finished"] is True
    assert [step["tool"] for step in run["steps"]] == [
        "search_products",
        "request_quote",
        "create_collective_order",
        "checkout",
    ]
    assert all(step["ok"] for step in run["steps"])
    assert run["total_usd"] == "815.00" and run["approval_url"].endswith(f"/approve/{run['order_id']}")
    assert run["said"][-1].endswith(run["approval_url"])
    world.expire_all()
    order = world.get(Order, run["order_id"])
    assert order.source == "mcp" and order.request_id == run["request_id"]  # drafted through the storefront
    feed = {
        event.type: event.payload_json["summary"]
        for event in world.scalars(select(Event).where(Event.type.like("agent.%")))
    }
    assert feed[EventType.AGENT_STARTED.value].startswith(
        "A buyer's AI agent (test mode's stand-in for Claude) got a person's request: “Please buy 40"
    )
    assert feed[EventType.AGENT_FINISHED.value] == (
        f"The buyer's AI agent drafted order {run['order_id']} ($815.00) and got its person the approval link"
    )
    assert fakes.payment_gateway.calls == []  # the agent cannot move money: a person approves at the link


def test_in_sandbox_mode_it_needs_the_token_and_a_claude_key(world, use_settings):
    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-token")
    assert client.post("/api/demo/run-agent").status_code == 401

    refused = client.post("/api/demo/run-agent", headers={"X-Demo-Run-Token": "made-up-token"})

    assert refused.status_code == 503
    assert refused.json()["detail"].startswith("The buyer's AI agent is not available:")
    assert "ANTHROPIC_API_KEY" in refused.json()["detail"]
