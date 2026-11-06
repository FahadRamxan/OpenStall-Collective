"""Pay-on-proof after approval (spec 3.5): the order is reserved exactly once when the human comes back from PayPal,
then each share is paid on proof of shipping or released, once, and never both."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, OrderStatus, PartStatus, PayoutRailChoice, Seller
from openstall_api.payments import WrongStatus, pay_share, release_share, reserve_order
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_paypal import PaymentError, PaymentUnavailable

client = TestClient(app)


@pytest.fixture
def demo_order(db):
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return db


def send_to_paypal() -> str:
    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout")
    assert response.status_code == 200
    return response.json()["paypal_order_id"]


@pytest.fixture
def approved(demo_order, fakes) -> str:
    """The demo order, approved by the buyer on the simulated PayPal page. Returns the PayPal order id."""
    paypal_order_id = send_to_paypal()
    fakes.payment_gateway.approve(paypal_order_id)
    fakes.payment_gateway.calls.clear()
    return paypal_order_id


def reserve():
    return client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve")


def events(db, kind: EventType) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == kind).order_by(Event.id)))


def calls(fakes) -> list[str]:
    return [name for name, _ in fakes.payment_gateway.calls]


def test_coming_back_from_paypal_reserves_the_whole_order(approved, demo_order):
    response = reserve()

    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "authorized"
    assert order["approved_at"] is not None
    assert order["paypal_order_id"] == approved
    assert [part["status"] for part in order["parts"]] == ["authorized"] * 4
    demo_order.expire_all()
    parts = demo_order.get(Order, DEMO_ORDER_ID).parts
    # The payouts path: one authorization holds every share.
    assert {part.reference_id: part.authorization_id for part in parts} == {
        f"op_00{n}": f"{approved}-AUTH" for n in range(1, 5)
    }


def test_reserving_records_the_order_and_each_makers_share(approved, demo_order):
    reserve()

    [authorized] = events(demo_order, EventType.ORDER_AUTHORIZED)
    assert authorized.payload_json["summary"] == (
        "PayPal reserved $815.00 for order ord_demo. Nothing is taken until each maker ships"
    )
    reserved = [event.payload_json["summary"] for event in events(demo_order, EventType.PART_RESERVED)]
    assert reserved == [
        "Amina's share is reserved: $216.00, paid when she ships",
        "Priya's share is reserved: $176.00, paid when she ships",
        "Lucía's share is reserved: $220.00, paid when she ships",
        "Grace's share is reserved: $203.00, paid when she ships",
    ]


def without_confirmations(order: dict) -> dict:
    """The order without PayPal's confirmations, which its webhooks add just after the first reserve call, nor the
    makers' notices, which are sent just after it too (prompt 31)."""
    return {
        **order,
        "parts": [{**part, "confirmed_by_paypal": None, "notice": None} for part in order["parts"]],
    }


def test_paypal_is_read_first_and_the_order_is_reserved_only_once(approved, demo_order, fakes):
    first = reserve().json()
    second = reserve().json()

    assert without_confirmations(second) == without_confirmations(first)
    assert calls(fakes) == ["get_order", "reserve"]
    assert len(events(demo_order, EventType.ORDER_AUTHORIZED)) == 1


def test_an_order_the_buyer_has_not_approved_is_not_reserved(demo_order, fakes):
    send_to_paypal()
    fakes.payment_gateway.calls.clear()

    response = reserve()

    assert response.status_code == 409
    assert response.json()["detail"].startswith("PayPal does not have your approval for this order yet.")
    assert calls(fakes) == ["get_order"]


def test_a_draft_never_sent_to_paypal_has_nothing_to_reserve(demo_order, fakes):
    response = reserve()

    assert response.status_code == 409
    assert response.json()["detail"] == "Order ord_demo is a draft, so there is nothing to reserve."
    assert fakes.payment_gateway.calls == []


def test_when_paypal_reserved_but_the_answer_was_lost_the_order_is_read_back_not_reserved_again(
    approved, demo_order, fakes, monkeypatch
):
    gateway = fakes.payment_gateway
    real_reserve = gateway.reserve

    def reserved_then_lost(paypal_order_id):
        real_reserve(paypal_order_id)
        raise PaymentUnavailable("PAYPAL_UNAVAILABLE", "the connection dropped")

    monkeypatch.setattr(gateway, "reserve", reserved_then_lost)

    response = reserve()

    assert response.status_code == 200
    assert response.json()["status"] == "authorized"
    assert calls(fakes) == ["get_order", "reserve", "get_order"]


