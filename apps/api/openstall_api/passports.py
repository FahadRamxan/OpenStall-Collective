"""Issuing trust passports (spec 3.7): which key signs them, and what goes in them. The signing is packages/trust."""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openstall_api.settings import get_settings
from openstall_trust import load_private_key, sign_passport

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
