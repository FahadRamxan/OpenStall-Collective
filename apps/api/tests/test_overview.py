"""The home page's numbers (prompt 41): GET /api/overview counts live makers and listings, approved orders, what makers
were paid on proof, the parcels delivered, and agents' searches this week, leaving Demand Radar's seeded searches out."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from openstall_api.main import app
from openstall_api.models import Order, Search, utcnow
from openstall_api.seed import DEMO_ORDER_ID, reset_demo_world

client = TestClient(app)
TODAY = date(2026, 11, 10)


def seeded_world(db) -> None:
    reset_demo_world(db, TODAY)
    db.commit()


def test_the_seeded_world_has_five_makers_and_nothing_paid_yet(db):
    seeded_world(db)

    assert client.get("/api/overview").json() == {
        "makers": 5,
        "listings": 5,
        "orders_approved": 0,
        "paid_usd": "0.00",
        "makers_paid": 0,
        "deliveries": 0,
        "agent_searches": 0,  # Demand Radar's 37 seeded searches are not agents'
        "simulated": True,
    }


def test_an_approved_order_a_maker_paid_on_proof_and_her_parcel_delivered(db, fakes):
    seeded_world(db)
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    db.expire_all()
    priya = next(part for part in db.get(Order, DEMO_ORDER_ID).parts if part.seller_id == "s_priya")
    assert client.post(f"/api/dev/parts/{priya.id}/proof").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/parts/{priya.id}/delivered").status_code == 200

    overview = client.get("/api/overview").json()

    assert (overview["orders_approved"], overview["paid_usd"], overview["makers_paid"]) == (1, "176.00", 1)
    assert overview["deliveries"] == 1


def test_agents_searches_this_week_only(db):
    seeded_world(db)
    db.add_all(
        [
            Search(query="cushion covers", filters_json={}, result_count=4),
            Search(query="ceramic mugs", filters_json={}, result_count=0),
            Search(query="ceramic mugs", filters_json={}, result_count=0, created_at=utcnow() - timedelta(days=9)),
        ]
    )
    db.commit()

    assert client.get("/api/overview").json()["agent_searches"] == 2
