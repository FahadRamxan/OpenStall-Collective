"""The stall page's PayPal buttons (prompt 42): POST /api/stall-orders drafts a person's purchase of one listing, which
then goes through the same checkout and reserve as any order; GET /api/paypal/config tells the page how to show PayPal.

In sandbox mode the page loads PayPal's JS SDK with the sandbox client id (a public value: it is in the script's
address on every page that shows PayPal's buttons); the secret never leaves the API. Test mode has no PayPal to load,
so the page shows a simulated PayPal button that goes through the simulated PayPal page instead.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_api import quotes
from openstall_api.db import get_session
from openstall_api.orders_api import OrderOut, _load, order_out
from openstall_api.settings import Settings, get_settings
from openstall_api.stall_orders import MAX_UNITS, StallOrderError, stall_order
from openstall_paypal import sandbox_host

router = APIRouter(prefix="/api", tags=["stall"])

SessionDep = Annotated[Session, Depends(get_session)]


class StallOrderIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=MAX_UNITS)
    ship_to: str = Field(min_length=1, max_length=120, description="The city it ships to.")


@router.post("/stall-orders", status_code=201)
def create_stall_order(body: StallOrderIn, session: SessionDep) -> OrderOut:
    """A person's purchase from a stall, as a draft order with one share at her list price. Nothing is reserved until
    the person approves it at PayPal (POST /api/orders/{id}/checkout, then /reserve)."""
    try:
        order = stall_order(session, body.product_id, body.quantity, body.ship_to, quotes.clock.today())
    except StallOrderError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return order_out(session, _load(session, order.id))


class PayPalConfig(BaseModel):
    """How the stall page shows PayPal."""

    mode: Literal["fake", "sandbox"]
    # The sandbox app's client id, for PayPal's JS SDK; None in test mode, or when sandbox mode has none set.
    client_id: str | None
    currency: Literal["USD"] = "USD"
    intent: Literal["authorize"] = "authorize"  # approving reserves the money; each share is captured on proof
    # Venmo's button, for a buyer in the US (prompt 57), and Pay Later's, off until it is proven with intent authorize.
    venmo: bool = False
    pay_later: bool = False
    # PayPal's sandbox shows Venmo only to a buyer it takes to be in the US, so the JS SDK is told so there; never on
    # PayPal's live host, where PayPal works out the buyer's country itself.
    buyer_country: Literal["US"] | None = None


@router.get("/paypal/config")
def paypal_config(settings: Annotated[Settings, Depends(get_settings)]) -> PayPalConfig:
    if settings.OPENSTALL_MODE == "fake":
        return PayPalConfig(mode="fake", client_id=None, venmo=settings.PAYPAL_VENMO)
    return PayPalConfig(
        mode="sandbox",
        client_id=settings.PAYPAL_CLIENT_ID or None,
        venmo=settings.PAYPAL_VENMO,
        pay_later=settings.PAYPAL_PAY_LATER,
        buyer_country="US" if sandbox_host(settings.PAYPAL_API_BASE) else None,
    )
