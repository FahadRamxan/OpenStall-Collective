"""Draft orders (spec 3.5, section 4): server-side totals, numbered shares, the status rules, and the order API."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from openstall_api.main import app
from openstall_api.models import Event, Order, OrderPart, OrderStatus, PartStatus
from openstall_api.orders import (
    ORDER_MOVES,
    PART_MOVES,
    DraftPart,
    IllegalMove,
    create_draft_order,
    move_order,
    move_part,
    server_total,
)
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

DUE = date(2026, 12, 10)


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def part(seller_id: str, quantity: int, price, product_id: str | None = None) -> DraftPart:
    return DraftPart(seller_id, product_id, quantity, price, DUE)


# ---------- totals and shares ----------


def test_the_total_is_worked_out_on_the_server_exactly(seeded):
    order = create_draft_order(seeded, [part("s_amina", 7, "29.99"), part("s_priya", 3, Decimal("0.10"))])
    seeded.commit()

    # 7 x 29.99 is 209.92999999999998 in floating point; in cents it is exactly 209.93.
    assert [p.amount_usd for p in order.parts] == [Decimal("209.93"), Decimal("0.30")]
    assert order.total_usd == Decimal("210.23") == server_total(order)


def test_shares_are_numbered_in_order_and_start_pending(seeded):
    order = create_draft_order(seeded, [part("s_amina", 12, "18.00"), part("s_priya", 11, "16.00")])

    assert [p.reference_id for p in order.parts] == ["op_001", "op_002"]
    assert {p.status for p in order.parts} == {PartStatus.PENDING}
    assert order.status is OrderStatus.DRAFT


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        ([part("s_amina", 1, "28.995")], "whole cents"),
        ([part("s_amina", 1, "-1.00")], "not negative"),
        ([part("s_amina", 0, "18.00")], "at least 1"),
        ([part("s_amina", True, "18.00")], "at least 1"),
        ([part("s_amina", 1, "18.00"), part("s_amina", 2, "18.00")], "one share per order"),
        ([], "at least one"),
    ],
)
def test_bad_shares_are_refused(seeded, parts, message):
    with pytest.raises(ValueError, match=message):
        create_draft_order(seeded, parts)


def test_drafting_an_order_records_an_event(seeded):
    order = create_draft_order(seeded, [part("s_amina", 12, "18.00"), part("s_priya", 11, "16.00")])
    seeded.commit()

    event = seeded.scalars(select(Event).where(Event.entity_id == order.id)).one()
    assert event.type == "order.drafted"
    assert event.payload_json["summary"] == f"Draft order {order.id}: 23 units from 2 makers, $392.00"
    assert event.payload_json["total_usd"] == "392.00"


# ---------- status rules ----------


def test_the_happy_path_of_pay_on_proof_is_allowed(seeded):
    order = create_draft_order(seeded, [part("s_amina", 12, "18.00"), part("s_priya", 11, "16.00")])
    first, second = order.parts

    move_order(order, OrderStatus.AWAITING_APPROVAL)
    move_order(order, OrderStatus.AUTHORIZED)
    for share in (first, second):
        move_part(share, PartStatus.AUTHORIZED)
    move_part(first, PartStatus.CAPTURED)  # Amina's receipt confirmed: she is paid
    move_order(order, OrderStatus.PARTLY_SHIPPED)
    move_part(second, PartStatus.RELEASED)  # Priya dropped out
    move_order(order, OrderStatus.SHIPPED)
    move_part(first, PartStatus.DELIVERED)
    move_order(order, OrderStatus.COMPLETED)

    assert order.status is OrderStatus.COMPLETED


@pytest.mark.parametrize(
    ("start", "to"),
    [
        (PartStatus.RELEASED, PartStatus.CAPTURED),  # never capture a released share
        (PartStatus.CAPTURED, PartStatus.RELEASED),  # never release a paid share
        (PartStatus.PENDING, PartStatus.CAPTURED),  # never capture before the order is authorized
        (PartStatus.DELIVERED, PartStatus.AUTHORIZED),
    ],
)
def test_illegal_share_moves_are_refused(start, to):
    share = OrderPart(order_id="ord_1", reference_id="op_001", status=start)

    with pytest.raises(IllegalMove):
        move_part(share, to)


@pytest.mark.parametrize(
    ("start", "to"),
    [
        (OrderStatus.DRAFT, OrderStatus.AUTHORIZED),  # skipping the human's approval
        (OrderStatus.COMPLETED, OrderStatus.DRAFT),
        (OrderStatus.CANCELLED, OrderStatus.AWAITING_APPROVAL),
        (OrderStatus.SHIPPED, OrderStatus.CANCELLED),
    ],
)
def test_illegal_order_moves_are_refused(start, to):
    order = Order(id="ord_1", status=start)

    with pytest.raises(IllegalMove):
        move_order(order, to)


def test_every_status_has_rules_and_the_ends_are_final():
    assert set(ORDER_MOVES) == set(OrderStatus)
    assert set(PART_MOVES) == set(PartStatus)
    assert ORDER_MOVES[OrderStatus.COMPLETED] == ORDER_MOVES[OrderStatus.CANCELLED] == frozenset()
    assert PART_MOVES[PartStatus.DELIVERED] == PART_MOVES[PartStatus.RELEASED] == frozenset()


# ---------- the order API ----------


@pytest.fixture
def demo_order(seeded):
    order = seed_demo_order(seeded, date(2026, 11, 10))
    seeded.commit()
    return order


def test_an_order_shows_each_makers_share_her_trust_and_the_buyers_request(demo_order):
    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()

    assert order["status"] == "draft"
    assert (order["total_usd"], order["units"]) == ("815.00", 40)
    assert order["request"] == {
        "summary": "40 hand-embroidered cushion covers for corporate gifts",
        "quantity": 40,
        "max_unit_price": "30.00",
        "deadline": "2026-12-10",
        "ship_to": "Chicago",
        # The story's plan in words (prompt 26), written by the template when the order is seeded.
        "explanation": (
            "The 40 units are split across 4 makers, cheapest valid offer first: Priya 11 at $16.00, Amina 12 at "
            "$18.00, Lucía 10 at $22.00 and Grace 7 at $29.00. The total is $815.00, and every share is due by "
            "December 10, 2026."
        ),
        "explanation_by": "Written from the plan by OpenStall's code.",
    }
    shares = [(p["seller"]["name"], p["quantity"], p["unit_price_usd"], p["amount_usd"]) for p in order["parts"]]
    assert shares == [
        ("Amina", 12, "18.00", "216.00"),
        ("Priya", 11, "16.00", "176.00"),
        ("Lucía", 10, "22.00", "220.00"),
        ("Grace", 7, "29.00", "203.00"),
    ]
    amina = order["parts"][0]
    assert amina["photo"] == "/media/seed/amina-cushion-1.svg"
    assert amina["trust_score"] == "0.95" and amina["trust_data_source"] == "seeded_demo"
    assert amina["delivery_date"] == "2026-12-10"
    assert amina["status"] == "pending"


def test_an_unknown_order_is_a_clear_404(seeded):
    response = client.get("/api/orders/ord_nobody")

    assert response.status_code == 404
    assert response.json()["detail"] == "There is no order called 'ord_nobody'."


def test_the_right_total_is_confirmed(demo_order):
    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/verify-total", json={"total_usd": "815.00"})

    assert response.status_code == 200
    assert response.json() == {"total_usd": "815.00"}


@pytest.mark.parametrize("claimed", ["800.00", "815.01", 0, "1"])
def test_a_changed_total_is_refused(demo_order, claimed):
    # Spec section 7: the server recalculates totals, and a changed client total is rejected.
    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/verify-total", json={"total_usd": claimed})

    assert response.status_code == 409
    assert response.json()["detail"].startswith("The total is $815.00")


def test_a_sub_cent_total_is_refused_as_invalid(demo_order):
    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/verify-total", json={"total_usd": "815.005"})

    assert response.status_code == 422


def test_seeding_the_demo_order_again_replaces_it(demo_order, seeded):
    seed_demo_order(seeded, date(2026, 11, 11))
    seeded.commit()

    assert seeded.scalar(select(func.count()).select_from(Order)) == 1
    assert seeded.get(Order, DEMO_ORDER_ID).parts[0].delivery_date == date(2026, 12, 11)
