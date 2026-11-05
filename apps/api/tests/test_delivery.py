"""Delivery and the end of an order (prompt 34): the buyer confirms each maker's parcel arrived; her share is delivered,
with when and whether by its delivery date; she is told in her language, once; and the order is completed once every
paid share is delivered, whichever share settles last. No money moves at delivery."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_api.adapters import get_registry
from openstall_api.db import session_scope
from openstall_api.delivery import DELIVERED, confirm_delivery
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, Direction, Event, Order, OrderPart, PartStatus
from openstall_api.payments import WrongStatus, release_share
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront
from openstall_api.wording import format_day

client = TestClient(app)
DUE = date(2026, 12, 10)  # the story order's delivery date: seeded on November 10, due in 30 days


@pytest.fixture
def demo_order(db):
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return db


@pytest.fixture
def reserved(demo_order, fakes) -> dict[str, str]:
    """The story order approved on the simulated PayPal page and reserved: each maker's share id, by seller."""
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    demo_order.expire_all()
    return {part.seller_id: part.id for part in demo_order.get(Order, DEMO_ORDER_ID).parts}


def ship(reserved: dict[str, str], *sellers: str) -> None:
    """Each maker's simulated proof of shipping, which pays her share."""
    for seller in sellers:
        assert client.post(f"/api/dev/parts/{reserved[seller]}/proof").status_code == 200, seller


def deliver(part_id: str, order_id: str = DEMO_ORDER_ID):
    return client.post(f"/api/orders/{order_id}/parts/{part_id}/delivered")


def shares(body: dict) -> dict[str, dict]:
    return {part["seller"]["id"]: part for part in body["parts"]}


def events(db, kind: EventType) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == kind).order_by(Event.id)))


def chat_texts(db, seller_id: str) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(ChatMessage.text)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.seller_id == seller_id, ChatMessage.direction == Direction.OUTBOUND)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    )


def test_the_buyer_confirms_a_parcel_and_her_share_is_delivered_with_when_and_whether_on_time(reserved, demo_order):
    ship(reserved, "s_priya")

    response = deliver(reserved["s_priya"])

    assert response.status_code == 200, response.text
    priya = shares(response.json())["s_priya"]
    today = datetime.now(UTC).date()
    assert priya["status"] == "delivered"
    assert date.fromisoformat(priya["delivered_at"][:10]) == today
    assert priya["on_time"] is (today <= DUE)
    assert response.json()["status"] == "partly_shipped"  # the other makers have not all shipped
    [confirmed] = events(demo_order, EventType.DELIVERY_CONFIRMED)
    timing = ", on time" if today <= DUE else ", late: it was due December 10, 2026"
    assert confirmed.payload_json["summary"] == (
        f"The buyer received Priya's parcel for order {DEMO_ORDER_ID} on {today:%B} {today.day}, {today.year}{timing}"
    )
    assert confirmed.entity_id == reserved["s_priya"]


def test_she_is_told_in_her_language_once(reserved, demo_order):
    ship(reserved, "s_priya", "s_lucia")

    deliver(reserved["s_priya"])
    deliver(reserved["s_priya"])
    deliver(reserved["s_lucia"])

    today = datetime.now(UTC).date()
    on_time = today <= DUE
    hindi = [text for text in chat_texts(demo_order, "s_priya") if text and text.startswith("खुशखबरी")]
    assert hindi == [
        f"खुशखबरी, Priya! खरीदार को ऑर्डर {DEMO_ORDER_ID} का आपका पार्सल {format_day('hi', today)} को मिल गया"
        f"{DELIVERED['hi'].on_time if on_time else ''}। धन्यवाद!"
    ]
    spanish = chat_texts(demo_order, "s_lucia")[-1]
    assert spanish.startswith(
        f"¡Buenas noticias, Lucía! El comprador recibió tu paquete del pedido {DEMO_ORDER_ID} el "
    )
    told = [event.payload_json["summary"] for event in events(demo_order, EventType.MESSAGE_SENT)]
    told_priya = (
        f"OpenStall told Priya in the web chat, in Hindi, that the buyer received her parcel for order {DEMO_ORDER_ID}"
    )
    assert told_priya in told


def test_confirming_again_changes_nothing(reserved, demo_order):
    ship(reserved, "s_grace")
    first = shares(deliver(reserved["s_grace"]).json())["s_grace"]

    again = deliver(reserved["s_grace"])

    assert again.status_code == 200
    assert shares(again.json())["s_grace"]["delivered_at"] == first["delivered_at"]
    assert len(events(demo_order, EventType.DELIVERY_CONFIRMED)) == 1


def test_a_share_that_has_not_shipped_or_was_released_cannot_be_delivered(reserved, demo_order):
    not_shipped = deliver(reserved["s_amina"])
    assert client.post("/api/dev/release-reserved-shares").status_code == 200
    released = deliver(reserved["s_amina"])

    assert (not_shipped.status_code, released.status_code) == (409, 409)
    assert not_shipped.json()["detail"] == (
        "Amina has not shipped her share yet: she is paid when she proves she shipped it."
    )
    assert released.json()["detail"] == "Amina's share was released, so there is no parcel of hers to receive."
    assert deliver("op_nobody").status_code == 404
    assert deliver(reserved["s_priya"], order_id="ord_other").status_code == 404
    assert events(demo_order, EventType.DELIVERY_CONFIRMED) == []


