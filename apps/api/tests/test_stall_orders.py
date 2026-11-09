"""Buying from a maker's stall (prompt 42): a person's purchase of one listing is drafted at her list price, with the
first delivery date she can make; it goes through the same checkout and reserve as any order, and the maker is told
where it ships. The page learns how to show PayPal from GET /api/paypal/config, which never gives the secret."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, Direction, Event, Order, OrderStatus, PartStatus
from openstall_api.seed import seed

client = TestClient(app)
TODAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def makers(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def buy(product_id: str = "p_priya_cushion", quantity: int = 2, ship_to: str = "Chicago"):
    return client.post("/api/stall-orders", json={"product_id": product_id, "quantity": quantity, "ship_to": ship_to})


def test_a_purchase_is_drafted_at_her_list_price_with_the_first_day_she_can_deliver(makers):
    response = buy()

    assert response.status_code == 201, response.text
    order = response.json()
    [share] = order["parts"]
    assert (share["seller"]["name"], share["quantity"], share["unit_price_usd"]) == ("Priya", 2, "16.00")
    assert order["total_usd"] == "32.00" and order["status"] == "draft"
    # 4 a week and 10 days in the post: 2 can arrive in 14 days (13 leave her 3 days to make them: only 1).
    assert share["delivery_date"] == "2026-11-24" and share["ship_by"] == "2026-11-14"
    assert order["request"] is None and order["requested_by_agent"] is False
    makers.expire_all()
    stored = makers.get(Order, order["id"])
    assert (stored.source, stored.ship_to) == ("stall", "Chicago")


def test_it_is_approved_and_reserved_like_any_order_and_she_is_told_where_it_ships(makers, fakes):
    order_id = buy(ship_to="  Austin  ").json()["id"]

    token = client.post(f"/api/orders/{order_id}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    reserved = client.post(f"/api/orders/{order_id}/reserve")

    assert reserved.status_code == 200
    assert reserved.json()["status"] == "authorized"
    makers.expire_all()
    [share] = makers.get(Order, order_id).parts
    assert share.status == PartStatus.AUTHORIZED
    told = makers.scalars(
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(ChatSession.seller_id == "s_priya", ChatMessage.direction == Direction.OUTBOUND)
    ).all()
    assert any(order_id in (message.text or "") and "Austin" in (message.text or "") for message in told)
    assert makers.scalar(
        select(Event.id).where(Event.type == EventType.ORDER_NOTICE_SENT.value, Event.entity_id == share.id)
    )
    assert makers.get(Order, order_id).status == OrderStatus.AUTHORIZED


def test_her_committed_units_push_the_date_out(makers):
    first = buy(quantity=2).json()["parts"][0]["delivery_date"]
    order_id = buy(quantity=2).json()["id"]
    token = client.post(f"/api/orders/{order_id}/checkout").json()["paypal_order_id"]
    client.post(f"/api/dev/fake-paypal/{token}/approve")
    client.post(f"/api/orders/{order_id}/reserve")  # 2 units she now owes

    later = buy(quantity=2).json()["parts"][0]["delivery_date"]

    assert first == "2026-11-24" and later == "2026-11-27"  # 4 to make: 7 days of work, then 10 in the post


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        (
            {"product_id": "p_nope", "quantity": 1, "ship_to": "Chicago"},
            409,
            "There is no listing for sale called 'p_nope'.",
        ),
        ({"product_id": "p_priya_cushion", "quantity": 1, "ship_to": "   "}, 409, "Say which city it ships to."),
        ({"product_id": "p_priya_cushion", "quantity": 0, "ship_to": "Chicago"}, 422, None),
        ({"product_id": "p_priya_cushion", "quantity": 51, "ship_to": "Chicago"}, 422, None),
    ],
)
def test_what_a_stall_refuses(makers, body, status, detail):
    response = client.post("/api/stall-orders", json=body)

    assert response.status_code == status
    if detail:
        assert response.json()["detail"] == detail


def test_the_demo_follows_collective_orders_not_stall_purchases(makers):
    order_id = buy().json()["id"]

    assert client.get("/api/orders?limit=1").json()[0]["id"] == order_id
    assert client.get("/api/orders?limit=1&stall=false").json() == []
    assert client.get("/api/dashboard").json()["orders"][0]["from_stall"] is True


def test_the_page_learns_how_to_show_paypal_and_never_the_secret(db, use_settings):
    assert client.get("/api/paypal/config").json() == {
        "mode": "fake",
        "client_id": None,
        "currency": "USD",
        "intent": "authorize",
        "venmo": True,
        "pay_later": False,
        "buyer_country": None,
    }

    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_CLIENT_ID="made-up-client-id", PAYPAL_CLIENT_SECRET="made-up-secret")
    sandbox = client.get("/api/paypal/config")

    assert sandbox.json()["mode"] == "sandbox" and sandbox.json()["client_id"] == "made-up-client-id"
    assert "made-up-secret" not in sandbox.text
    # PayPal's sandbox shows Venmo only to a buyer it takes to be in the US; Pay Later waits until it is proven.
    assert (sandbox.json()["venmo"], sandbox.json()["pay_later"], sandbox.json()["buyer_country"]) == (True, False, "US")


def test_venmo_and_pay_later_follow_their_settings_and_the_live_host_gets_no_buyer_country(db, use_settings):
    use_settings(
        OPENSTALL_MODE="sandbox",
        PAYPAL_CLIENT_ID="made-up-client-id",
        PAYPAL_CLIENT_SECRET="made-up-secret",
        PAYPAL_API_BASE="https://api-m.paypal.com",
        PAYPAL_VENMO="false",
        PAYPAL_PAY_LATER="true",
    )
    config = client.get("/api/paypal/config").json()

    assert (config["venmo"], config["pay_later"], config["buyer_country"]) == (False, True, None)
