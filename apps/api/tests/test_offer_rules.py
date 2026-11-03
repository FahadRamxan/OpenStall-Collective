"""The offer rules on real data: policy JSON and products mapped onto the allocator core, and committed units."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from openstall_allocator import Listing, Offer, QuoteRequest, RejectionReason, SellerPolicy, is_valid_offer
from openstall_api.models import Order, OrderPart, OrderStatus, PartStatus, Product, Seller
from openstall_api.models import QuoteRequest as QuoteRequestRow
from openstall_api.offer_rules import (
    PolicyError,
    capacity_by_deadline,
    committed_units,
    default_deadline,
    listing_of,
    quote_request_of,
    seller_policy,
)
from openstall_api.seed import MAKERS, seed

TODAY = date(2026, 11, 10)
# Spec section 2: what each maker can supply in a 30-day order.
SEED_SUPPLY = {"s_amina": 12, "s_priya": 11, "s_lucia": 10, "s_grace": 11, "s_noor": 10}


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def product(db, seller_id: str) -> Product:
    return db.get(Product, next(maker.product_id for maker in MAKERS if maker.id == seller_id))


def add_share(db, seller_id: str, quantity: int, status: PartStatus, due: date = date(2026, 12, 10)) -> None:
    """One order holding one share of hers, in the given status."""
    price = Decimal("16.00")
    order = Order(status=OrderStatus.AUTHORIZED, total_usd=price * quantity)
    order.parts = [
        OrderPart(
            seller_id=seller_id,
            product_id=product(db, seller_id).id,
            reference_id="op_001",
            quantity=quantity,
            unit_price_usd=price,
            amount_usd=price * quantity,
            delivery_date=due,
            status=status,
        )
    ]
    db.add(order)
    db.commit()


def test_a_policy_and_a_product_map_onto_the_core_types(seeded):
    amina = seeded.get(Seller, "s_amina")
    cushion = product(seeded, "s_amina")

    assert seller_policy(amina, cushion) == SellerPolicy(
        seller_id="s_amina",
        floor_price_usd=Decimal("15.00"),
        max_discount_pct=Decimal("15"),
        capacity_per_week=4,
        min_lead_days=5,
        free_shipping_min_qty=3,
    )
    assert listing_of(cushion) == Listing(
        seller_id="s_amina", product_id="p_amina_cushion", price_usd=Decimal("18.00"), ship_days=9
    )


def test_capacity_comes_from_the_listing_when_the_policy_leaves_it_out(seeded):
    # Onboarding asks for the price limits and takes capacity from the listing (prompt 18).
    priya = seeded.get(Seller, "s_priya")
    priya.policy_json = {key: value for key, value in priya.policy_json.items() if key != "capacity_per_week"}

    assert seller_policy(priya, product(seeded, "s_priya")).capacity_per_week == 4
    with pytest.raises(PolicyError, match="seller s_priya's policy is missing capacity_per_week"):
        seller_policy(priya)


@pytest.mark.parametrize("field", ["floor_price_usd", "max_discount_pct", "min_lead_days"])
def test_a_policy_missing_a_field_is_a_clear_error(seeded, field):
    noor = seeded.get(Seller, "s_noor")
    noor.policy_json = {key: value for key, value in noor.policy_json.items() if key != field}

    with pytest.raises(PolicyError, match=f"^seller s_noor's policy is missing {field}$"):
        seller_policy(noor, product(seeded, "s_noor"))


def test_no_policy_or_another_sellers_policy_is_a_clear_error(seeded):
    grace = seeded.get(Seller, "s_grace")
    cushion = product(seeded, "s_grace")

    grace.policy_json = None
    with pytest.raises(PolicyError, match="seller s_grace has no policy yet"):
        seller_policy(grace, cushion)

    grace.policy_json = {**seeded.get(Seller, "s_noor").policy_json}
    with pytest.raises(PolicyError, match="seller s_grace's policy belongs to 's_noor'"):
        seller_policy(grace, cushion)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("floor_price_usd", "15.005", "an amount must be whole cents, got '15.005'"),
        ("max_discount_pct", 150, "max_discount_pct must be from 0 to 100"),
        ("capacity_per_week", 4.5, "capacity_per_week must be an int, not float"),
        ("min_lead_days", -1, "min_lead_days must be at least 0, got -1"),
    ],
)
def test_a_value_the_rules_refuse_is_a_clear_error(seeded, field, value, reason):
    lucia = seeded.get(Seller, "s_lucia")
    lucia.policy_json = {**lucia.policy_json, field: value}

    with pytest.raises(PolicyError) as refused:
        seller_policy(lucia, product(seeded, "s_lucia"))

    assert str(refused.value).startswith("seller s_lucia's policy has a value the offer rules refuse: ")
    assert reason in str(refused.value)


@pytest.mark.parametrize("today", [TODAY, date(2026, 12, 1), date(2027, 2, 27)])
def test_capacity_by_deadline_matches_the_seed_table(seeded, today):
    deadline = default_deadline(today)

    supply = {seller: capacity_by_deadline(product(seeded, seller), today, deadline) for seller in SEED_SUPPLY}

    assert deadline == today + timedelta(days=30)
    assert supply == SEED_SUPPLY


def test_a_deadline_sooner_than_her_lead_days_gives_no_capacity_as_the_offer_rules_say(db):
    # A fast maker: 21 a week, 1 day to ship, but she needs 5 days' notice.
    db.add(
        Seller(
            id="s_fast",
            name="Fast maker",
            policy_json={"floor_price_usd": "10.00", "max_discount_pct": 10, "min_lead_days": 5},
        )
    )
    db.add(
        Product(
            id="p_fast",
            seller_id="s_fast",
            title="Linen napkins",
            description="",
            category="home",
            variants_json=[],
            price_usd=Decimal("12.00"),
            capacity_per_week=21,
            ship_days=1,
            ship_from_city="Austin",
        )
    )
    db.commit()
    fast = db.get(Product, "p_fast")
    policy, listing = seller_policy(fast.seller, fast), listing_of(fast)

    for days, capacity in [(3, 0), (4, 0), (5, 12), (6, 15)]:
        deadline = TODAY + timedelta(days=days)
        request = QuoteRequest(quantity=40, max_unit_price=Decimal("30.00"), deadline=deadline)
        # Her production time alone says 6 by day 3, but seller agents deliver on the deadline, and the offer rules
        # refuse a delivery sooner than her lead days.
        assert capacity_by_deadline(fast, TODAY, deadline) == capacity, days
        offer = Offer(
            seller_id="s_fast", unit_price=Decimal("12.00"), quantity=max(capacity, 1), delivery_date=deadline
        )
        check = is_valid_offer(offer, policy, listing, request, TODAY)
        assert check.reason == (RejectionReason.TOO_SOON if capacity == 0 else None), days


def test_only_reserved_shares_count_as_committed_whatever_their_date(seeded):
    add_share(seeded, "s_priya", 3, PartStatus.PENDING)  # a draft: nobody approved it yet
    add_share(seeded, "s_priya", 5, PartStatus.AUTHORIZED)
    add_share(seeded, "s_priya", 2, PartStatus.AUTHORIZED, due=date(2027, 6, 1))  # due long after the deadline
    add_share(seeded, "s_priya", 4, PartStatus.CAPTURED)  # made and shipped
    add_share(seeded, "s_priya", 1, PartStatus.DELIVERED)
    add_share(seeded, "s_priya", 6, PartStatus.RELEASED)  # she dropped out
    add_share(seeded, "s_lucia", 10, PartStatus.AUTHORIZED)

    committed = committed_units(seeded, ["s_priya", "s_lucia", "s_grace", "s_priya"])

    assert committed == {"s_priya": 7, "s_lucia": 10, "s_grace": 0}
    deadline = default_deadline(TODAY)
    assert capacity_by_deadline(product(seeded, "s_priya"), TODAY, deadline, committed["s_priya"]) == 11 - 7
    assert capacity_by_deadline(product(seeded, "s_lucia"), TODAY, deadline, committed["s_lucia"]) == 0
    assert committed_units(seeded, []) == {}


def test_a_stored_quote_request_maps_onto_the_core_type():
    row = QuoteRequestRow(
        id="q_story",
        items_json=[{"query": "hand-embroidered cushion covers"}],
        quantity=40,
        max_unit_price=Decimal("30.00"),
        deadline=date(2026, 12, 10),
        ship_to="Chicago",
    )

    assert quote_request_of(row) == QuoteRequest(
        quantity=40, max_unit_price=Decimal("30.00"), deadline=date(2026, 12, 10), request_id="q_story"
    )
