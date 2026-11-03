"""The simulated PayPal page's API, in fake mode only: the order as the buyer sees it at "PayPal", and their approval.

The page stands in for PayPal so the whole flow runs offline and in tests. It never pretends to be PayPal: the web
page is titled "Simulated PayPal (test mode)". In sandbox mode these endpoints do not exist.
"""

from decimal import Decimal
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from openstall_api.adapters import AdapterRegistry, get_registry
from openstall_api.events_api import fake_mode_only
from openstall_api.webhooks import deliver_fake_webhooks
from openstall_paypal import FakeGateway, FakeOrderView, PaymentError, PayPalOrderStatus

router = APIRouter(prefix="/api/dev/fake-paypal", tags=["dev"], dependencies=[Depends(fake_mode_only)])

FAKE_PAYER_ID = "FAKEBUYER01"


class FakeShare(BaseModel):
    reference_id: str
    description: str
    amount_usd: Decimal


class FakePayPalOrder(BaseModel):
    token: str
    status: PayPalOrderStatus
    order_id: str
    total_usd: Decimal
    shares: list[FakeShare]
    cancel_url: str


class Redirect(BaseModel):
    redirect_url: str


def _gateway(registry: Annotated[AdapterRegistry, Depends(get_registry)]) -> FakeGateway:
    gateway = registry.payment_gateway
    if not isinstance(gateway, FakeGateway):  # fake_mode_only already stops this; a second guard costs nothing
        raise HTTPException(status_code=404)
    return gateway


GatewayDep = Annotated[FakeGateway, Depends(_gateway)]


def _view(gateway: FakeGateway, token: str, approve: bool = False) -> FakeOrderView:
    try:
        return gateway.approve(token) if approve else gateway.view(token)
    except PaymentError:
        # Fake orders live in memory, so a restarted API forgets them.
        raise HTTPException(
            status_code=404,
            detail="This test checkout has expired or never existed. Go back to the order and press Approve again.",
        ) from None


@router.get("/{token}")
def view_order(token: str, gateway: GatewayDep) -> FakePayPalOrder:
    view = _view(gateway, token)
    return FakePayPalOrder(
        token=token,
        status=view.status,
        order_id=view.request.order_id,
        total_usd=view.request.total_usd,
        shares=[
            FakeShare(reference_id=part.reference_id, description=part.description, amount_usd=part.amount_usd)
            for part in view.request.parts
        ],
        cancel_url=view.request.cancel_url,
    )


@router.post("/{token}/approve")
def approve_order(token: str, gateway: GatewayDep, background: BackgroundTasks) -> Redirect:
    """The buyer approves. Like PayPal, send them to the return URL with the token and a payer id, and send the
    CHECKOUT.ORDER.APPROVED webhook."""
    view = _view(gateway, token, approve=True)
    background.add_task(deliver_fake_webhooks)
    separator = "&" if "?" in view.request.return_url else "?"
    query = urlencode({"token": token, "PayerID": FAKE_PAYER_ID})
    return Redirect(redirect_url=f"{view.request.return_url}{separator}{query}")
