"""Orders (spec 3.5 and section 4): one share per seller, totals worked out here and never taken from a caller, and
the only allowed status moves.

Pay-on-proof shapes the statuses: approval authorizes the whole order, and each seller's share is captured on its own
when her tracking is confirmed, or released if she drops out.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from openstall_allocator import usd
from openstall_api.events import EventType, record_event
from openstall_api.models import Order, OrderPart, OrderStatus, PartStatus

CENT = Decimal("0.01")

ORDER_MOVES: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT: frozenset({OrderStatus.AWAITING_APPROVAL, OrderStatus.CANCELLED}),
    OrderStatus.AWAITING_APPROVAL: frozenset({OrderStatus.AUTHORIZED, OrderStatus.CANCELLED}),
    # Shipped straight away when every share is paid at once; cancelled when every share is released.
    OrderStatus.AUTHORIZED: frozenset({OrderStatus.PARTLY_SHIPPED, OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.PARTLY_SHIPPED: frozenset({OrderStatus.SHIPPED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.COMPLETED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}

PART_MOVES: dict[PartStatus, frozenset[PartStatus]] = {
    PartStatus.PENDING: frozenset({PartStatus.AUTHORIZED, PartStatus.RELEASED}),
    PartStatus.AUTHORIZED: frozenset({PartStatus.CAPTURED, PartStatus.RELEASED}),  # paid on proof, or dropped out
    PartStatus.CAPTURED: frozenset({PartStatus.DELIVERED}),
    PartStatus.DELIVERED: frozenset(),
    PartStatus.RELEASED: frozenset(),
}


class IllegalMove(ValueError):
    """A status change the rules do not allow, such as capturing a released share."""


def move_order(order: Order, to: OrderStatus) -> None:
    if to not in ORDER_MOVES[order.status]:
        raise IllegalMove(f"order {order.id} cannot go from {order.status.value} to {to.value}")
    order.status = to


def move_part(part: OrderPart, to: PartStatus) -> None:
    if to not in PART_MOVES[part.status]:
        raise IllegalMove(f"share {part.reference_id} of order {part.order_id} cannot go from "
                          f"{part.status.value} to {to.value}")
    part.status = to


@dataclass(frozen=True)
class DraftPart:
    """One seller's share, as the allocator planned it. Prices are per unit; totals are worked out here."""

    seller_id: str
    product_id: str | None
    quantity: int
    unit_price: Decimal | str | int
    delivery_date: date


def line_total(quantity: int, unit_price: Decimal) -> Decimal:
    return (unit_price * quantity).quantize(CENT, rounding=ROUND_HALF_UP)


def create_draft_order(
    session: Session,
    parts: list[DraftPart],
    *,
    order_id: str | None = None,
    request_id: str | None = None,
    parent_order_id: str | None = None,
) -> Order:
    """A draft order with one share per seller, numbered op_001, op_002 ... and a total worked out on the server."""
    if not parts:
        raise ValueError("an order needs at least one seller's share")
    sellers = [part.seller_id for part in parts]
    if len(set(sellers)) != len(sellers):
        raise ValueError("each seller has one share per order; merge her lines first")
    order = Order(request_id=request_id, parent_order_id=parent_order_id, status=OrderStatus.DRAFT)
    if order_id is not None:
        order.id = order_id
    total = Decimal("0.00")
    for number, part in enumerate(parts, start=1):
        if isinstance(part.quantity, bool) or not isinstance(part.quantity, int) or part.quantity < 1:
            raise ValueError(f"a share needs a whole quantity of at least 1, got {part.quantity!r}")
        unit_price = usd(part.unit_price)
        amount = line_total(part.quantity, unit_price)
        total += amount
        order.parts.append(
            OrderPart(
                seller_id=part.seller_id,
                product_id=part.product_id,
                reference_id=f"op_{number:03d}",
                quantity=part.quantity,
                unit_price_usd=unit_price,
                amount_usd=amount,
                delivery_date=part.delivery_date,
                status=PartStatus.PENDING,
            )
        )
    order.total_usd = total
    order.created_at = datetime.now(UTC)
    session.add(order)
    session.flush()
    units = sum(part.quantity for part in parts)
    kind = "Top-up order" if parent_order_id else "Draft order"
    makers = "1 maker" if len(parts) == 1 else f"{len(parts)} makers"
    record_event(
        session,
        EventType.ORDER_DRAFTED,
        f"{kind} {order.id}: {units} units from {makers}, ${total:,.2f}",
        entity_id=order.id,
        payload={"total_usd": total, "units": units, "sellers": sellers},
    )
    return order


def server_total(order: Order) -> Decimal:
    """The total from the shares themselves, whatever any caller claims."""
    return sum((part.amount_usd for part in order.parts), Decimal("0.00"))
