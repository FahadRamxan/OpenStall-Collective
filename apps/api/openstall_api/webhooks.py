"""PayPal webhooks (spec 3.5 and section 7): verified, kept, and acted on exactly once.

Every event is checked with PayPal (or, in fake mode, against the fake gateway's signature) before anything else.
Its id goes into processed_webhooks in the same transaction as what it changes, so a repeat changes nothing.

What PayPal confirmed is worked out from the kept events when an order is read (confirmations), so events that
arrive before our side saved its own ids, or out of order, still count. A few events also change a share: a
capture PayPal completed after our call to it timed out, and an authorization voided at PayPal (it expired, or
someone voided it in the dashboard), which releases the shares it held.
"""

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openstall_api.adapters import get_registry
from openstall_api.db import session_scope
from openstall_api.events import EventType, record_event
from openstall_api.models import Order, OrderPart, PartStatus, ProcessedWebhook
from openstall_api.orders import move_part
from openstall_api.payments import settle_order
from openstall_paypal import (
    FakeGateway,
    FakeWebhookVerifier,
    PayPalWebhookVerifier,
    SandboxGateway,
    WebhookVerifier,
    sign_fake_webhook,
)

log = logging.getLogger(__name__)

MAX_BYTES = 1024 * 1024  # PayPal's events are a few kilobytes
PROVIDER = "paypal"

# Events that mean a share needs a person to look at it, in words for the buyer.
ATTENTION = {
    "PAYMENT.CAPTURE.DENIED": "PayPal denied this payment",
    "PAYMENT.CAPTURE.REFUNDED": "PayPal refunded this payment",
    "PAYMENT.CAPTURE.REVERSED": "PayPal reversed this payment",
    "PAYMENT.PAYOUTS-ITEM.FAILED": "PayPal could not pay this maker",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED": "PayPal blocked the payout to this maker",
    "PAYMENT.PAYOUTS-ITEM.RETURNED": "The payout to this maker came back",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED": "This maker has not claimed her payout yet",
}


class WebhookRefused(ValueError):
    """Not a genuine PayPal event: refused with 400, and nothing is changed."""


def webhook_verifier() -> WebhookVerifier:
    registry = get_registry()
    if registry.settings.OPENSTALL_MODE == "fake":
        return FakeWebhookVerifier()
    gateway = registry.payment_gateway
    assert isinstance(gateway, SandboxGateway)
    return PayPalWebhookVerifier(gateway.client, registry.settings.PAYPAL_WEBHOOK_ID)


def resource_id(resource: Mapping[str, Any]) -> str | None:
    """PayPal's id for what the event is about: an authorization, a capture, a payout item or a batch."""
    found = resource.get("id") or resource.get("payout_item_id") or (resource.get("batch_header") or {}).get(
        "payout_batch_id"
    )
    return str(found)[:64] if found else None


def reference(resource: Mapping[str, Any]) -> str | None:
    """Our own id that PayPal echoes back: a capture's invoice_id or a payout's sender_item_id, both a share's id."""
    found = resource.get("invoice_id") or (resource.get("payout_item") or {}).get("sender_item_id")
    return str(found)[:64] if found else None


def receive_paypal_webhook(raw: bytes, headers: Mapping[str, str]) -> Literal["processed", "repeat"]:
    """Verify a webhook, then act on it once. Raises WebhookRefused for anything PayPal did not send, and
    PaymentUnavailable when PayPal cannot be asked (the caller answers 503, so PayPal sends it again later)."""
    headers = {name.lower(): value for name, value in headers.items()}
    if len(raw) > MAX_BYTES:
        raise WebhookRefused("the event is too large")
    try:
        event = json.loads(raw)
    except ValueError:
        raise WebhookRefused("the body is not JSON") from None
    if not isinstance(event, dict) or not event.get("id") or not event.get("event_type"):
        raise WebhookRefused("the body is not a PayPal event")
    if not webhook_verifier().verify(raw, headers):
        with session_scope() as session:
            record_event(
                session,
                EventType.SECURITY_REJECTED,
                "A PayPal webhook failed verification and was refused",
                payload={
                    "event_type": str(event.get("event_type"))[:64],
                    "transmission_id": headers.get("paypal-transmission-id", "")[:64],
                },
            )
        raise WebhookRefused("PayPal did not sign this event")
    try:
        with session_scope() as session:
            if session.scalar(select(ProcessedWebhook.id).where(ProcessedWebhook.event_id == str(event["id"]))):
                return "repeat"
            resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
            session.add(
                ProcessedWebhook(
                    provider=PROVIDER,
                    event_id=str(event["id"])[:128],
                    event_type=str(event["event_type"])[:64],
                    resource_id=resource_id(resource),
                    reference=reference(resource),
                    payload_json=event,
                )
            )
            session.flush()  # a repeat arriving at the same moment fails here, before anything changes
            apply_paypal_event(session, str(event["event_type"]), resource)
    except IntegrityError:
        return "repeat"
    return "processed"


def _order_of(session: Session, resource: Mapping[str, Any]) -> Order | None:
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    paypal_order_id = related.get("order_id") or resource.get("id")
    if not paypal_order_id:
        return None
    return session.scalar(select(Order).where(Order.paypal_order_id == str(paypal_order_id)))


