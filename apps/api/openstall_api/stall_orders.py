"""Buying from a maker's stall (spec 3.9 and plan M13, prompt 42): a person buys one listing at her list price, with
PayPal's own buttons on her stall page (the JS SDK), or simulated PayPal in test mode.

The order is like any other, with one share: drafted here, its total worked out by the server; sent to PayPal by
checkout (intent AUTHORIZE, so the money is only reserved); reserved when PayPal says the person approved it; the maker
told in her language; and paid on proof of shipping. Nothing is negotiated: a person at a stall pays her list price.
Her delivery date is the first day she can make the quantity and ship it, by the offer rules: her lead time, her weekly
capacity, her ship days, and the units she already owes. The buyer's city goes on the order, so she is told where it
ships.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from openstall_api.catalog import ID_PATTERN
from openstall_api.models import Order, Product, ProductStatus
from openstall_api.offer_rules import PolicyError, capacity_by_deadline, committed_units
from openstall_api.orders import DraftPart, create_draft_order

MAX_UNITS = 50  # a stall sells to a person; bigger orders go through a quote, where the collective can split them
HORIZON_DAYS = 120  # the furthest out a stall offers a delivery date
SOURCE = "stall"


class StallOrderError(ValueError):
    """The purchase cannot be drafted as asked. The message says why, in words a buyer can act on."""


def earliest_delivery(session: Session, product: Product, quantity: int, today: date) -> date | None:
    """The first day she can make `quantity` more and have them delivered, or None within HORIZON_DAYS."""
    owed = committed_units(session, [product.seller_id]).get(product.seller_id, 0)
    for days in range(1, HORIZON_DAYS + 1):
        day = today + timedelta(days=days)
        if capacity_by_deadline(product, today, day, owed) >= quantity:
            return day
    return None


def stall_order(session: Session, product_id: str, quantity: int, ship_to: str, today: date) -> Order:
    """A draft order for `quantity` of one live listing at her list price, shipping to `ship_to`. Raises
    StallOrderError, in words, for a listing not for sale, a quantity she cannot make, or no city. The caller
    commits."""
    product = session.get(Product, product_id) if ID_PATTERN.fullmatch(product_id) else None
    if product is None or product.status != ProductStatus.LIVE:
        raise StallOrderError(f"There is no listing for sale called {product_id!r}.")
    name = product.seller.name
    if isinstance(quantity, bool) or not 1 <= quantity <= MAX_UNITS:
        raise StallOrderError(
            f"Choose from 1 to {MAX_UNITS} at a stall. For more, ask OpenStall for a quote: the collective can split "
            "it across makers."
        )
    city = " ".join(ship_to.split())
    if not city:
        raise StallOrderError("Say which city it ships to.")
    try:
        day = earliest_delivery(session, product, quantity, today)
    except PolicyError:
        raise StallOrderError(f"{name} has not set her limits yet, so her stall cannot take orders.") from None
    if day is None:
        raise StallOrderError(f"{name} cannot make {quantity} more within {HORIZON_DAYS} days. Choose fewer.")
    order = create_draft_order(
        session, [DraftPart(product.seller_id, product.id, quantity, product.price_usd, day)]
    )
    order.source = SOURCE
    order.ship_to = city[:120]
    return order
