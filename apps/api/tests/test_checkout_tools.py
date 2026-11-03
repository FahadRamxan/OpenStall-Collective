"""MCP checkout and get_order_status (prompt 28): an agent gets OpenStall's approval link for its human and follows
the order, but changes nothing: approving, reserving and paying happen only on the approval page and on proof."""

import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderStatus
from openstall_api.seed import DEMO_ORDER_ID, DEMO_REQUEST, seed, seed_demo_order
from openstall_api.storefront import storefront

client = TestClient(app)

TODAY = date(2026, 11, 10)
STORY = {
    "items": [DEMO_REQUEST],
    "quantity": 40,
    "max_unit_price": 30,
    "deadline": (TODAY + timedelta(days=30)).isoformat(),
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


def call(name: str, arguments: dict):
    async def go():
        async with Client(storefront) as mcp:
            return await mcp.call_tool(name, arguments)

    return asyncio.run(go())


def ok(name: str, arguments: dict) -> dict:
    result = call(name, arguments)
    assert not result.is_error, result.content
    return result.structured_content


def drafted_by_an_agent() -> str:
    request_id = ok("request_quote", STORY)["request_id"]
    return ok("create_collective_order", {"request_id": request_id})["order_id"]


def link_events(db, order_id: str) -> list[Event]:
    query = select(Event).where(Event.type == EventType.CHECKOUT_LINK_ISSUED.value, Event.entity_id == order_id)
    return list(db.scalars(query))


def test_checkout_gives_openstalls_approval_page_and_leaves_the_order_unpaid(seeded):
    order_id = drafted_by_an_agent()

    link = ok("checkout", {"order_id": order_id})

    assert link["approval_url"] == f"http://localhost:3000/approve/{order_id}"
    assert "paypal" not in link["approval_url"].lower()
    assert (link["status"], link["total_usd"]) == ("draft", "815.00")
    assert link["next_step"].startswith("Send this link to your human.")
    seeded.expire_all()
    order = seeded.get(Order, order_id)
    assert (order.status, order.paypal_order_id, order.approved_at) == (OrderStatus.DRAFT, None, None)
    [issued] = link_events(seeded, order_id)
    assert issued.payload_json["summary"] == f"Approval link for order {order_id} sent to the human"


def test_asking_for_the_link_again_gives_the_same_link_and_records_nothing_more(seeded):
    order_id = drafted_by_an_agent()

    first = ok("checkout", {"order_id": order_id})["approval_url"]
    second = ok("checkout", {"order_id": order_id})["approval_url"]

    assert first == second
    assert len(link_events(seeded, order_id)) == 1


def test_the_order_says_an_agent_asked_for_it_and_when_its_link_was_sent(seeded):
    order_id = drafted_by_an_agent()
    before = client.get(f"/api/orders/{order_id}").json()
    assert (before["requested_by_agent"], before["approval_link"]) == (True, None)

    ok("checkout", {"order_id": order_id})

    after = client.get(f"/api/orders/{order_id}").json()
    assert after["approval_link"]["url"] == f"http://localhost:3000/approve/{order_id}"
    assert after["approval_link"]["issued_at"]
    # The seeded story order came from no agent.
    seed_demo_order(seeded, TODAY)
    seeded.commit()
    assert client.get(f"/api/orders/{DEMO_ORDER_ID}").json()["requested_by_agent"] is False


def test_order_status_follows_the_order_from_draft_to_reserved_to_paid_on_proof(seeded):
    order_id = drafted_by_an_agent()

    draft = ok("get_order_status", {"order_id": order_id})
    assert (draft["status"], draft["approved"], draft["simulated"]) == ("draft", False, True)
    assert draft["status_words"] == "Draft: waiting for a person to approve it. Nothing is reserved."
    assert {share["status"] for share in draft["shares"]} == {"pending"}

    # The person approves at the simulated PayPal page, and the order is reserved.
    token = client.post(f"/api/orders/{order_id}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{order_id}/reserve").status_code == 200
    reserved = ok("get_order_status", {"order_id": order_id})
    assert (reserved["status"], reserved["approved"]) == ("authorized", True)
    assert {share["status"] for share in reserved["shares"]} == {"authorized"}
    priya = next(share for share in reserved["shares"] if share["seller_name"] == "Priya")
    assert priya["status_words"] == "Reserved at PayPal: paid when she proves she shipped."
    assert (priya["payout_rail"], priya["paid_through_paypal"]) == ("paypal", True)
    assert priya["payout_words"] == "Paid to PayPal when she ships (simulated)"

    # Priya proves she shipped (simulated tracking), and her share is paid.
    part_id = seeded.get(Order, order_id).parts[0].id
    assert client.post(f"/api/dev/parts/{part_id}/proof").status_code == 200
    shipped = ok("get_order_status", {"order_id": order_id})
    paid = next(share for share in shipped["shares"] if share["status"] == "captured")
    assert (paid["carrier"], paid["tracking_number"]) == ("OTHER", f"SIMULATED-{part_id}")
    assert paid["status_words"] == "Paid: she proved she shipped."
    assert shipped["status"] == "partly_shipped"


def test_an_unknown_order_is_refused_in_words(seeded):
    for tool in ("checkout", "get_order_status"):
        result = call(tool, {"order_id": "ord_nobody"})
        assert result.is_error
        assert result.content[0].text.endswith(
            "There is no order called 'ord_nobody'. create_collective_order gives each order's id."
        )


def test_the_tools_say_they_spend_nothing_and_get_order_status_only_reads(seeded):
    async def go():
        async with Client(storefront) as mcp:
            return {tool.name: tool for tool in (await mcp.list_tools()).tools}

    tools = asyncio.run(go())

    assert "It spends no money" in tools["checkout"].description
    assert tools["checkout"].annotations.idempotent_hint is True
    assert tools["get_order_status"].annotations.read_only_hint is True
    instructions = asyncio.run(_instructions())
    assert "No tool approves, captures, refunds or pays out" in instructions


async def _instructions() -> str:
    async with Client(storefront) as mcp:
        return mcp.instructions or ""
