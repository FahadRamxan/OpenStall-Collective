"""Payments for orders (spec 3.5, pay-on-proof): send the human to PayPal to approve the whole order, reserve it when
they come back, then pay or release each seller's share. Every PayPal call goes through the payment gateway.
"""

from sqlalchemy.orm import Session, selectinload

from openstall_api.events import EventType, record_event
from openstall_api.models import Order, OrderPart, OrderStatus
from openstall_api.orders import move_order
from openstall_paypal import Checkout, CheckoutPart, CheckoutRequest, PaymentGateway

# Only these orders can be sent to PayPal: a repeated press of Approve finds the order waiting for approval.
CHECKOUT_FROM = frozenset({OrderStatus.DRAFT, OrderStatus.AWAITING_APPROVAL})

STATUS_WORDS = {
    OrderStatus.DRAFT: "a draft",
    OrderStatus.AWAITING_APPROVAL: "waiting for approval",
    OrderStatus.AUTHORIZED: "reserved at PayPal",
    OrderStatus.PARTLY_SHIPPED: "partly shipped",
    OrderStatus.SHIPPED: "shipped",
    OrderStatus.COMPLETED: "completed",
    OrderStatus.CANCELLED: "cancelled",
}


class OrderNotFound(LookupError):
    pass


class WrongStatus(ValueError):
    """The order's status does not allow this step, such as sending a reserved order to PayPal again."""


def load_order(session: Session, order_id: str) -> Order:
    order = session.get(Order, order_id, options=[selectinload(Order.parts).selectinload(OrderPart.seller)])
    if order is None:
        raise OrderNotFound(f"There is no order called {order_id!r}.")
    return order


def share_description(part: OrderPart) -> str:
    """How a share reads at PayPal, for example "12 × Hand-embroidered cushion cover, Amina"."""
    title = part.product.title if part.product else "items"
    return f"{part.quantity} × {title}, {part.seller.name}"


def checkout_request(order: Order, web_base_url: str) -> CheckoutRequest:
    """The whole order for PayPal: one share per seller, amounts from our own rows, never from a caller."""
    return CheckoutRequest(
        order_id=order.id,
        parts=tuple(
            CheckoutPart(
                reference_id=part.reference_id,
                amount_usd=part.amount_usd,
                description=share_description(part),
                payee_merchant_id=part.seller.paypal_merchant_id,
                payee_email=part.seller.paypal_email,
            )
            for part in order.parts
        ),
        return_url=f"{web_base_url}/approve/{order.id}/return",
        cancel_url=f"{web_base_url}/approve/{order.id}?cancelled=1",
    )


def start_checkout(session: Session, order_id: str, gateway: PaymentGateway, web_base_url: str) -> Checkout:
    """Create the PayPal order for the whole amount and say where the human approves it. The caller commits.

    Pressing Approve again returns the same PayPal order (the gateway's idempotency key is our order id). If the
    human already approved it and only the reservation is missing, they go straight to the return page instead.
    """
    order = load_order(session, order_id)
    if order.status not in CHECKOUT_FROM:
        raise WrongStatus(f"Order {order.id} is {STATUS_WORDS[order.status]}, so it cannot go to PayPal again.")
    request = checkout_request(order, web_base_url)
    checkout = gateway.create_checkout(request)
    repeated = order.paypal_order_id == checkout.paypal_order_id
    if order.status == OrderStatus.DRAFT:
        move_order(order, OrderStatus.AWAITING_APPROVAL)
    elif repeated and gateway.get_order(checkout.paypal_order_id).status == "APPROVED":
        return Checkout(checkout.paypal_order_id, request.return_url)
    order.paypal_order_id = checkout.paypal_order_id
    if not repeated:
        makers = len(order.parts)
        record_event(
            session,
            EventType.ORDER_CHECKOUT_STARTED,
            f"Order {order.id} went to PayPal: ${request.total_usd:,.2f} to reserve for {makers} "
            f"{'maker' if makers == 1 else 'makers'}",
            entity_id=order.id,
            payload={"paypal_order_id": checkout.paypal_order_id, "total_usd": request.total_usd},
        )
    return checkout
