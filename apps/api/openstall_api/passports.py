"""Trust passports (spec 3.7): which key signs them, what goes in them, and the trust card agents read. The signing
is packages/trust.

The trust card is a maker's passport as the MCP tool get_trust_card and GET /passport/{seller_id} give it. Until
agents can check signatures (prompt 35 publishes the public key and the verify endpoints), its signature reads
"pending", though the seeded rows already carry a fake-mode signature.
"""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_api.catalog import ID_PATTERN, NotFound, TrustSummary
from openstall_api.models import Passport
from openstall_api.settings import get_settings
from openstall_trust import load_private_key, sign_passport

# What a trust card's "signature" says until agents can check one (prompt 35).
PENDING_SIGNATURE = "pending"

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


def issue_passport(seller_id: str, metrics: dict[str, Any], data_source: str, issued_at: datetime) -> dict[str, Any]:
    """A signed passport in the spec 3.7 shape: the seller, when, the numbers, where they came from, the signature."""
    passport = {
        "seller_id": seller_id,
        "issued_at": issued_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        **metrics,
        "data_source": data_source,
    }
    return sign_passport(passport, signing_key())


class TrustCard(BaseModel):
    """A maker's trust passport as agents read it: get_trust_card and GET /passport/{seller_id}.

    The spec 3.7 passport with its score, read through the same TrustSummary as her stall page, so the two cannot
    disagree. It leaves out the seeded passports' paypal_account_verified: nothing checks a PayPal account yet.
    """

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
    signature: str = Field(
        description='"pending": OpenStall does not yet publish the key that checks passports, so treat the numbers '
        "as unverified."
    )

    @classmethod
    def of(cls, passport: Passport) -> "TrustCard":
        trust = TrustSummary.of(passport)
        return cls(
            seller_id=passport.seller_id,
            issued_at=trust.issued_at,
            orders_delivered=trust.orders_delivered,
            on_time_rate=trust.on_time_rate,
            dispute_rate=trust.dispute_rate,
            photo_originality=trust.photo_originality,
            score=float(trust.score),
            data_source=trust.data_source.value,
            signature=PENDING_SIGNATURE,
        )


def trust_card(session: Session, seller_id: str) -> TrustCard:
    """A maker's trust card. Raises NotFound with a message for the agent when she has no passport. This only reads."""
    passport = session.get(Passport, seller_id) if ID_PATTERN.fullmatch(seller_id) else None
    if passport is None:
        raise NotFound(
            f"There is no trust card for {seller_id!r}. Each listing's seller_id names its maker; a maker who is new "
            "to OpenStall has no trust card yet."
        )
    return TrustCard.of(passport)
