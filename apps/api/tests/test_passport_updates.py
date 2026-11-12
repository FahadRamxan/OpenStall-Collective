"""Trust passports updated after each delivery (prompt 36, spec 3.7): when a buyer receives a maker's parcel, her
passport is worked out again from her history and her deliveries through OpenStall, and signed again. A seeded
maker's passport stays marked seeded_demo and says how many of its orders went through OpenStall; on time is by each
share's delivery date; doing it again changes nothing; a maker with no passport gets none yet."""

import asyncio
from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_api import delivery
from openstall_api.db import session_scope
from openstall_api.delivery import confirm_delivery, refresh_passport
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import DataSource, Event, Order, OrderPart, Passport, Seller
from openstall_api.passports import FAKE_MODE_KEY_B64, MissingSigningKey
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront
from openstall_trust import load_private_key, load_public_key, public_key_b64, verify_passport

client = TestClient(app)
DUE = date(2026, 12, 10)  # the story order's delivery date
ON_TIME = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
LATE = datetime(2026, 12, 12, 9, 0, tzinfo=UTC)
# Priya's seeded history: 67 orders delivered, 97% on time, 1% disputed, 93% original photos.
PRIYA = {"orders_delivered": 67, "on_time_rate": 0.97, "dispute_rate": 0.01, "photo_originality": 0.93}


@pytest.fixture
def reserved(db, fakes) -> dict[str, str]:
    """The story order approved on the simulated PayPal page and reserved: each maker's share id, by seller."""
    seed(db, with_amina=True)
    seed_demo_order(db, date(2026, 11, 10))
    db.commit()
    return reserve(DEMO_ORDER_ID, db)


def reserve(order_id: str, db) -> dict[str, str]:
    token = client.post(f"/api/orders/{order_id}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{order_id}/reserve").status_code == 200
    db.expire_all()
    return {part.seller_id: part.id for part in db.get(Order, order_id).parts}


def ship_and_deliver(part_id: str, when: datetime) -> None:
    assert client.post(f"/api/dev/parts/{part_id}/proof").status_code == 200
    with session_scope() as session:
        assert confirm_delivery(session, part_id, now=when) is True


def passport(db, seller_id: str) -> Passport:
    db.expire_all()
    return db.get(Passport, seller_id)


def updates(db) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == EventType.PASSPORT_UPDATED).order_by(Event.id)))


def test_her_passport_counts_the_delivery_and_is_signed_again(reserved, db):
    before = passport(db, "s_priya").signature

    ship_and_deliver(reserved["s_priya"], ON_TIME)

    after = passport(db, "s_priya")
    assert {key: after.metrics_json[key] for key in (*PRIYA, "live_deliveries", "live_on_time")} == {
        "orders_delivered": 68,
        "on_time_rate": 0.9704,  # (0.97 x 67 + 1) / 68
        "dispute_rate": 0.0099,  # 0.01 x 67 / 68: a delivery is undisputed
        "photo_originality": 0.93,  # nothing measures it again yet
        "live_deliveries": 1,
        "live_on_time": 1,
    }
    assert after.data_source == DataSource.SEEDED_DEMO  # her history is still made up
    assert after.metrics_json["issued_at"] == "2026-12-01T15:00:00Z"
    assert after.signature != before
    signed = {**after.metrics_json, "signature": after.signature}
    public = load_public_key(public_key_b64(load_private_key(FAKE_MODE_KEY_B64)))
    assert verify_passport(signed, public)
    assert not verify_passport({**signed, "orders_delivered": 69}, public)


def test_a_late_parcel_lowers_her_on_time_rate(reserved, db):
    ship_and_deliver(reserved["s_priya"], LATE)

    metrics = passport(db, "s_priya").metrics_json
    assert (metrics["on_time_rate"], metrics["live_on_time"]) == (0.9557, 0)  # 0.97 x 67 / 68


def test_the_live_feed_says_what_changed(reserved, db):
    ship_and_deliver(reserved["s_priya"], ON_TIME)

    [update] = updates(db)
    assert update.payload_json["summary"] == (
        "Priya's trust passport was signed again after her delivery: 68 orders delivered, 97% on time, score 0.96 "
        "(was 0.96)"
    )
    assert update.payload_json["before"] == {
        "orders_delivered": 67,
        "on_time_rate": 0.97,
        "dispute_rate": 0.01,
        "score": "0.96",
    }
    assert update.payload_json["after"]["orders_delivered"] == 68
    assert (update.entity_id, update.payload_json["live_deliveries"]) == ("s_priya", 1)


def test_it_is_worked_out_from_the_deliveries_so_doing_it_again_changes_nothing(reserved, db):
    ship_and_deliver(reserved["s_priya"], ON_TIME)
    signed = passport(db, "s_priya").signature

    with session_scope() as session:
        assert refresh_passport(session, "s_priya") is False

    assert passport(db, "s_priya").signature == signed
    assert len(updates(db)) == 1


def test_each_delivery_counts(reserved, db):
    ship_and_deliver(reserved["s_priya"], ON_TIME)
    second = client.post("/api/dev/story-orders").json()["order_id"]
    shares = reserve(second, db)
    # The second order is due 30 days from the day the test runs: late is two days after its own date.
    due = db.get(OrderPart, shares["s_priya"]).delivery_date

    ship_and_deliver(shares["s_priya"], datetime.combine(due + timedelta(days=2), time(9), tzinfo=UTC))

    metrics = passport(db, "s_priya").metrics_json
    assert (metrics["orders_delivered"], metrics["live_deliveries"], metrics["live_on_time"]) == (69, 2, 1)
    assert metrics["on_time_rate"] == round((0.97 * 67 + 1) / 69, 4)


def test_agents_see_it_on_her_trust_card_and_in_search(reserved, db):
    ship_and_deliver(reserved["s_priya"], ON_TIME)

    card = asyncio.run(_call("get_trust_card", seller_id="s_priya"))
    found = asyncio.run(_call("search_products", query="mirror-work cushion cover"))

    assert (card["orders_delivered"], card["live_deliveries"], card["data_source"]) == (68, 1, "seeded_demo")
    assert card["issued_at"] == "2026-12-01T15:00:00Z"
    [priya] = [result for result in found["result"] if result["seller_id"] == "s_priya"]
    assert priya["trust"]["summary"] == (
        "Trust score 0.96 from 68 delivered orders: 97% on time, 1% disputed (seeded demo numbers, 1 of them through "
        "OpenStall)"
    )


def test_a_maker_with_no_passport_gets_none_yet(db):
    new = Seller(name="A new maker", data_source=DataSource.LIVE)
    db.add(new)
    db.commit()

    with session_scope() as session:
        assert refresh_passport(session, new.id) is False

    assert passport(db, new.id) is None


def test_without_a_signing_key_her_delivery_stands_and_her_passport_waits(reserved, db, monkeypatch):
    def no_key(*args, **kwargs):
        raise MissingSigningKey("Sandbox mode needs PASSPORT_SIGNING_KEY to sign trust passports.")

    monkeypatch.setattr(delivery, "issue_passport", no_key)

    ship_and_deliver(reserved["s_priya"], ON_TIME)

    assert passport(db, "s_priya").metrics_json["orders_delivered"] == 67
    assert updates(db) == []


async def _call(name: str, **arguments) -> dict:
    async with Client(storefront) as mcp:
        result = await mcp.call_tool(name, arguments)
    assert not result.is_error, result.content
    return result.structured_content
