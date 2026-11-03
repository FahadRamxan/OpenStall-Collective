"""The scripted buyer agent and the demo controls (prompt 29): scripts/run_demo_request.py over HTTP and
POST /api/demo/run in process play the same story through the MCP storefront, and POST /api/demo/reset puts the demo
world back as seeded. In sandbox mode both controls need the DEMO_RUN_TOKEN header."""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import func, select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.buyer import run_story
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Offer, Order, QuoteRequest, Seller
from openstall_api.passports import FAKE_MODE_KEY_B64
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order

client = TestClient(app)

TODAY = date(2026, 11, 10)
STORY_SPLIT = [["Priya", 11], ["Amina", 12], ["Lucía", 10], ["Grace", 7]]


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    return db


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_the_demo_run_plays_the_story_through_the_storefront(seeded):
    response = client.post("/api/demo/run")

    assert response.status_code == 200
    run = response.json()
    assert run["shares"] == STORY_SPLIT
    assert run["total_usd"] == "815.00"
    assert run["approval_url"] == f"http://localhost:3000/approve/{run['order_id']}"
    assert run["steps"][0].startswith("1. Searched for “40 hand-embroidered cushion covers for corporate gifts”")
    assert run["steps"][-2] == f"5. Approval link for the human: {run['approval_url']}"
    order = seeded.get(Order, run["order_id"])
    assert (order.source, order.status.value) == ("mcp", "draft")
    # The feed: the run starts, then each step of the stepper.
    types = [event.type for event in seeded.scalars(select(Event).order_by(Event.id))]
    started = types.index("demo.run")
    after = types[started:]
    for step in ("search.logged", "quote.requested", "offer.accepted", "allocation.planned", "checkout.link_issued"):
        assert step in after, step


def test_the_script_over_http_and_the_endpoint_make_the_same_order(seeded, server_url):
    async def script():
        async with Client(server_url) as mcp:
            return await run_story(mcp, TODAY, say=lambda line: None)

    scripted = asyncio.run(script())
    endpoint = client.post("/api/demo/run").json()

    assert [list(share) for share in scripted.shares] == endpoint["shares"] == STORY_SPLIT
    assert scripted.total_usd == endpoint["total_usd"] == "815.00"
    assert scripted.order_id != endpoint["order_id"]


def test_reset_puts_the_demo_world_back_as_seeded_and_keeps_the_feed(seeded):
    assert client.post("/api/demo/run").status_code == 200
    assert count(seeded, Offer) > 0
    events_before = count(seeded, Event)

    response = client.post("/api/demo/reset")

    assert response.status_code == 200
    assert response.json() == {"sellers": 5, "products": 5, "passports": 5, "order_id": DEMO_ORDER_ID}
    seeded.expire_all()
    assert (count(seeded, Offer), count(seeded, QuoteRequest), count(seeded, Order)) == (0, 1, 1)
    assert count(seeded, Seller) == 5
    assert seeded.get(Order, DEMO_ORDER_ID).status.value == "draft"
    # The feed keeps its history, and says the demo was reset.
    assert count(seeded, Event) > events_before
    last = seeded.scalars(select(Event).order_by(Event.id.desc()).limit(1)).one()
    assert last.type == EventType.DEMO_RESET.value


@pytest.mark.parametrize("path", ["/api/demo/run", "/api/demo/reset"])
def test_sandbox_mode_needs_the_token(use_settings, db, path):
    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-demo-token", PASSPORT_SIGNING_KEY=FAKE_MODE_KEY_B64)

    missing = client.post(path)
    wrong = client.post(path, headers={"X-Demo-Run-Token": "not-it"})

    assert (missing.status_code, wrong.status_code) == (401, 401)
    assert missing.json()["detail"] == "The demo controls need the X-Demo-Run-Token header."


def test_sandbox_mode_resets_with_the_token(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-demo-token", PASSPORT_SIGNING_KEY=FAKE_MODE_KEY_B64)

    response = client.post("/api/demo/reset", headers={"X-Demo-Run-Token": "made-up-demo-token"})

    assert response.status_code == 200
    assert response.json()["sellers"] == 5


@pytest.mark.parametrize("path", ["/api/demo/run", "/api/demo/reset"])
def test_sandbox_mode_without_a_token_set_keeps_the_controls_off(use_settings, db, path):
    use_settings(OPENSTALL_MODE="sandbox")

    response = client.post(path, headers={"X-Demo-Run-Token": "anything"})

    assert response.status_code == 403
    assert response.json()["detail"] == "The demo controls are off: DEMO_RUN_TOKEN is not set."
