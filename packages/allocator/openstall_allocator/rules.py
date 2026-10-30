"""The rules that keep seller agents inside their limits (spec 3.3).

Plain code is the only authority: a model may propose a price, but only these checks decide.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import ROUND_CEILING, Decimal
from typing import Protocol, runtime_checkable

from openstall_allocator.types import (
    CENT,
    Listing,
    Offer,
    OfferCheck,
    QuoteRequest,
    RejectionReason,
    SellerPolicy,
    _count,
    _day,
)

HUNDRED = Decimal(100)


@runtime_checkable
class Clock(Protocol):
    """Where "today" comes from, so tests and the demo can fix the date."""

    def today(self) -> date: ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Today's date in one time zone, UTC by default, so every server and CI agree on it."""

    tz: tzinfo = timezone.utc

    def today(self) -> date:
        return datetime.now(self.tz).date()


@dataclass(frozen=True, slots=True)
class FixedClock:
    """The same day every time, for tests and for recording the demo."""

    day: date

    def __post_init__(self) -> None:
        _day("day", self.day)

    def today(self) -> date:
        return self.day


def capacity_available(
    policy: SellerPolicy,
    listing: Listing,
    today: date,
    deadline: date,
    committed_units: int = 0,
) -> int:
    """Units the seller can still make and ship by the deadline, exactly as in spec 3.3.

    committed_units counts this seller's open order parts in the same window.
    """
    _day("today", today)
    _day("deadline", deadline)
    _count("committed_units", committed_units)
    production_days = (deadline - today).days - listing.ship_days
    return max(0, policy.capacity_per_week * production_days // 7 - committed_units)


def lowest_allowed_price(policy: SellerPolicy, listing: Listing) -> Decimal:
    """The floor, or the list price less the maximum discount, whichever is higher.

    Rounded up to the cent, so a whole-cent offer can never land below the real limit.
    """
    discounted = listing.price_usd * (HUNDRED - policy.max_discount_pct) / HUNDRED
    return max(policy.floor_price_usd, discounted.quantize(CENT, rounding=ROUND_CEILING))


def is_valid_offer(
    offer: Offer,
    policy: SellerPolicy,
    listing: Listing,
    request: QuoteRequest,
    today: date,
    *,
    committed_units: int = 0,
) -> OfferCheck:
    """Check an offer against the seller's limits and the buyer's request (spec 3.3).

    Reports the first rule that fails, in the order of RejectionReason. Capacity is measured to the
    buyer's deadline, as in the spec, because seller agents always offer delivery on the deadline.
    """
    _day("today", today)
    if not offer.seller_id == policy.seller_id == listing.seller_id:
        raise ValueError(
            f"offer, policy and listing must belong to one seller, got "
            f"{offer.seller_id!r}, {policy.seller_id!r} and {listing.seller_id!r}"
        )
    capacity = capacity_available(policy, listing, today, request.deadline, committed_units)
    if offer.unit_price < lowest_allowed_price(policy, listing):
        return OfferCheck(valid=False, reason=RejectionReason.BELOW_FLOOR)
    if offer.unit_price > request.max_unit_price:
        return OfferCheck(valid=False, reason=RejectionReason.OVER_BUYER_CAP)
    if offer.quantity > capacity:
        return OfferCheck(valid=False, reason=RejectionReason.OVER_CAPACITY)
    if offer.delivery_date < today + timedelta(days=policy.min_lead_days):
        return OfferCheck(valid=False, reason=RejectionReason.TOO_SOON)
    if offer.delivery_date > request.deadline:
        return OfferCheck(valid=False, reason=RejectionReason.AFTER_DEADLINE)
    return OfferCheck(valid=True)
