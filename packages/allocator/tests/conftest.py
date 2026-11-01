"""Shared test data: the seed table from spec section 2, as allocator inputs."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest

from openstall_allocator import Listing, Offer, QuoteRequest, SellerPolicy, capacity_available

# seller id, name, list price, floor, makes per week, ship days to Chicago, can supply in 30 days.
# Every seller has a 15% maximum discount and 5 lead days.
SEED_TABLE = (
    ("s_amina", "Amina", "18.00", "15.00", 4, 9, 12),
    ("s_priya", "Priya", "16.00", "13.00", 4, 10, 11),
    ("s_lucia", "Lucía", "22.00", "19.00", 3, 6, 10),
    ("s_grace", "Grace", "32.00", "27.00", 3, 3, 11),
)

# What each agent ends up offering in the story: list price, except Grace, whose $32 is over the
# buyer's $30 cap, so her agent comes back at $29 (spec section 2, step 6).
STORY_PRICES = {"s_amina": "18.00", "s_priya": "16.00", "s_lucia": "22.00", "s_grace": "29.00"}


@dataclass(frozen=True)
class SeedSeller:
    name: str
    policy: SellerPolicy
    listing: Listing
    can_supply_in_30_days: int


@pytest.fixture
def seed() -> dict[str, SeedSeller]:
    return {
        seller_id: SeedSeller(
            name=name,
            policy=SellerPolicy(
                seller_id=seller_id,
                floor_price_usd=floor,
                max_discount_pct=15,
                capacity_per_week=per_week,
                min_lead_days=5,
            ),
            listing=Listing(
                seller_id=seller_id,
                product_id=f"p_{seller_id[2:]}_cushion",
                price_usd=price,
                ship_days=ship_days,
            ),
            can_supply_in_30_days=can_supply,
        )
        for seller_id, name, price, floor, per_week, ship_days, can_supply in SEED_TABLE
    }


@pytest.fixture
def run_date() -> date:
    """The video is recorded around November 10. Tests may parametrize run_date to move it."""
    return date(2026, 11, 10)


@pytest.fixture
def story_request(run_date: date) -> QuoteRequest:
    """40 cushion covers at most $30 each, to Chicago, due 30 days after the run date."""
    return QuoteRequest(
        request_id="q_story",
        quantity=40,
        max_unit_price=Decimal("30.00"),
        deadline=run_date + timedelta(days=30),
    )


@pytest.fixture
def story_offers(seed: dict[str, SeedSeller], story_request: QuoteRequest, run_date: date) -> list[Offer]:
    """The offers the seller agents make in the story.

    As in spec 3.3 step 1, code sets the quantity (capacity by the deadline, capped at the request)
    and the delivery date (the deadline); the price is the agent's.
    """
    return [
        Offer(
            seller_id=seller_id,
            offer_id=f"off_{seller_id[2:]}",
            unit_price=STORY_PRICES[seller_id],
            quantity=min(
                capacity_available(seller.policy, seller.listing, run_date, story_request.deadline),
                story_request.quantity,
            ),
            delivery_date=story_request.deadline,
        )
        for seller_id, seller in seed.items()
    ]
