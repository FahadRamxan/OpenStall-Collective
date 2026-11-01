"""Plain inputs and outputs for the offer rules and the allocator (spec 3.3 and 3.4).

Nothing here touches the database, the web or a model, so the API can map its own rows onto these
types. Every type checks its values when it is built. Money is a Decimal in USD with exactly 2 places.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

CENT = Decimal("0.01")

# What usd() accepts. Floats are read through their shortest repr, so 29.99 stays 29.99.
Amount = Decimal | int | str | float


def usd(value: Amount) -> Decimal:
    """Return an amount in USD with exactly 2 places, for example usd("18") == Decimal("18.00").

    Negative, non-finite and sub-cent amounts raise ValueError, so a price is never rounded silently.
    """
    amount = _decimal("amount", value)
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"an amount must be finite and not negative, got {value!r}")
    try:
        cents = amount.quantize(CENT)
    except InvalidOperation:
        raise ValueError(f"amount is too large: {value!r}") from None
    if cents != amount:
        raise ValueError(f"an amount must be whole cents, got {value!r}")
    return cents.copy_abs()  # turns -0.00 into 0.00


class RejectionReason(StrEnum):
    """Why an offer is invalid. The rules are checked in this order and the first failure is reported."""

    BELOW_FLOOR = "below_floor"  # under the lowest allowed price: the floor or the maximum discount
    OVER_BUYER_CAP = "over_buyer_cap"  # over the buyer's maximum unit price
    OVER_CAPACITY = "over_capacity"  # more units than the seller can make and ship by the deadline
    TOO_SOON = "too_soon"  # delivery sooner than the seller's minimum lead days
    AFTER_DEADLINE = "after_deadline"  # delivery after the buyer's deadline


@dataclass(frozen=True, slots=True, kw_only=True)
class SellerPolicy:
    """A seller's limits, set by chat and confirmed by the seller (spec 3.3)."""

    seller_id: str
    floor_price_usd: Decimal
    max_discount_pct: Decimal  # 15 means 15%
    capacity_per_week: int
    min_lead_days: int
    free_shipping_min_qty: int | None = None  # part of the policy JSON; the rules do not use it

    def __post_init__(self) -> None:
        _ident("seller_id", self.seller_id)
        _count("capacity_per_week", self.capacity_per_week)
        _count("min_lead_days", self.min_lead_days)
        if self.free_shipping_min_qty is not None:
            _count("free_shipping_min_qty", self.free_shipping_min_qty)
        _set(
            self,
            floor_price_usd=usd(self.floor_price_usd),
            max_discount_pct=_percent("max_discount_pct", self.max_discount_pct),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Listing:
    """The parts of a product listing that the rules need."""

    seller_id: str
    price_usd: Decimal  # the list price
    ship_days: int  # days in transit to the buyer
    product_id: str | None = None

    def __post_init__(self) -> None:
        _ident("seller_id", self.seller_id)
        _count("ship_days", self.ship_days)
        if self.product_id is not None:
            _ident("product_id", self.product_id)
        _set(self, price_usd=usd(self.price_usd))


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteRequest:
    """What the buyer agent asked for (spec 3.2, request_quote)."""

    quantity: int
    max_unit_price: Decimal
    deadline: date
    request_id: str | None = None

    def __post_init__(self) -> None:
        _count("quantity", self.quantity, minimum=1)
        _day("deadline", self.deadline)
        if self.request_id is not None:
            _ident("request_id", self.request_id)
        _set(self, max_unit_price=usd(self.max_unit_price))


@dataclass(frozen=True, slots=True, kw_only=True)
class Offer:
    """One seller's offer. Code sets the quantity and delivery date; the model proposes the price."""

    seller_id: str
    unit_price: Decimal
    quantity: int
    delivery_date: date
    offer_id: str | None = None

    def __post_init__(self) -> None:
        _ident("seller_id", self.seller_id)
        _count("quantity", self.quantity, minimum=1)
        _day("delivery_date", self.delivery_date)
        if self.offer_id is not None:
            _ident("offer_id", self.offer_id)
        _set(self, unit_price=usd(self.unit_price))


@dataclass(frozen=True, slots=True)
class OfferCheck:
    """The verdict on one offer: valid, or invalid with the reason.

    It is falsy when invalid, and unpacks as `valid, reason = check`.
    """

    valid: bool
    reason: RejectionReason | None = None

    def __post_init__(self) -> None:
        if self.valid != (self.reason is None):
            raise ValueError("a valid offer has no reason, and an invalid one needs one")
        if self.reason is not None:
            _set(self, reason=RejectionReason(self.reason))  # also accepts the stored string

    def __bool__(self) -> bool:
        return self.valid

    def __iter__(self) -> Iterator[bool | RejectionReason | None]:
        yield self.valid
        yield self.reason


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanLine:
    """One seller's share of the order."""

    seller_id: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    offer_id: str | None = None

    def __post_init__(self) -> None:
        _ident("seller_id", self.seller_id)
        _count("quantity", self.quantity, minimum=1)
        _day("delivery_date", self.delivery_date)
        _set(self, unit_price=usd(self.unit_price), line_total=usd(self.line_total))
        if self.line_total != self.unit_price * self.quantity:
            raise ValueError(f"line_total {self.line_total} is not {self.quantity} x {self.unit_price}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    """How the order is split, in allocation order (cheapest first).

    A plan that cannot fill the order has complete=False, the shortfall in units and a plain reason.
    The totals must match the lines, so a changed total is refused.
    """

    lines: tuple[PlanLine, ...]
    total_quantity: int
    total_cost: Decimal
    complete: bool
    shortfall: int
    reason: str | None = None

    def __post_init__(self) -> None:
        lines = tuple(self.lines)
        _count("total_quantity", self.total_quantity)
        _count("shortfall", self.shortfall)
        _set(self, lines=lines, total_cost=usd(self.total_cost))
        if self.total_quantity != sum(line.quantity for line in lines):
            raise ValueError("total_quantity does not match the lines")
        if self.total_cost != sum((line.line_total for line in lines), Decimal("0.00")):
            raise ValueError("total_cost does not match the lines")
        if self.complete != (self.shortfall == 0):
            raise ValueError("a plan is complete exactly when there is no shortfall")
        if not self.complete and not self.reason:
            raise ValueError("a partial plan needs a reason")

    @property
    def requested_quantity(self) -> int:
        return self.total_quantity + self.shortfall

    def quantities(self) -> dict[str, int]:
        """Units per seller id, in plan order."""
        return {line.seller_id: line.quantity for line in self.lines}


def _set(obj: object, **values: object) -> None:
    """Store normalised values on a frozen dataclass while it is being built."""
    for name, value in values.items():
        object.__setattr__(obj, name, value)


def _decimal(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str | float):
        raise TypeError(f"{name} must be a Decimal, int, str or float, not {type(value).__name__}")
    try:
        return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{name} is not a number: {value!r}") from None


def _percent(name: str, value: object) -> Decimal:
    pct = _decimal(name, value)
    # At most 2 places keeps every price calculation exact in Decimal's default 28 digits.
    if not pct.is_finite() or not 0 <= pct <= 100 or pct != pct.quantize(CENT):
        raise ValueError(f"{name} must be from 0 to 100 with at most 2 decimal places, got {value!r}")
    return pct


def _count(name: str, value: object, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, not {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def _day(name: str, value: object) -> date:
    # A datetime is a date too, but mixing them makes (deadline - today).days drop part of a day.
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{name} must be a date, not {type(value).__name__}")
    return value


def _ident(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value
