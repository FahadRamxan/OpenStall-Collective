"""Try to break it (prompt 40): every attack on the guardrail panel is refused by the code a real request goes
through, each refusal is in the live feed, nothing an attack touched is kept, and no money moves."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.events import EventType
from openstall_api.guardrails import ATTACKS
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, ProcessedWebhook, QuoteRequest
from openstall_api.seed import seed, seed_demo_order

client = TestClient(app)
TODAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    return db


def count(db, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def rejections(db) -> list[str]:
    db.expire_all()
    query = select(Event).where(Event.type == EventType.SECURITY_REJECTED.value).order_by(Event.id)
    return [event.payload_json["summary"] for event in db.scalars(query)]


def run_all() -> dict[str, dict]:
    response = client.post("/api/guardrails/run")
    assert response.status_code == 200, response.text
    outcomes = response.json()
    assert [outcome["key"] for outcome in outcomes] == [attack.key for attack in ATTACKS]
    return {outcome["key"]: outcome for outcome in outcomes}


def test_the_panel_lists_every_attack_and_what_refuses_it(db):
    attacks = client.get("/api/guardrails").json()

    assert [attack["key"] for attack in attacks] == [
        "below_floor",
        "capture_tool",
        "changed_total",
        "forged_webhook",
        "reserve_unapproved",
        "pay_before_proof",
        "flood",
        "tampered_passport",
    ]
    assert all(attack["name"] and attack["guard"] for attack in attacks)
    assert rejections(db) == []  # listing them tries nothing


def test_every_attack_is_refused_and_nothing_it_touched_is_kept(seeded, fakes):
    models = (Order, QuoteRequest, OrderPart, ProcessedWebhook)
    orders, requests, parts, webhooks = (count(seeded, model) for model in models)

    outcomes = run_all()

    results = {key: outcome["result"] for key, outcome in outcomes.items()}
    assert results == {attack.key: "refused" for attack in ATTACKS}
    assert (count(seeded, Order), count(seeded, QuoteRequest), count(seeded, OrderPart)) == (orders, requests, parts)
    assert count(seeded, ProcessedWebhook) == webhooks  # the forged event was never applied
    assert fakes.payment_gateway.calls == []  # nothing reached PayPal: no reserve, no capture
    # Each refusal is in the live feed: one from the panel for each attack but the forged webhook, which records its
    # own; and the flood's limit, which the limits middleware records too.
    feed = rejections(seeded)
    assert len(feed) == len(ATTACKS) + 1
    assert any(summary.startswith("Limit reached: more than 120 calls to the MCP storefront from client ") for summary in feed)
    assert "A PayPal webhook failed verification and was refused" in feed
    assert "Guardrail held: Talk a maker's price down to $1.00. Refused by code (below_floor)" in " ".join(feed)


def test_what_refused_each_attack(seeded, fakes):
    outcomes = run_all()

    assert outcomes["below_floor"]["tried"].startswith("A buyer tells Amina's agent to sell for $1.00, and it proposes")
    assert outcomes["below_floor"]["reason"].startswith("Refused by code (below_floor): her lowest price is $")
    capture = outcomes["capture_tool"]["reason"]
    assert capture.startswith("Refused: there is no such tool. The storefront's 7 tools (")
    for tool in ("checkout", "create_collective_order", "get_order_status", "request_quote", "search_products"):
        assert tool in capture
    assert outcomes["changed_total"]["tried"] == "The browser asks to pay $715.00 for an order of $815.00."
    assert outcomes["changed_total"]["reason"] == (
        "Refused (HTTP 409): The total is $815.00, not $715.00. Totals are worked out on the server."
    )
    assert outcomes["forged_webhook"]["reason"] == "Refused: PayPal did not sign this event. Nothing changed."
    assert "so there is nothing to reserve" in outcomes["reserve_unapproved"]["reason"]
    assert outcomes["pay_before_proof"]["reason"].endswith(
        "paid when her tracking is confirmed, and there is none yet. Nothing was captured."
    )
    assert outcomes["tampered_passport"]["reason"].startswith("Refused: the signature does not match.")
    assert outcomes["flood"]["tried"] == "An agent at one address calls the MCP storefront 150 times in a minute."
    assert outcomes["flood"]["reason"].startswith(
        "Refused by the limits middleware: the first 120 calls were answered, the other 30 got 429 Too Many Requests"
    )


def test_one_attack_at_a_time(seeded):
    response = client.post("/api/guardrails/tampered_passport/run")

    assert response.status_code == 200
    assert response.json()["result"] == "refused"
    assert len(rejections(seeded)) == 1
    assert client.post("/api/guardrails/steal_everything/run").status_code == 404


def test_without_the_seeded_world_the_attacks_that_need_it_are_not_tried(db):
    outcomes = run_all()

    assert outcomes["capture_tool"]["result"] == "refused"
    assert outcomes["forged_webhook"]["result"] == "refused"
    assert outcomes["flood"]["result"] == "refused"  # it needs nothing seeded
    for key in ("below_floor", "changed_total", "reserve_unapproved", "pay_before_proof", "tampered_passport"):
        assert outcomes[key]["result"] == "not_tried", key
    # Only refusals are recorded: the capture tool's, the forged webhook's, and the flood's with its limit.
    assert len(rejections(db)) == 4


def test_in_sandbox_mode_the_panel_needs_the_demo_token(db, use_settings):
    use_settings(OPENSTALL_MODE="sandbox")
    assert client.post("/api/guardrails/run").status_code == 403  # no DEMO_RUN_TOKEN set: the controls are off

    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-token")
    assert client.post("/api/guardrails/run").status_code == 401
    assert client.get("/api/guardrails").status_code == 200  # the list itself is public