def _names(parts: Iterable[OrderPart]) -> str:
    names = [part.seller.name for part in parts]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def apply_paypal_event(session: Session, kind: str, resource: Mapping[str, Any]) -> None:
    """What a verified event changes, and its line in the live feed."""
    order_id: str | None = None
    if kind == "CHECKOUT.ORDER.APPROVED":
        order = _order_of(session, resource)
        order_id = order.id if order else None
        summary = f"PayPal confirmed the buyer approved order {order_id}" if order else "PayPal confirmed an approval"
    elif kind in ("PAYMENT.AUTHORIZATION.CREATED", "PAYMENT.AUTHORIZATION.VOIDED"):
        hold = resource_id(resource)
        parts = list(session.scalars(select(OrderPart).where(OrderPart.authorization_id == hold))) if hold else []
        order_id = parts[0].order_id if parts else None
        if kind == "PAYMENT.AUTHORIZATION.CREATED":
            summary = (
                f"PayPal confirmed the money for {_names(parts)} is reserved"
                if parts
                else "PayPal confirmed a reservation; it counts as soon as the order is saved"
            )
        else:
            held = [part for part in parts if part.status == PartStatus.AUTHORIZED]
            for part in held:  # voided at PayPal: these shares can no longer be paid
                move_part(part, PartStatus.RELEASED)
                record_event(
                    session,
                    EventType.PART_RELEASED,
                    f"{part.seller.name}'s share of ${part.amount_usd:,.2f} was released: PayPal voided its hold",
                    entity_id=part.id,
                    payload={"order_id": part.order_id, "amount_usd": part.amount_usd},
                )
            if held:
                settle_order(held[0].order)
            summary = f"PayPal confirmed the hold for {_names(parts)} is released" if parts else "PayPal voided a hold"
    elif kind == "PAYMENT.CAPTURE.COMPLETED":
        part = session.get(OrderPart, reference(resource) or "")
        order_id = part.order_id if part else None
        if part and part.status == PartStatus.AUTHORIZED:  # our call timed out, but PayPal took the money
            part.capture_id = resource_id(resource)
            move_part(part, PartStatus.CAPTURED)
            settle_order(part.order)
        summary = f"PayPal confirmed {part.seller.name} was paid" if part else "PayPal confirmed a payment"
    elif kind in ATTENTION:
        part = session.get(OrderPart, reference(resource) or "")
        order_id = part.order_id if part else None
        summary = f"{ATTENTION[kind]}: {part.seller.name}'s share needs attention" if part else ATTENTION[kind]
    elif kind == "PAYMENT.PAYOUTS-ITEM.SUCCEEDED":
        part = session.get(OrderPart, reference(resource) or "")
        order_id = part.order_id if part else None
        summary = f"PayPal paid out {part.seller.name}'s share" if part else "PayPal paid out a share"
    elif kind == "PAYMENT.PAYOUTSBATCH.SUCCESS":
        summary = "PayPal finished a payout batch"
    else:
        summary = f"PayPal sent {kind}; nothing to do"
    record_event(session, EventType.PAYMENT_WEBHOOK, summary, entity_id=order_id, payload={"event_type": kind})


@dataclass(frozen=True)
class PayPalConfirmation:
    """For one share: whether PayPal confirmed where it stands now, and anything that needs a person."""

    confirmed: bool
    attention: str | None


def confirmations(session: Session, parts: list[OrderPart]) -> dict[str, PayPalConfirmation]:
    """What PayPal's events confirm about each share, by share id."""
    holds = {part.authorization_id for part in parts if part.authorization_id}
    ids = {part.id for part in parts}
    rows = session.execute(
        select(ProcessedWebhook.event_type, ProcessedWebhook.resource_id, ProcessedWebhook.reference).where(
            or_(ProcessedWebhook.resource_id.in_(holds), ProcessedWebhook.reference.in_(ids))
        )
    ).all()
    by_resource = {(row.event_type, row.resource_id) for row in rows}
    by_reference = {(row.event_type, row.reference) for row in rows}
    result = {}
    for part in parts:
        if part.status == PartStatus.AUTHORIZED:
            confirmed = ("PAYMENT.AUTHORIZATION.CREATED", part.authorization_id) in by_resource
        elif part.status in (PartStatus.CAPTURED, PartStatus.DELIVERED):
            confirmed = ("PAYMENT.CAPTURE.COMPLETED", part.id) in by_reference
        elif part.status == PartStatus.RELEASED:
            confirmed = ("PAYMENT.AUTHORIZATION.VOIDED", part.authorization_id) in by_resource
        else:
            confirmed = False
        attention = next((words for kind, words in ATTENTION.items() if (kind, part.id) in by_reference), None)
        result[part.id] = PayPalConfirmation(confirmed=confirmed, attention=attention)
    return result


def deliver_fake_webhooks() -> int:
    """Fake mode: send the events the fake gateway queued to our own webhook handler, signed, as PayPal would send
    them, so the whole flow works offline, confirmations included. Returns how many were sent."""
    gateway = get_registry().payment_gateway if get_registry().settings.OPENSTALL_MODE == "fake" else None
    if not isinstance(gateway, FakeGateway):
        return 0
    events = gateway.take_outbox()
    for event in events:
        raw = json.dumps(event).encode("utf-8")
        try:
            receive_paypal_webhook(raw, sign_fake_webhook(raw))
        except Exception:  # one bad event must not stop the rest; PayPal would retry it
            log.exception("A fake PayPal webhook (%s) could not be processed", event.get("event_type"))
    return len(events)
