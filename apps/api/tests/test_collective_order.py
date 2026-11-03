"""MCP request_quote and create_collective_order (prompt 27): a buyer agent asks for a quote and turns its plan into
one draft order, with every price and total worked out by OpenStall, and nothing reserved or paid."""

import asyncio
from datetime import date, timedelta

import pytest
from mcp import Client
from sqlalchemy import select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.models import Order, OrderStatus
from openstall_api.seed import DEMO_ORDER_ID, DEMO_REQUEST, seed, seed_demo_order
from openstall_api.storefront import storefront

TODAY = date(2026, 11, 10)
DEADLINE = (TODAY + timedelta(days=30)).isoformat()
STORY = {
    "items": [DEMO_REQUEST],
    "quantity": 40,
    "max_unit_price": 30,
    "deadline": DEADLINE,
    "ship_to": "Chicago",
}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def call(name: str, arguments: dict, target=storefront):
    async def go():
        async with Client(target) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(go())


def ok(name: str, arguments: dict, target=storefront) -> dict:
    result = call(name, arguments, target)
    assert not result.is_error, result.content
    return result.structured_content


def refusal(name: str, arguments: dict) -> str:
    """What the tool said when it refused, without the SDK's "Error executing tool ...: " in front."""
    result = call(name, arguments)
    assert result.is_error
    return result.content[0].text.removeprefix(f"Error executing tool {name}: ")


def tools(target=storefront) -> dict:
    async def go():
        async with Client(target) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    return asyncio.run(go())


def test_request_quote_gives_every_valid_offer_the_plan_and_its_explanation(seeded):
    quote = ok("request_quote", STORY)

    assert (quote["rounds"], quote["makers_asked"]) == (1, 5)
    assert [(o["seller_name"], o["unit_price"], o["quantity"]) for o in quote["offers"]] == [
        ("Priya", "16.00", 11),
        ("Amina", "18.00", 12),
        ("Lucía", "22.00", 10),
        ("Grace", "29.00", 11),
        ("Noor", "29.50", 10),
    ]
    assert {o["delivery_date"] for o in quote["offers"]} == {DEADLINE}
    assert all(0 < o["trust_score"] <= 1 for o in quote["offers"])
    assert quote["offers"][3]["message"] == "Grace can make 11 by December 10 at $29.00 each."
    plan = quote["plan"]
    assert [(line["seller_name"], line["quantity"]) for line in plan["lines"]] == [
        ("Priya", 11),
        ("Amina", 12),
        ("Lucía", 10),
        ("Grace", 7),
    ]
    assert (plan["total_cost"], plan["complete"]) == ("815.00", True)
    assert "the 40 units go to them in that order: 11, 12, 10 and 7" in plan["explanation"]
    assert quote["next_step"] == f"Call create_collective_order with request_id {quote['request_id']!r} to draft the order."


def test_create_collective_order_drafts_the_plan_with_the_servers_numbers_once(seeded):
    request_id = ok("request_quote", STORY)["request_id"]

    draft = ok("create_collective_order", {"request_id": request_id})

    assert (draft["request_id"], draft["status"], draft["total_usd"], draft["units"]) == (
        request_id,
        "draft",
        "815.00",
        40,
    )
    assert [(s["seller_name"], s["quantity"], s["unit_price"], s["line_total"]) for s in draft["shares"]] == [
        ("Priya", 11, "16.00", "176.00"),
        ("Amina", 12, "18.00", "216.00"),
        ("Lucía", 10, "22.00", "220.00"),
        ("Grace", 7, "29.00", "203.00"),
    ]
    assert "A person must approve this draft on OpenStall before any money is reserved" in draft["next_step"]
    order = seeded.get(Order, draft["order_id"])
    assert (order.status, order.request_id) == (OrderStatus.DRAFT, request_id)
    # Each share is for the listing her offer was for.
    assert all(part.product_id for part in order.parts)
    # Asked again, the same draft.
    assert ok("create_collective_order", {"request_id": request_id})["order_id"] == draft["order_id"]
    assert len(seeded.scalars(select(Order).where(Order.request_id == request_id)).all()) == 1


def test_a_short_plan_is_drafted_only_when_the_agent_accepts_part(seeded):
    # The story's draft order, reserved: its shares use up Amina, Priya and Lucía, and most of Grace.
    from fastapi.testclient import TestClient

    from openstall_api.main import app

    client = TestClient(app)
    seed_demo_order(seeded, TODAY)
    seeded.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    quote = ok("request_quote", STORY)
    assert quote["plan"]["complete"] is False
    assert quote["next_step"].endswith("with accept_partial true to order only what is possible.")

    assert refusal("create_collective_order", {"request_id": quote["request_id"]}) == (
        "The plan covers only 14 of the 40 units. Call again with accept_partial true to order those 14, or ask "
        "for a new quote."
    )
    draft = ok("create_collective_order", {"request_id": quote["request_id"], "accept_partial": True})
    assert (draft["units"], draft["total_usd"]) == (14, "411.00")


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"deadline": TODAY.isoformat()}, "The deadline 2026-11-10 must be after today, 2026-11-10 (UTC)."),
        ({"deadline": "2026-11-01"}, "The deadline 2026-11-01 must be after today, 2026-11-10 (UTC)."),
        ({"quantity": 0}, "quantity"),
        ({"max_unit_price": 0}, "max_unit_price"),
        ({"items": []}, "items"),
    ],
)
def test_request_quote_refuses_what_cannot_be_quoted_in_words(seeded, change, words):
    assert words in refusal("request_quote", {**STORY, **change})


def test_create_collective_order_says_when_there_is_nothing_to_draft(seeded):
    assert refusal("create_collective_order", {"request_id": "q_nobody"}) == (
        "There is no quote request called 'q_nobody'. request_quote gives each request's id."
    )
    nobody = ok("request_quote", {**STORY, "items": ["ceramic mugs"]})
    assert refusal("create_collective_order", {"request_id": nobody["request_id"], "accept_partial": True}) == (
        "No maker can supply any of the 40 units by December 10, 2026, so there is nothing to order. Ask for a new "
        "quote with a later deadline or a higher maximum price."
    )


def test_no_tool_takes_a_price_or_a_total_from_an_agent(seeded):
    listed = tools()

    assert set(listed["create_collective_order"].input_schema["properties"]) == {"request_id", "accept_partial"}
    assert set(listed["request_quote"].input_schema["properties"]) == {
        "items",
        "quantity",
        "max_unit_price",
        "deadline",
        "ship_to",
    }
    for tool in listed.values():
        assert not {name for name in tool.input_schema["properties"] if "total" in name}, tool.name


def test_both_tools_say_they_spend_no_money_and_how_they_change_things(seeded):
    listed = tools()

    quote, draft = listed["request_quote"], listed["create_collective_order"]
    assert "It spends no money" in quote.description
    assert "It spends no money" in draft.description
    assert (quote.annotations.read_only_hint, quote.annotations.destructive_hint) == (False, False)
    assert quote.annotations.idempotent_hint is False
    assert (draft.annotations.read_only_hint, draft.annotations.destructive_hint) == (False, False)
    assert draft.annotations.idempotent_hint is True


def test_a_buyer_agent_can_quote_and_draft_over_http(seeded, server_url):
    request_id = ok("request_quote", STORY, server_url)["request_id"]

    draft = ok("create_collective_order", {"request_id": request_id}, server_url)

    assert (draft["total_usd"], draft["units"]) == ("815.00", 40)
