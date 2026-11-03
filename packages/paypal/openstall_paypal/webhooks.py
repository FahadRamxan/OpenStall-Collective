"""PayPal webhooks: checking an event really comes from PayPal, and the fake events fake mode sends itself.

In sandbox mode PayPal checks its own signature: we send it the transmission headers, our webhook id and the event
exactly as it arrived, to /v1/notifications/verify-webhook-signature. In fake mode the fake gateway signs its events
with a fixed key in this file. That key is public, which is fine: fake mode moves no money.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from openstall_paypal.client import PayPalClient
from openstall_paypal.sandbox import paypal_errors

log = logging.getLogger(__name__)

# The transmission headers PayPal sends with every webhook, lower-cased.
TRANSMISSION_HEADERS = (
    "paypal-auth-algo",
    "paypal-cert-url",
    "paypal-transmission-id",
    "paypal-transmission-sig",
    "paypal-transmission-time",
)
FAKE_WEBHOOK_KEY = b"openstall fake mode webhook key: public, signs nothing of value"


class WebhookVerifier(Protocol):
    def verify(self, raw: bytes, headers: Mapping[str, str]) -> bool:
        """Whether PayPal sent this event. `headers` are the request's headers, with lower-case names."""
        ...


class PayPalWebhookVerifier:
    """Asks PayPal whether an event is genuine. Raises PaymentUnavailable when PayPal cannot be asked."""

    def __init__(self, client: PayPalClient, webhook_id: str | None) -> None:
        self.client = client
        self.webhook_id = webhook_id

    def verify(self, raw: bytes, headers: Mapping[str, str]) -> bool:
        if not self.webhook_id:
            log.warning("A PayPal webhook arrived, but PAYPAL_WEBHOOK_ID is not set, so it cannot be verified")
            return False
        if not all(headers.get(name) for name in TRANSMISSION_HEADERS):
            return False
        fields = json.dumps(
            {
                "auth_algo": headers["paypal-auth-algo"],
                "cert_url": headers["paypal-cert-url"],
                "transmission_id": headers["paypal-transmission-id"],
                "transmission_sig": headers["paypal-transmission-sig"],
                "transmission_time": headers["paypal-transmission-time"],
                "webhook_id": self.webhook_id,
            }
        )
        # The event goes back byte for byte: parsing and re-encoding it could change what PayPal signed.
        body = fields[:-1] + ', "webhook_event": ' + raw.decode("utf-8") + "}"
        with paypal_errors():
            answer = self.client.post_raw("/v1/notifications/verify-webhook-signature", body.encode("utf-8"))
        return answer.get("verification_status") == "SUCCESS"


def fake_signature(raw: bytes, transmission_id: str) -> str:
    return hmac.new(FAKE_WEBHOOK_KEY, transmission_id.encode() + b"|" + raw, hashlib.sha256).hexdigest()


def sign_fake_webhook(raw: bytes) -> dict[str, str]:
    """The transmission headers for an event fake mode sends itself."""
    transmission_id = "FAKE-" + hashlib.sha256(raw).hexdigest()[:24]
    return {
        "paypal-auth-algo": "HMAC-SHA256",
        "paypal-cert-url": "fake://openstall",
        "paypal-transmission-id": transmission_id,
        "paypal-transmission-sig": fake_signature(raw, transmission_id),
        "paypal-transmission-time": datetime.now(UTC).isoformat(),
    }


class FakeWebhookVerifier:
    """Fake mode: accepts only events signed by sign_fake_webhook."""

    def verify(self, raw: bytes, headers: Mapping[str, str]) -> bool:
        transmission_id = headers.get("paypal-transmission-id") or ""
        signature = headers.get("paypal-transmission-sig") or ""
        return bool(transmission_id) and hmac.compare_digest(signature, fake_signature(raw, transmission_id))


def fake_event(event_type: str, resource_type: str, resource: dict[str, Any], summary: str) -> dict[str, Any]:
    """A webhook event shaped like PayPal's. Its id comes from what it says, so a repeat has the same id."""
    # A payout item's event names it by payout_item_id; it has no id of its own.
    about = resource.get("id") or resource.get("payout_item_id")
    digest = hashlib.sha256(f"{event_type}|{about}".encode()).hexdigest()[:20].upper()
    return {
        "id": f"WH-FAKE-{digest}",
        "event_version": "1.0",
        "create_time": datetime.now(UTC).isoformat(),
        "resource_type": resource_type,
        "event_type": event_type,
        "summary": summary,
        "resource": resource,
    }