def test_the_order_completes_once_every_shipped_parcel_arrived_and_the_rest_was_released(reserved, demo_order):
    ship(reserved, "s_priya", "s_lucia", "s_grace")
    for seller in ("s_priya", "s_lucia", "s_grace"):
        assert deliver(reserved[seller]).json()["status"] == "partly_shipped"  # Amina's share still waits

    assert client.post("/api/dev/release-reserved-shares").json()["released"] == 1  # Amina cannot ship

    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    assert order["status"] == "completed"
    assert (order["paid_usd"], order["released_usd"]) == ("599.00", "216.00")  # 176 + 220 + 203, and Amina's
    demo_order.expire_all()
    parts = demo_order.get(Order, DEMO_ORDER_ID).parts
    delivered = [part for part in parts if part.status == PartStatus.DELIVERED]
    paid = sum(part.amount_usd for part in delivered)
    units = sum(part.quantity for part in delivered)
    [completed] = events(demo_order, EventType.ORDER_COMPLETED)
    assert completed.payload_json["summary"] == (
        f"Order {DEMO_ORDER_ID} is complete: 3 makers delivered {units} units and were paid ${paid:,.2f}; 1 share was "
        "released"
    )
    assert (units, completed.entity_id) == (28, DEMO_ORDER_ID)


def test_a_shipped_order_completes_when_its_last_parcel_arrives(reserved, demo_order, fakes):
    with session_scope() as session:
        release_share(session, reserved["s_amina"], fakes.payment_gateway)  # Amina cannot ship
    ship(reserved, "s_priya", "s_lucia", "s_grace")
    assert client.get(f"/api/orders/{DEMO_ORDER_ID}").json()["status"] == "shipped"

    deliver(reserved["s_priya"])
    deliver(reserved["s_lucia"])
    middle = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()["status"]
    last = deliver(reserved["s_grace"]).json()

    assert (middle, last["status"]) == ("shipped", "completed")
    [completed] = events(demo_order, EventType.ORDER_COMPLETED)
    summary = completed.payload_json["summary"]
    assert summary.startswith(f"Order {DEMO_ORDER_ID} is complete: 3 makers delivered 28 units")


@pytest.mark.parametrize(
    ("arrived", "kept", "timing"),
    [
        (datetime(2026, 12, 10, 23, 59, tzinfo=UTC), True, ", on time"),
        (datetime(2026, 12, 11, 0, 1, tzinfo=UTC), False, ", late: it was due December 10, 2026"),
    ],
)
def test_on_time_is_by_the_delivery_date(reserved, demo_order, arrived, kept, timing):
    ship(reserved, "s_priya")

    with session_scope() as session:
        assert confirm_delivery(session, reserved["s_priya"], now=arrived) is True
        assert confirm_delivery(session, reserved["s_priya"], now=arrived) is False

    demo_order.expire_all()
    part = demo_order.get(OrderPart, reserved["s_priya"])
    assert part.status == PartStatus.DELIVERED
    assert shares(client.get(f"/api/orders/{DEMO_ORDER_ID}").json())["s_priya"]["on_time"] is kept
    [confirmed] = events(demo_order, EventType.DELIVERY_CONFIRMED)
    assert confirmed.payload_json["summary"].endswith(timing)


def test_get_order_status_tells_the_buyer_agent_each_delivery_and_the_end_of_the_order(reserved, demo_order):
    ship(reserved, "s_priya", "s_lucia", "s_grace")
    for seller in ("s_priya", "s_lucia", "s_grace"):
        deliver(reserved[seller])
    client.post("/api/dev/release-reserved-shares")

    status = asyncio.run(_order_status())

    assert status["status"] == "completed"
    assert status["status_words"] == (
        "Completed: every parcel that shipped was received, and every maker who shipped is paid."
    )
    priya = next(share for share in status["shares"] if share["seller_name"] == "Priya")
    assert priya["status"] == "delivered"
    assert priya["status_words"] == "Delivered: the buyer received her parcel."
    assert priya["delivered_at"] is not None and isinstance(priya["on_time"], bool)
    amina = next(share for share in status["shares"] if share["seller_name"] == "Amina")
    assert (amina["status"], amina["delivered_at"], amina["on_time"]) == ("released", None, None)


class NoMoney:
    """A payment gateway that fails the test if delivery reaches any of its PayPal calls."""

    def __getattr__(self, name: str):
        if name in ("create_checkout", "get_order", "reserve", "pay_share", "release_share", "add_tracking"):
            pytest.fail(f"delivery reached PaymentGateway.{name}")
        raise AttributeError(name)


def test_delivery_moves_no_money(reserved, demo_order, monkeypatch):
    ship(reserved, "s_priya", "s_lucia", "s_grace")
    monkeypatch.setitem(get_registry()._made, "payment_gateway", NoMoney())

    for seller in ("s_priya", "s_lucia", "s_grace"):
        assert deliver(reserved[seller]).status_code == 200

    with pytest.raises(WrongStatus), session_scope() as session:
        confirm_delivery(session, reserved["s_amina"])  # still reserved: she has not shipped


async def _order_status() -> dict:
    async with Client(storefront) as mcp:
        result = await mcp.call_tool("get_order_status", {"order_id": DEMO_ORDER_ID})
    assert not result.is_error, result.content
    return result.structured_content
