"""The Collective: one order split across several sellers, cheapest first (spec 3.4).

Plain code decides the split; a model only explains the result in words.
"""

import math
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from openstall_allocator.types import Amount, Offer, Plan, PlanLine, _count, _day, _decimal


def allocate(
    offers: Iterable[Offer],
    quantity: int,
    deadline: date,
    fair_share: Amount | None = None,
) -> Plan:
    """Fill the quantity from the cheapest valid offers first, each up to its own quantity.

    Offers delivered after the deadline are left out. Ties go to the earlier delivery, then the
    lower seller id, so the same offers always give the same plan. Each seller makes at most one
    offer, because capacity belongs to the seller.

    fair_share, for example 0.3, caps each seller at that share of the quantity, rounded up to a
    whole unit. It is off by default, as in the demo.

    When the offers cannot cover the quantity, the plan holds what is possible, with
    complete=False, the shortfall and a plain reason.
    """
    offers = list(offers)
    _count("quantity", quantity)
    _day("deadline", deadline)
    _check_offers(offers)
    cap = _seller_cap(fair_share, quantity)

    eligible = sorted(
        (offer for offer in offers if offer.delivery_date <= deadline),
        key=lambda offer: (offer.unit_price, offer.delivery_date, offer.seller_id),
    )
    lines: list[PlanLine] = []
    remaining = quantity
    for offer in eligible:
        if remaining == 0:
            break
        limit = offer.quantity if cap is None else min(offer.quantity, cap)
        take = min(limit, remaining)
        lines.append(
            PlanLine(
                seller_id=offer.seller_id,
                quantity=take,
                unit_price=offer.unit_price,
                line_total=offer.unit_price * take,
                delivery_date=offer.delivery_date,
                offer_id=offer.offer_id,
            )
        )
        remaining -= take

    supplied = quantity - remaining
    reason = None
    if remaining:
        capped = cap is not None and any(offer.quantity > cap for offer in eligible)
        reason = _shortfall_reason(
            supplied=supplied,
            quantity=quantity,
            deadline=deadline,
            offered=len(offers),
            late=len(offers) - len(eligible),
            cap=cap if capped else None,
        )
    return Plan(
        lines=tuple(lines),
        total_quantity=supplied,
        total_cost=sum((line.line_total for line in lines), Decimal("0.00")),
        complete=remaining == 0,
        shortfall=remaining,
        reason=reason,
    )


def _check_offers(offers: list[Offer]) -> None:
    sellers: set[str] = set()
    for offer in offers:
        if not isinstance(offer, Offer):
            raise TypeError(f"offers must be Offer objects, not {type(offer).__name__}")
        if offer.seller_id in sellers:
            raise ValueError(f"more than one offer from {offer.seller_id}; pass each seller's best offer")
        sellers.add(offer.seller_id)


def _seller_cap(fair_share: Amount | None, quantity: int) -> int | None:
    """The most units one seller may take, or None when fair share is off."""
    if fair_share is None:
        return None
    share = _decimal("fair_share", fair_share)
    if not share.is_finite() or not 0 < share <= 1:
        raise ValueError(f"fair_share must be above 0 and at most 1, got {fair_share!r}")
    # Decimal keeps 0.3 x 40 at exactly 12; in floats it is 12.000000000000002, which rounds up to 13.
    return math.ceil(share * quantity)


def _shortfall_reason(
    *, supplied: int, quantity: int, deadline: date, offered: int, late: int, cap: int | None
) -> str:
    """A plain sentence for the buyer: how many units are possible, and why not more."""
    reason = f"Only {supplied} of {quantity} units can be supplied by {deadline.isoformat()}."
    if not offered:
        return f"{reason} No seller made an offer."
    if late == 1:
        reason += " 1 offer delivers after the deadline and was left out."
    elif late:
        reason += f" {late} offers deliver after the deadline and were left out."
    if cap is not None:
        reason += f" Fair share caps each seller at {cap} units."
    return reason
