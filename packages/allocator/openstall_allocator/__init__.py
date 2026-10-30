"""Offer rules (spec 3.3) and the order allocator (spec 3.4), in plain code.

The model only proposes prices and explains results; these functions decide.
"""

from openstall_allocator.allocate import allocate
from openstall_allocator.rules import (
    Clock,
    FixedClock,
    SystemClock,
    capacity_available,
    is_valid_offer,
    lowest_allowed_price,
)
from openstall_allocator.types import (
    CENT,
    Amount,
    Listing,
    Offer,
    OfferCheck,
    Plan,
    PlanLine,
    QuoteRequest,
    RejectionReason,
    SellerPolicy,
    usd,
)

__all__ = [
    "CENT",
    "Amount",
    "Clock",
    "FixedClock",
    "Listing",
    "Offer",
    "OfferCheck",
    "Plan",
    "PlanLine",
    "QuoteRequest",
    "RejectionReason",
    "SellerPolicy",
    "SystemClock",
    "allocate",
    "capacity_available",
    "is_valid_offer",
    "lowest_allowed_price",
    "usd",
]
