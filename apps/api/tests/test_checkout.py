"""Checkout (spec 3.5): Approve sends the human to PayPal for the whole order, once, and only from the right status.
In fake mode the simulated PayPal page stands in for PayPal."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderStatus
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_paypal import PaymentError, PaymentUnavailable

client = TestClient(app)
WEB = "http://localhost:3000"


@pytest.fixture
def demo_order(db):
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return db


def checkout(order_id: str = DEMO_ORDER_ID):
    return client.post(f"/api/orders/{order_id}/checkout")


def checkout_events(db) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == EventType.ORDER_CHECKOUT_STARTED)))


def test_approve_creates_one_paypal_order_for_the_whole_total(demo_order, fakes):
    response = checkout()

    assert response.status_code == 200
    body = response.json()
    assert body["paypal_order_id"].startswith("FAKE-")
    assert body["approval_url"] == f"{WEB}/fake-paypal?token={body['paypal_order_id']}"
    [(call, request)] = fakes.payment_gateway.calls
    assert call == "create_checkout"
    assert request.total_usd == Decimal("815.00")
    assert [(part.reference_id, part.amount_usd, part.description) for part in request.parts] == [
        ("op_001", Decimal("216.00"), "12 × Hand-embroidered cushion cover, Amina"),
        ("op_002", Decimal("176.00"), "11 × Mirror-work embroidered cushion cover, Priya"),
        ("op_003", Decimal("220.00"), "10 × Oaxacan embroidered cushion cover, Lucía"),
        ("op_004", Decimal("203.00"), "7 × Hand-embroidered linen cushion cover, Grace"),
    ]
    assert request.return_url == f"{WEB}/approve/{DEMO_ORDER_ID}/return"
    assert request.cancel_url == f"{WEB}/approve/{DEMO_ORDER_ID}?cancelled=1"


def test_the_order_waits_for_approval_with_its_paypal_order_and_an_event(demo_order):
    paypal_order_id = checkout().json()["paypal_order_id"]

    demo_order.expire_all()
    order = demo_order.get(Order, DEMO_ORDER_ID)
    assert order.status == OrderStatus.AWAITING_APPROVAL
    assert order.paypal_order_id == paypal_order_id
    [event] = checkout_events(demo_order)
    assert event.entity_id == DEMO_ORDER_ID
    assert event.payload_json["summary"] == "Order ord_demo went to PayPal: $815.00 to reserve for 4 makers"


def test_pressing_approve_twice_reuses_the_same_paypal_order(demo_order):
    first = checkout().json()
    second = checkout().json()

    assert second == first
    assert len(checkout_events(demo_order)) == 1


def test_an_order_already_approved_at_paypal_goes_straight_to_the_return_page(demo_order, fakes):
    paypal_order_id = checkout().json()["paypal_order_id"]
    fakes.payment_gateway.approve(paypal_order_id)

    again = checkout().json()

    assert again == {"paypal_order_id": paypal_order_id, "approval_url": f"{WEB}/approve/{DEMO_ORDER_ID}/return"}


@pytest.mark.parametrize("status", [OrderStatus.AUTHORIZED, OrderStatus.SHIPPED, OrderStatus.CANCELLED])
def test_an_order_past_approval_is_refused(demo_order, fakes, status):
    demo_order.get(Order, DEMO_ORDER_ID).status = status
    demo_order.commit()

    response = checkout()

    assert response.status_code == 409
    assert "cannot go to PayPal again" in response.json()["detail"]
    assert fakes.payment_gateway.calls == []


def test_an_unknown_order_is_not_found(db):
    response = checkout("ord_nobody")

    assert response.status_code == 404
    assert response.json()["detail"] == "There is no order called 'ord_nobody'."


def test_when_paypal_does_not_answer_nothing_changes(demo_order, fakes, monkeypatch):
    def no_answer(request):
        raise PaymentUnavailable("PAYPAL_UNAVAILABLE", "timed out")

    monkeypatch.setattr(fakes.payment_gateway, "create_checkout", no_answer)

    response = checkout()

    assert response.status_code == 503
    assert response.json()["detail"].startswith("PayPal did not answer")
    demo_order.expire_all()
    assert demo_order.get(Order, DEMO_ORDER_ID).status == OrderStatus.DRAFT


def test_a_paypal_refusal_names_paypals_issue(demo_order, fakes, monkeypatch):
    def refused(request):
        raise PaymentError("PAYEE_MISSING", "no PayPal account is linked for Grace")

    monkeypatch.setattr(fakes.payment_gateway, "create_checkout", refused)

    response = checkout()

    assert response.status_code == 502
    assert "PAYEE_MISSING" in response.json()["detail"]


def test_sandbox_mode_without_paypal_keys_says_which_keys(demo_order, use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    response = checkout()

    assert response.status_code == 503
    assert "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET" in response.json()["detail"]


# The simulated PayPal page (fake mode only).


def test_the_simulated_page_shows_what_the_buyer_approves(demo_order):
    token = checkout().json()["paypal_order_id"]

    response = client.get(f"/api/dev/fake-paypal/{token}")

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == DEMO_ORDER_ID
    assert body["status"] == "PAYER_ACTION_REQUIRED"
    assert body["total_usd"] == "815.00"
    assert [share["amount_usd"] for share in body["shares"]] == ["216.00", "176.00", "220.00", "203.00"]
    assert body["cancel_url"] == f"{WEB}/approve/{DEMO_ORDER_ID}?cancelled=1"


def test_approving_on_the_simulated_page_returns_like_paypal_does(demo_order, fakes):
    token = checkout().json()["paypal_order_id"]

    response = client.post(f"/api/dev/fake-paypal/{token}/approve")

    assert response.json() == {
        "redirect_url": f"{WEB}/approve/{DEMO_ORDER_ID}/return?token={token}&PayerID=FAKEBUYER01"
    }
    assert fakes.payment_gateway.view(token).status == "APPROVED"


def test_an_unknown_simulated_checkout_explains_what_to_do(db):
    response = client.get("/api/dev/fake-paypal/FAKE-0000")

    assert response.status_code == 404
    assert "press Approve again" in response.json()["detail"]


def test_the_simulated_page_does_not_exist_in_sandbox_mode(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.get("/api/dev/fake-paypal/FAKE-0000").status_code == 404
    assert client.post("/api/dev/fake-paypal/FAKE-0000/approve").status_code == 404


def test_ui_tests_can_make_a_fresh_copy_of_the_story_order(demo_order):
    first = client.post("/api/dev/story-orders")
    second = client.post("/api/dev/story-orders")

    assert first.status_code == second.status_code == 201
    order_id = first.json()["order_id"]
    assert order_id != second.json()["order_id"] and order_id != DEMO_ORDER_ID
    order = client.get(f"/api/orders/{order_id}").json()
    assert order["status"] == "draft"
    assert order["total_usd"] == "815.00"
    assert [part["quantity"] for part in order["parts"]] == [12, 11, 10, 7]


def test_fresh_story_orders_are_not_made_in_sandbox_mode(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.post("/api/dev/story-orders").status_code == 404