def test_when_paypal_did_not_reserve_and_did_not_answer_nothing_changes(approved, demo_order, fakes, monkeypatch):
    def no_answer(paypal_order_id):
        raise PaymentUnavailable("PAYPAL_UNAVAILABLE", "timed out")

    monkeypatch.setattr(fakes.payment_gateway, "reserve", no_answer)

    response = reserve()

    assert response.status_code == 503
    assert response.json()["detail"].startswith("PayPal did not answer")
    demo_order.expire_all()
    assert demo_order.get(Order, DEMO_ORDER_ID).status == OrderStatus.AWAITING_APPROVAL


def test_a_declined_payment_method_says_what_to_do(approved, fakes, monkeypatch):
    def declined(paypal_order_id):
        raise PaymentError("INSTRUMENT_DECLINED", "The instrument presented was declined")

    monkeypatch.setattr(fakes.payment_gateway, "reserve", declined)

    response = reserve()

    assert response.status_code == 409
    assert response.json()["detail"].startswith("PayPal declined the way you chose to pay. Nothing was reserved.")


def test_an_approval_paypal_voided_is_explained(approved, fakes, monkeypatch):
    from openstall_paypal import OrderState

    monkeypatch.setattr(fakes.payment_gateway, "get_order", lambda paypal_order_id: OrderState("VOIDED", {}))

    response = reserve()

    assert response.status_code == 409
    assert "no longer valid (voided)" in response.json()["detail"]


def test_an_unknown_order_is_not_found(db):
    assert client.post("/api/orders/ord_nobody/reserve").status_code == 404


# Paying and releasing each share (called by later steps: the receipt photo, and the order healing itself).


@pytest.fixture
def reserved(approved, demo_order, fakes):
    """The reserved demo order's shares, by seller."""
    reserve()
    fakes.payment_gateway.calls.clear()
    demo_order.expire_all()
    return {part.seller_id: part.id for part in demo_order.get(Order, DEMO_ORDER_ID).parts}


def part(db, part_id: str) -> OrderPart:
    db.expire_all()
    return db.get(OrderPart, part_id)


def pay(db, fakes, part_id: str) -> None:
    pay_share(db, part_id, fakes.payment_gateway)
    db.commit()  # as the endpoints do: the services leave committing to their caller


def release(db, fakes, part_id: str) -> None:
    release_share(db, part_id, fakes.payment_gateway)
    db.commit()


def confirm_tracking(db, part_id: str) -> None:
    part(db, part_id).tracking_number = "LP00123456789PK"
    db.commit()


def test_a_share_is_never_paid_before_her_tracking_is_confirmed(reserved, demo_order, fakes):
    with pytest.raises(WrongStatus, match="paid when her tracking is confirmed"):
        pay_share(demo_order, reserved["s_amina"], fakes.payment_gateway)

    assert fakes.payment_gateway.calls == []


def test_a_share_with_confirmed_tracking_is_paid_once(reserved, demo_order, fakes):
    priya = reserved["s_priya"]
    confirm_tracking(demo_order, priya)

    pay(demo_order, fakes, priya)
    pay(demo_order, fakes, priya)

    paid = part(demo_order, priya)
    assert paid.status == PartStatus.CAPTURED
    assert paid.capture_id == f"{paid.authorization_id}-CAP-1"  # a partial capture of the order's one hold
    assert calls(fakes) == ["pay_share"]
    [event] = events(demo_order, EventType.PART_CAPTURED)
    assert event.payload_json["summary"] == "Priya was paid $176.00 on proof of shipping"
    assert event.payload_json["payout_rail"] == "paypal"


def test_amina_is_captured_and_paid_to_her_bank_through_hyperwallet_simulated(reserved, demo_order, fakes):
    amina = reserved["s_amina"]  # Lahore: PayPal cannot pay out to Pakistan; Hyperwallet can (simulated)
    confirm_tracking(demo_order, amina)

    pay(demo_order, fakes, amina)

    assert part(demo_order, amina).status == PartStatus.CAPTURED
    [event] = events(demo_order, EventType.PART_CAPTURED)
    assert event.payload_json["summary"] == (
        "Amina was paid $216.00 on proof of shipping, to her bank through Hyperwallet (simulated)"
    )
    assert (event.payload_json["payout_rail"], event.payload_json["payout_simulated"]) == ("hyperwallet", True)


