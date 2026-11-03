"""Webhooks over HTTP: POST /api/webhooks/paypal."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from openstall_api.webhooks import MAX_BYTES, WebhookRefused, receive_paypal_webhook
from openstall_paypal import PaymentUnavailable

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookOutcome(BaseModel):
    status: str  # processed, or repeat for an event already handled


@router.post("/paypal")
async def paypal_webhook(request: Request) -> WebhookOutcome:
    """A PayPal event. 200 once it is handled (a repeat is a 200 that changes nothing), 400 if PayPal did not send
    it, 503 if PayPal cannot verify it right now, so PayPal sends it again later."""
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="The event is too large.")
    try:
        outcome = await run_in_threadpool(receive_paypal_webhook, raw, dict(request.headers))
    except WebhookRefused as error:
        raise HTTPException(status_code=400, detail=f"Refused: {error}.") from None
    except PaymentUnavailable:
        raise HTTPException(status_code=503, detail="PayPal could not verify the event right now.") from None
    return WebhookOutcome(status=outcome)
