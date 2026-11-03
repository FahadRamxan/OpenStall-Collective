"""Orders over HTTP, for the approval page: the order, its total check, and checkout at PayPal."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from openstall_allocator import usd
from openstall_api.adapters import AdapterRegistry, AdapterUnavailable, get_registry
from openstall_api.catalog import photo_path
from openstall_api.db import get_session
from openstall_api.models import DataSource, Order, OrderPart, OrderStatus, PartStatus, Passport
from openstall_api.orders import server_total
from openstall_api.payments import OrderNotFound, WrongStatus, start_checkout
from openstall_paypal import PaymentError, PaymentUnavailable
from openstall_trust import trust_score

router = APIRouter(prefix="/api", tags=["orders"])

SessionDep = Annotated[Session, Depends(get_session)]
RegistryDep = Annotated[AdapterRegistry, Depends(get_registry)]


class SellerBrief(BaseModel):
    id: str
    name: str
    city: str | None
    country: str | None


class PartOut(BaseModel):
    id: str
    reference_id: str
    seller: SellerBrief
    product_title: str | None
    photo: str | None
    quantity: int
    unit_price_usd: Decimal
    amount_usd: Decimal
    delivery_date: date | None
    status: PartStatus
    trust_score: Decimal | None
    trust_data_source: DataSource | None


class RequestOut(BaseModel):
    """What the buyer agent asked for."""

    summary: str
    quantity: int
    max_unit_price: Decimal
    deadline: date
    ship_to: str


class OrderOut(BaseModel):
    id: str
    status: OrderStatus
    total_usd: Decimal
    units: int
    created_at: datetime
    parent_order_id: str | None
    request: RequestOut | None
    parts: list[PartOut]


def _part(session: Session, part: OrderPart) -> PartOut:
    passport = session.get(Passport, part.seller_id)
    metrics = passport.metrics_json if passport else None
    product = part.product
    return PartOut(
        id=part.id,
        reference_id=part.reference_id,
        seller=SellerBrief(
            id=part.seller.id, name=part.seller.name, city=part.seller.city, country=part.seller.country
        ),
        product_title=product.title if product else None,
        photo=photo_path(product.photos_json[0]) if product and product.photos_json else None,
        quantity=part.quantity,
        unit_price_usd=part.unit_price_usd,
        amount_usd=part.amount_usd,
        delivery_date=part.delivery_date,
        status=part.status,
        trust_score=(
            trust_score(metrics["on_time_rate"], metrics["dispute_rate"], metrics["photo_originality"])
            if metrics
            else None
        ),
        trust_data_source=passport.data_source if passport else None,
    )


def order_out(session: Session, order: Order) -> OrderOut:
    request = order.request
    items = request.items_json if request else []
    summary = next((item.get("query") for item in items if isinstance(item, dict) and item.get("query")), None)
    return OrderOut(
        id=order.id,
        status=order.status,
        total_usd=server_total(order),
        units=sum(part.quantity for part in order.parts),
        created_at=order.created_at,
        parent_order_id=order.parent_order_id,
        request=(
            RequestOut(
                summary=summary or f"{request.quantity} items",
                quantity=request.quantity,
                max_unit_price=request.max_unit_price,
                deadline=request.deadline,
                ship_to=request.ship_to,
            )
            if request
            else None
        ),
        parts=[_part(session, part) for part in order.parts],
    )


def _load(session: Session, order_id: str) -> Order:
    order = session.get(
        Order,
        order_id,
        options=[selectinload(Order.parts).selectinload(OrderPart.seller), selectinload(Order.request)],
    )
    if order is None:
        raise HTTPException(status_code=404, detail=f"There is no order called {order_id!r}.")
    return order


@router.get("/orders/{order_id}")
def get_order(order_id: str, session: SessionDep) -> OrderOut:
    return order_out(session, _load(session, order_id))


class TotalIn(BaseModel):
    total_usd: Decimal


class TotalCheck(BaseModel):
    total_usd: Decimal


@router.post("/orders/{order_id}/verify-total")
def verify_total(order_id: str, body: TotalIn, session: SessionDep) -> TotalCheck:
    """Spec 3.5: never trust a total from an agent or a browser. A different total is refused with 409."""
    order = _load(session, order_id)
    expected = server_total(order)
    try:
        claimed = usd(body.total_usd)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if claimed != expected:
        raise HTTPException(
            status_code=409,
            detail=f"The total is ${expected:,.2f}, not ${claimed:,.2f}. Totals are worked out on the server.",
        )
    return TotalCheck(total_usd=expected)


class CheckoutOut(BaseModel):
    paypal_order_id: str
    approval_url: str


@contextmanager
def payment_errors() -> Iterator[None]:
    """Payment failures as HTTP errors a person can read. When one is raised, nothing was reserved or paid."""
    try:
        yield
    except OrderNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except WrongStatus as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except AdapterUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except PaymentUnavailable:
        raise HTTPException(
            status_code=503, detail="PayPal did not answer, so nothing was reserved or paid. Try again in a moment."
        ) from None
    except PaymentError as error:
        raise HTTPException(
            status_code=502, detail=f"PayPal refused this ({error.issue}), so nothing was reserved or paid."
        ) from None


@router.post("/orders/{order_id}/checkout")
def checkout(order_id: str, session: SessionDep, registry: RegistryDep) -> CheckoutOut:
    """Spec 3.5: one PayPal order for the whole amount. Approving it at PayPal only reserves the money."""
    with payment_errors():
        result = start_checkout(session, order_id, registry.payment_gateway, registry.settings.WEB_BASE_URL)
    session.commit()
    return CheckoutOut(paypal_order_id=result.paypal_order_id, approval_url=result.approval_url)
