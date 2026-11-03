"""The offer rules on the /demo page (prompt 22): GET /api/demo/limits gives each live maker's lowest price and her
capacity by the deadline from the allocator core, and the dev helper that releases reserved shares for UI tests."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from openstall_allocator import FixedClock
from openstall_api import demo_api
from openstall_api.main import app
from openstall_api.models import Order, PartStatus, Product, ProductStatus, Seller
from openstall_api.seed import DEMO_ORDER_ID, MAKERS, seed, seed_demo_order

client = TestClient(app)

TODAY = date(2026, 11, 10)
# Spec section 2: what each maker can supply in 30 days, and the lowest price her agent may offer: her floor, or her
# list price less the 15% maximum discount, whichever is higher.
SEED_SUPPLY = {"s_amina": 12, "s_priya": 11, "s_lucia": 10, "s_grace": 11, "s_noor": 10}
SEED_LOWEST = {"s_amina": "15.30", "s_priya": "13.60", "s_lucia": "19.00", "s_grace": "27.20", "s_noor": "28.50"}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(demo_api, "clock", FixedClock(TODAY))


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


@pytest.fixture
def demo_order(seeded):
    seed_demo_order(seeded, TODAY)
    seeded.commit()
    return seeded


def limits(**params: str) -> dict:
    response = client.get("/api/demo/limits", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def by_seller(body: dict) -> dict[str, dict]:
    return {maker["seller_id"]: maker for maker in body["makers"]}


def reserve_demo_order() -> None:
    """The story's order approved on the simulated PayPal page and reserved: every share is then committed."""
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200


def test_the_limits_are_the_seed_tables_for_the_default_30_day_deadline(seeded):
    body = limits()

    assert (body["today"], body["deadline"]) == ("2026-11-10", "2026-12-10")
    makers = by_seller(body)
    assert {seller: maker["capacity_by_deadline"] for seller, maker in makers.items()} == SEED_SUPPLY
    assert {seller: maker["lowest_price_usd"] for seller, maker in makers.items()} == SEED_LOWEST
    assert body["unreadable"] == []
    amina = makers["s_amina"]
    assert (amina["seller_name"], amina["city"], amina["list_price_usd"], amina["floor_price_usd"]) == (
        "Amina",
        "Lahore",
        "18.00",
        "15.00",
    )
    assert (amina["max_discount_pct"], amina["capacity_per_week"], amina["ship_days"], amina["min_lead_days"]) == (
        "15",
        4,
        9,
        5,
    )
    # Seeded makers stay marked as made-up demo data.
    assert {maker["data_source"] for maker in makers.values()} == {"seeded_demo"}
    assert {maker["committed_units"] for maker in makers.values()} == {0}


def test_one_row_per_live_listing_with_its_title(seeded):
    makers = by_seller(limits())
    expected = {maker.id: maker.product_id for maker in MAKERS}

    assert {seller: maker["product_id"] for seller, maker in makers.items()} == expected
    assert all(maker["product_title"] for maker in makers.values())


def test_a_later_deadline_gives_more_capacity_and_the_same_lowest_prices(seeded):
    # 44 days: makes per week x (44 - ship days) / 7, rounded down.
    makers = by_seller(limits(deadline="2026-12-24"))

    assert {seller: maker["capacity_by_deadline"] for seller, maker in makers.items()} == {
        "s_amina": 20,
        "s_priya": 19,
        "s_lucia": 16,
        "s_grace": 17,
        "s_noor": 16,
    }
    assert {seller: maker["lowest_price_usd"] for seller, maker in makers.items()} == SEED_LOWEST


def test_a_deadline_sooner_than_their_lead_days_leaves_no_capacity(seeded):
    # Every maker needs 5 days' notice, so nothing can be promised for 4 days from now.
    makers = by_seller(limits(deadline=(TODAY + timedelta(days=4)).isoformat()))

    assert {maker["capacity_by_deadline"] for maker in makers.values()} == {0}


@pytest.mark.parametrize("deadline", ["2026-11-10", "2026-11-09"])
def test_a_deadline_that_is_not_after_today_is_refused_in_words(seeded, deadline):
    response = client.get("/api/demo/limits", params={"deadline": deadline})

    assert response.status_code == 422
    assert response.json()["detail"] == f"The deadline {deadline} must be after today, 2026-11-10 (UTC)."


def test_a_drafted_order_commits_nothing_and_a_reserved_one_lowers_each_makers_capacity(demo_order, fakes):
    # The seeded draft (12/11/10/7) is not approved, so it holds no maker's time.
    assert {s: m["capacity_by_deadline"] for s, m in by_seller(limits()).items()} == SEED_SUPPLY

    reserve_demo_order()
    makers = by_seller(limits())

    assert {seller: maker["committed_units"] for seller, maker in makers.items()} == {
        "s_amina": 12,
        "s_priya": 11,
        "s_lucia": 10,
        "s_grace": 7,
        "s_noor": 0,
    }
    assert {seller: maker["capacity_by_deadline"] for seller, maker in makers.items()} == {
        "s_amina": 0,
        "s_priya": 0,
        "s_lucia": 0,
        "s_grace": 4,
        "s_noor": 10,
    }
    # Committed units change capacity, never the lowest price.
    assert {seller: maker["lowest_price_usd"] for seller, maker in makers.items()} == SEED_LOWEST


def test_a_maker_whose_policy_cannot_be_read_is_named_and_the_others_still_show(seeded):
    noor = seeded.get(Seller, "s_noor")
    noor.policy_json = {key: value for key, value in noor.policy_json.items() if key != "floor_price_usd"}
    seeded.commit()

    body = limits()

    assert set(by_seller(body)) == set(SEED_SUPPLY) - {"s_noor"}
    assert body["unreadable"] == ["Noor's limits cannot be checked: seller s_noor's policy is missing floor_price_usd."]


def test_only_live_listings_have_limits(seeded):
    grace = seeded.get(Product, next(maker.product_id for maker in MAKERS if maker.id == "s_grace"))
    grace.status = ProductStatus.PAUSED
    seeded.commit()

    assert "s_grace" not in by_seller(limits())


def test_no_live_listing_means_no_rows(db):
    assert limits()["makers"] == []


def test_the_dev_helper_releases_every_reserved_share_and_gives_the_seed_capacity_back(demo_order, fakes):
    reserve_demo_order()
    assert by_seller(limits())["s_amina"]["capacity_by_deadline"] == 0

    response = client.post("/api/dev/release-reserved-shares")

    assert response.status_code == 200
    assert response.json() == {"released": 4}
    demo_order.expire_all()
    assert {part.status for part in demo_order.get(Order, DEMO_ORDER_ID).parts} == {PartStatus.RELEASED}
    assert {s: m["capacity_by_deadline"] for s, m in by_seller(limits()).items()} == SEED_SUPPLY
    # Nothing is left to release.
    assert client.post("/api/dev/release-reserved-shares").json() == {"released": 0}


def test_the_dev_helper_does_not_exist_outside_fake_mode(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.post("/api/dev/release-reserved-shares").status_code == 404
