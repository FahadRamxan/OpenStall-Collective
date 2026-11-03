"""The stalls over HTTP: GET /api/sellers, /api/sellers/{id}, /api/products, and the seed photos."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from openstall_api.main import app
from openstall_api.models import Product, ProductStatus
from openstall_api.seed import seed

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def test_the_stalls_are_listed_by_name_with_their_cover_and_lowest_price(seeded):
    cards = client.get("/api/sellers").json()

    assert [card["name"] for card in cards] == ["Amina", "Grace", "Lucía", "Noor", "Priya"]
    priya = next(card for card in cards if card["id"] == "s_priya")
    assert priya["from_price_usd"] == "16.00"  # a string, so the price stays exact
    assert priya["headline"] == "Mirror-work embroidered cushion cover"
    assert priya["cover_photo"] == "/media/seed/priya-cushion-1.svg"
    assert priya["data_source"] == "seeded_demo"
    assert (priya["city"], priya["country"], priya["language"]) == ("Jaipur", "IN", "hi")


def test_a_seller_without_a_live_listing_is_not_listed(seeded):
    seeded.get(Product, "p_grace_cushion").status = ProductStatus.PAUSED
    seeded.commit()

    assert "s_grace" not in {card["id"] for card in client.get("/api/sellers").json()}


def test_a_stall_shows_the_maker_her_listings_and_her_trust_record(seeded):
    stall = client.get("/api/sellers/s_noor").json()

    assert (stall["name"], stall["city"], stall["country"], stall["language"]) == ("Noor", "Manchester", "GB", "ur")
    [product] = stall["products"]
    assert product["title"] == "Chain-stitch embroidered cushion cover"
    assert product["price_usd"] == "31.00"
    assert product["variants"] == ["rose", "forest"]
    assert (product["capacity_per_week"], product["ship_days"]) == (3, 5)
    assert product["photos"] == ["/media/seed/noor-cushion-1.svg", "/media/seed/noor-cushion-2.svg"]
    trust = stall["trust"]
    assert trust["orders_delivered"] == 25
    assert Decimal(trust["score"]) == Decimal("0.97")  # 0.4 x 0.96 + 0.3 x 1.00 + 0.3 x 0.94 = 0.966
    assert trust["data_source"] == "seeded_demo"


def test_an_unknown_stall_is_a_clear_404(seeded):
    response = client.get("/api/sellers/s_nobody")

    assert response.status_code == 404
    assert response.json()["detail"] == "There is no stall called 's_nobody'."


def test_products_can_be_listed_for_one_seller_or_all(seeded):
    all_products = client.get("/api/products").json()
    priya_only = client.get("/api/products", params={"seller_id": "s_priya"}).json()

    assert len(all_products) == 5
    assert [product["id"] for product in priya_only] == ["p_priya_cushion"]


def test_every_seed_photo_is_served_as_an_svg(seeded):
    for card in client.get("/api/sellers").json():
        for photo in client.get(f"/api/sellers/{card['id']}").json()["products"][0]["photos"]:
            response = client.get(photo)
            assert response.status_code == 200, photo
            assert response.headers["content-type"].startswith("image/svg+xml")
            assert "Placeholder photo" in response.text
