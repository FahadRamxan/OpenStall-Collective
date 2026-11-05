"""Trust passports (spec 3.7): which key signs them, what goes in them, the trust card agents read, and how anyone
checks one. The signing is packages/trust.

The trust card IS the signed passport: the MCP tool get_trust_card and GET /passport/{seller_id} give exactly the
fields that were signed, with the signature. Anyone can check it with the public key at /passport/public-key
(Ed25519 over the card's canonical JSON, every field but "signature"), or ask GET /passport/{seller_id}/verify, or
send a card to POST /passport/verify, which says whether OpenStall's key signed exactly that.
"""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_api.catalog import ID_PATTERN, NotFound
from openstall_api.models import Passport
from openstall_api.settings import get_settings
from openstall_trust import load_private_key, load_public_key, public_key_b64, sign_passport, trust_score
from openstall_trust import verify_passport as signature_holds

# Fake mode only: a fixed key that anyone can rebuild from this file, so local runs and tests need no setup.
# Nothing signed with it is trusted anywhere real, and sandbox mode refuses to use it.
FAKE_MODE_KEY_B64 = base64.b64encode(hashlib.sha256(b"OpenStall fake-mode passport key, not secret").digest()).decode()


class MissingSigningKey(RuntimeError):
    """Sandbox mode without PASSPORT_SIGNING_KEY."""


def signing_key() -> Ed25519PrivateKey:
    settings = get_settings()
    if settings.PASSPORT_SIGNING_KEY is not None and settings.is_set("PASSPORT_SIGNING_KEY"):
        return load_private_key(settings.PASSPORT_SIGNING_KEY.get_secret_value())
    if settings.OPENSTALL_MODE == "fake":
        return load_private_key(FAKE_MODE_KEY_B64)
    raise MissingSigningKey(
        "Sandbox mode needs PASSPORT_SIGNING_KEY to sign trust passports. Make one with "
        "python scripts/make_signing_key.py and put it in .env or the host's environment."
    )


def public_key() -> str:
    """The key that checks every passport, as base64 of its 32 raw bytes. Raises MissingSigningKey in sandbox mode
    without PASSPORT_SIGNING_KEY."""
    return public_key_b64(signing_key())


def issue_passport(seller_id: str, metrics: dict[str, Any], data_source: str, issued_at: datetime) -> dict[str, Any]:
    """A signed passport: exactly the trust card's fields (spec 3.7, with the core's score and how many of her
    orders came through OpenStall), then the signature. `metrics`: orders_delivered, on_time_rate, dispute_rate and
    photo_originality, and live_deliveries and live_on_time when there are any."""
    passport = {
        "seller_id": seller_id,
        "issued_at": issued_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "orders_delivered": int(metrics["orders_delivered"]),
        "on_time_rate": metrics["on_time_rate"],
        "dispute_rate": metrics["dispute_rate"],
        "photo_originality": metrics["photo_originality"],
        "score": float(trust_score(metrics["on_time_rate"], metrics["dispute_rate"], metrics["photo_originality"])),
        "live_deliveries": int(metrics.get("live_deliveries", 0)),
        "live_on_time": int(metrics.get("live_on_time", 0)),
        "data_source": data_source,
    }
    return sign_passport(passport, signing_key())


def verify_card(card: Any) -> bool:
    """Whether OpenStall's key signed exactly this card. Never raises for a bad card: anything changed, missing or
    malformed is False."""
    return signature_holds(card, load_public_key(public_key()))


class TrustCard(BaseModel):
    """A maker's trust passport as agents read it: get_trust_card and GET /passport/{seller_id}. It is exactly what
    was signed, with the signature, so an agent can check it: Ed25519 over the canonical JSON of every field but
    "signature", with the key at /passport/public-key."""

    seller_id: str
    issued_at: str = Field(description="When OpenStall issued the passport, in UTC (ISO 8601).")
    orders_delivered: int = Field(description="Orders she has delivered.")
    on_time_rate: float = Field(description="Share of her orders that arrived by their date, from 0 to 1.")
    dispute_rate: float = Field(description="Share of her orders that buyers disputed, from 0 to 1.")
    photo_originality: float = Field(description="From 0 to 1: how far her photos are her own.")
    score: float = Field(
        description="From 0 to 1: 0.4 x on-time rate + 0.3 x (1 - dispute rate) + 0.3 x photo originality."
    )
    data_source: str = Field(description='Where the numbers come from: "seeded_demo" marks made-up demo numbers.')
    live_deliveries: int = Field(
        default=0,
        description="Of her orders delivered, how many a buyer confirmed through OpenStall. The rest are the history "
        'she came with: made up, for a passport marked "seeded_demo".',
    )
    live_on_time: int = Field(default=0, description="Of those, how many arrived by their delivery date.")
    signature: str = Field(
        description='OpenStall\'s Ed25519 signature, "ed25519:" then base64url, over the canonical JSON of every '
        'other field. Check it with the key at /passport/public-key, or ask /passport/{seller_id}/verify.'
    )

    @classmethod
    def of(cls, passport: Passport) -> "TrustCard":
        """Her stored passport, exactly as it was signed, with its signature."""
        return cls.model_validate({**passport.metrics_json, "signature": passport.signature})


def trust_card(session: Session, seller_id: str) -> TrustCard:
    """A maker's trust card. Raises NotFound with a message for the agent when she has no passport. This only reads."""
    passport = session.get(Passport, seller_id) if ID_PATTERN.fullmatch(seller_id) else None
    if passport is None:
        raise NotFound(
            f"There is no trust card for {seller_id!r}. Each listing's seller_id names its maker; a maker who is new "
            "to OpenStall has no trust card yet."
        )
    return TrustCard.of(passport)
