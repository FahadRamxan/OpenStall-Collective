"""The allocator on real quotes (prompt 25): a quote's valid offers become a stored plan, cheapest first, with a plain
reason when the offers cannot fill the order, and GET /api/quotes/{id}/plan for the /demo Allocation panel."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.allocation import plan_quote, valid_offers
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event
from openstall_api.quotes import create_quote_request, run_quote
from openstall_api.seed import DEMO_ORDER_ID, DEMO_REQUEST, seed, seed_demo_order

client = TestClient(app)

TODAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def story_quote(db, llm, quantity: int = 40):
    request, products = create_quote_request(
        db, [DEMO_REQUEST], quantity, Decimal("30.00"), TODAY + timedelta(days=30), "Chicago", TODAY
    )
    db.commit()
    run_quote(db, request, products, llm, TODAY)
    return request


def planned_events(db) -> list[Event]:
    return list(db.scalars(select(Event).where(Event.type == EventType.ALLOCATION_PLANNED.value)))


def test_the_story_splits_12_11_10_7_cheapest_first_and_costs_815(seeded, fakes):
    request = story_quote(seeded, fakes.llm)

    plan = client.get(f"/api/quotes/{request.id}/plan").json()

    assert [(line["seller_name"], line["quantity"], line["unit_price"]) for line in plan["lines"]] == [
        ("Priya", 11, "16.00"),
        ("Amina", 12, "18.00"),
        ("Lucía", 10, "22.00"),
        ("Grace", 7, "29.00"),
    ]
    assert [line["line_total"] for line in plan["lines"]] == ["176.00", "216.00", "220.00", "203.00"]
    assert (plan["total_quantity"], plan["total_cost"], plan["complete"], plan["shortfall"], plan["reason"]) == (
        40,
        "815.00",
        True,
        0,
        None,
    )
    assert {line["delivery_date"] for line in plan["lines"]} == {"2026-12-10"}
    # Each line points at the offer it came from; Noor, the backup, is left out.
    offers = {offer.seller_id: offer.id for offer in valid_offers(seeded, request.id)}
    assert [line["offer_id"] for line in plan["lines"]] == [offers[s] for s in ("s_priya", "s_amina", "s_lucia", "s_grace")]
    events = planned_events(seeded)
    assert [e.payload_json["summary"] for e in events] == [
        "Split 40 across 4 makers, cheapest first: Priya 11, Amina 12, Lucía 10, Grace 7 ($815.00)"
    ]


def test_planning_again_keeps_one_plan_and_one_event(seeded, fakes):
    request = story_quote(seeded, fakes.llm)
    first = request.plan_json

    plan_quote(seeded, request)
    seeded.commit()

    assert request.plan_json == first
    assert len(planned_events(seeded)) == 1


def test_offers_that_cannot_fill_the_order_give_a_short_plan_with_a_plain_reason(seeded, fakes):
    # The story's draft order, reserved: its 12/11/10/7 use up Amina, Priya and Lucía and most of Grace.
    seed_demo_order(seeded, TODAY)
    seeded.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200

    request = story_quote(seeded, fakes.llm)
    plan = client.get(f"/api/quotes/{request.id}/plan").json()

    assert [(line["seller_name"], line["quantity"]) for line in plan["lines"]] == [("Grace", 4), ("Noor", 10)]
    assert (plan["complete"], plan["total_quantity"], plan["shortfall"]) == (False, 14, 26)
    assert plan["reason"] == "Only 14 of 40 units can be supplied by 2026-12-10."
    assert planned_events(seeded)[-1].payload_json["summary"] == "Only 14 of 40 possible: Grace 4, Noor 10 ($411.00)"


def test_a_quote_nobody_can_supply_plans_nothing_and_says_so(seeded, fakes):
    request, products = create_quote_request(
        seeded, ["ceramic mugs"], 40, Decimal("30.00"), TODAY + timedelta(days=30), "Chicago", TODAY
    )
    seeded.commit()
    run_quote(seeded, request, products, fakes.llm, TODAY)

    plan = client.get(f"/api/quotes/{request.id}/plan").json()

    assert (plan["lines"], plan["complete"], plan["shortfall"]) == ([], False, 40)
    assert plan["reason"] == "Only 0 of 40 units can be supplied by 2026-12-10. No seller made an offer."
    assert planned_events(seeded)[-1].payload_json["summary"] == "No valid offer can supply any of the 40 asked for"


def test_a_quote_without_a_plan_yet_and_an_unknown_quote_say_so(seeded):
    request, _ = create_quote_request(
        seeded, [DEMO_REQUEST], 40, Decimal("30.00"), TODAY + timedelta(days=30), "Chicago", TODAY
    )
    seeded.commit()

    unplanned = client.get(f"/api/quotes/{request.id}/plan")
    assert unplanned.status_code == 404
    assert unplanned.json()["detail"] == "Quote request " + repr(request.id) + " has no plan yet: its rounds are not done."
    assert client.get("/api/quotes/q_nobody/plan").status_code == 404
