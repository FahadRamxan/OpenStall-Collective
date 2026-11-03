"""The offer rules (spec 3.3) on real data: database rows mapped onto the allocator core's types.

The core (packages/allocator) decides; this module only builds its inputs from the database, so search (prompt 20),
the limits panel (prompt 22) and the seller agents (prompt 23) get the same numbers from the same rules.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openstall_allocator import Listing, QuoteRequest, SellerPolicy, capacity_available, lowest_allowed_price
from openstall_api.catalog import live_products
from openstall_api.models import OrderPart, PartStatus, Product, Seller
from openstall_api.models import QuoteRequest as QuoteRequestRow

# Capacity is counted this far ahead when nobody names a deadline: the story's request is always due in 30 days.
DEFAULT_DAYS_AHEAD = 30

# The shares that still take a maker's time: reserved at PayPal and not shipped yet. A pending share is only a draft
# until the human approves it, a captured one is made and shipped, and a released one is off (docs/decisions.md).
COMMITTED = frozenset({PartStatus.AUTHORIZED})

# What a policy JSON must hold. capacity_per_week may come from the listing instead (seller_policy).
REQUIRED_FIELDS = ("floor_price_usd", "max_discount_pct", "min_lead_days")


class PolicyError(ValueError):
    """A seller's policy JSON is missing, lacks a field, or holds a value the rules refuse."""


def default_deadline(today: date) -> date:
    return today + timedelta(days=DEFAULT_DAYS_AHEAD)


def seller_policy(seller: Seller, product: Product | None = None) -> SellerPolicy:
    """Her policy JSON (spec 3.3) as the core's SellerPolicy.

    capacity_per_week comes from the policy when it has one, else from the listing: onboarding asks for the price
    limits and lead days, and takes capacity from the listing (prompt 18). A missing field or a value the core refuses
    is a PolicyError naming the seller and the field.
    """
    raw = seller.policy_json
    if not raw:
        raise PolicyError(f"seller {seller.id} has no policy yet")
    if raw.get("seller_id", seller.id) != seller.id:
        raise PolicyError(f"seller {seller.id}'s policy belongs to {raw['seller_id']!r}")
    capacity = raw.get("capacity_per_week")
    if capacity is None and product is not None:
        capacity = product.capacity_per_week
    missing = [name for name in REQUIRED_FIELDS if raw.get(name) is None]
    if capacity is None:
        missing.append("capacity_per_week")
    if missing:
        raise PolicyError(f"seller {seller.id}'s policy is missing {', '.join(missing)}")
    try:
        return SellerPolicy(
            seller_id=seller.id,
            floor_price_usd=raw["floor_price_usd"],
            max_discount_pct=raw["max_discount_pct"],
            capacity_per_week=capacity,
            min_lead_days=raw["min_lead_days"],
            free_shipping_min_qty=raw.get("free_shipping_min_qty"),
        )
    except (TypeError, ValueError) as error:
        raise PolicyError(f"seller {seller.id}'s policy has a value the offer rules refuse: {error}") from error


def listing_of(product: Product) -> Listing:
    """The parts of a product the rules need: its list price and ship days (to US cities for now)."""
    return Listing(
        seller_id=product.seller_id,
        product_id=product.id,
        price_usd=product.price_usd,
        ship_days=product.ship_days,
    )


def quote_request_of(request: QuoteRequestRow) -> QuoteRequest:
    """A stored quote request as the core's QuoteRequest: what every offer made for it is checked against."""
    return QuoteRequest(
        quantity=request.quantity,
        max_unit_price=request.max_unit_price,
        deadline=request.deadline,
        request_id=request.id,
    )


def committed_units(session: Session, seller_ids: Iterable[str]) -> dict[str, int]:
    """Units each seller has promised and not shipped yet: her shares in COMMITTED, whatever their dates.

    Every reserved share counts, not only those due by the deadline asked about: she cannot make two orders' units in
    the same days, so this never promises time she has already sold (docs/decisions.md).
    """
    counts = dict.fromkeys(set(seller_ids), 0)
    if not counts:
        return counts
    rows = session.execute(
        select(OrderPart.seller_id, func.sum(OrderPart.quantity))
        .where(OrderPart.seller_id.in_(list(counts)), OrderPart.status.in_(COMMITTED))
        .group_by(OrderPart.seller_id)
    )
    for seller_id, units in rows:
        counts[seller_id] = int(units)
    return counts


def capacity_by_deadline(product: Product, today: date, deadline: date, committed: int = 0) -> int:
    """Units this product's maker can still make and ship by the deadline, after her committed units (spec 3.3).

    Production time and the listing's ship days both count, through the core's capacity_available. A deadline sooner
    than her minimum lead days gives 0, whatever her production time says: seller agents always offer delivery on
    the deadline, and the offer rules refuse a delivery that soon (too_soon), so she can supply nothing by it.
    """
    policy = seller_policy(product.seller, product)
    capacity = capacity_available(policy, listing_of(product), today, deadline, committed)
    return capacity if deadline >= today + timedelta(days=policy.min_lead_days) else 0


@dataclass(frozen=True)
class MakerLimits:
    """What the offer rules allow one live listing's maker by a deadline (spec 3.3): the lowest price her agent may
    offer, and the units she can still make and ship by then, after her committed units."""

    product: Product
    policy: SellerPolicy
    lowest_price: Decimal
    committed: int
    capacity: int


def limits_by_deadline(session: Session, today: date, deadline: date) -> tuple[list[MakerLimits], list[str]]:
    """Each live listing's limits by the deadline, from the core rules, oldest listing first.

    A maker whose policy cannot be read is left out, and the second list says why in words, so one bad policy does not
    hide everyone else's limits. This only reads.
    """
    products = live_products(session)
    committed = committed_units(session, {product.seller_id for product in products})
    limits: list[MakerLimits] = []
    unreadable: list[str] = []
    for product in products:
        try:
            policy = seller_policy(product.seller, product)
        except PolicyError as error:
            unreadable.append(f"{product.seller.name}'s limits cannot be checked: {error}.")
            continue
        units = committed[product.seller_id]
        limits.append(
            MakerLimits(
                product=product,
                policy=policy,
                lowest_price=lowest_allowed_price(policy, listing_of(product)),
                committed=units,
                capacity=capacity_by_deadline(product, today, deadline, units),
            )
        )
    return limits, unreadable