def test_a_maker_no_payout_rail_can_reach_is_never_captured(reserved, demo_order, fakes):
    amina = reserved["s_amina"]
    demo_order.get(Seller, "s_amina").payout_rail = PayoutRailChoice.PAYPAL  # PayPal Payouts cannot reach Pakistan
    demo_order.commit()
    confirm_tracking(demo_order, amina)

    with pytest.raises(WrongStatus, match=r"Amina's share stays reserved and is not captured. Payout rail not connected yet \(Pakistan\)"):
        pay(demo_order, fakes, amina)

    assert fakes.payment_gateway.calls == []
    assert part(demo_order, amina).status == PartStatus.AUTHORIZED


def test_grace_is_paid_on_the_venmo_rail(reserved, demo_order, fakes):
    grace = reserved["s_grace"]
    confirm_tracking(demo_order, grace)

    pay(demo_order, fakes, grace)

    [(_, share)] = fakes.payment_gateway.calls
    assert (share.payout_rail, share.venmo_handle) == ("venmo", "grace-detroit-demo")
    [event] = events(demo_order, EventType.PART_CAPTURED)
    assert event.payload_json["payout_rail"] == "venmo"


def test_paying_one_share_leaves_the_order_partly_shipped(reserved, demo_order, fakes):
    confirm_tracking(demo_order, reserved["s_priya"])

    pay(demo_order, fakes, reserved["s_priya"])

    assert part(demo_order, reserved["s_priya"]).order.status == OrderStatus.PARTLY_SHIPPED


def test_a_released_share_is_released_once_and_never_paid(reserved, demo_order, fakes):
    lucia = reserved["s_lucia"]

    release(demo_order, fakes, lucia)
    release(demo_order, fakes, lucia)
    confirm_tracking(demo_order, lucia)

    with pytest.raises(WrongStatus, match="Lucía's share is released, so it cannot be paid"):
        pay(demo_order, fakes, lucia)
    assert part(demo_order, lucia).status == PartStatus.RELEASED
    assert calls(fakes) == ["release_share"]
    [event] = events(demo_order, EventType.PART_RELEASED)
    assert event.payload_json["summary"] == "Lucía's share of $220.00 was released back to the buyer"


def test_a_paid_share_is_never_released(reserved, demo_order, fakes):
    grace = reserved["s_grace"]
    confirm_tracking(demo_order, grace)
    pay(demo_order, fakes, grace)

    with pytest.raises(WrongStatus, match="already paid, so it cannot be released"):
        release(demo_order, fakes, grace)

    assert calls(fakes) == ["pay_share"]


def test_only_the_last_open_share_may_close_the_hold(reserved, demo_order, fakes):
    for seller in ("s_amina", "s_priya", "s_lucia"):
        release(demo_order, fakes, reserved[seller])
    confirm_tracking(demo_order, reserved["s_grace"])
    pay(demo_order, fakes, reserved["s_grace"])

    lasts = [share.last for _, share in fakes.payment_gateway.calls]
    assert lasts == [False, False, False, True]


def test_the_order_is_shipped_once_no_share_waits(reserved, demo_order, fakes):
    release(demo_order, fakes, reserved["s_amina"])
    for seller in ("s_priya", "s_lucia", "s_grace"):
        confirm_tracking(demo_order, reserved[seller])
        pay(demo_order, fakes, reserved[seller])

    assert part(demo_order, reserved["s_lucia"]).order.status == OrderStatus.SHIPPED


def test_an_order_whose_every_share_was_released_is_cancelled(reserved, demo_order, fakes):
    for part_id in reserved.values():
        release(demo_order, fakes, part_id)

    assert part(demo_order, reserved["s_amina"]).order.status == OrderStatus.CANCELLED


def test_a_share_of_an_order_never_reserved_is_released_without_paypal(demo_order, fakes):
    amina = next(p.id for p in demo_order.get(Order, DEMO_ORDER_ID).parts if p.seller_id == "s_amina")

    release(demo_order, fakes, amina)

    assert part(demo_order, amina).status == PartStatus.RELEASED
    assert fakes.payment_gateway.calls == []


def test_reserve_order_is_the_same_function_the_endpoint_uses(approved, demo_order, fakes):
    order = reserve_order(demo_order, DEMO_ORDER_ID, fakes.payment_gateway)

    assert order.status == OrderStatus.AUTHORIZED
