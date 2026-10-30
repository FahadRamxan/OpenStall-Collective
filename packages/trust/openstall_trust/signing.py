"""Ed25519 keys and passport signatures (spec 3.7).

Keys travel as standard base64 of their raw 32 bytes: the private key in PASSPORT_SIGNING_KEY,
the public key wherever passports are checked. A signature is "ed25519:" plus base64url of its
64 bytes without padding, made over canonical_json(passport).
"""

import base64
import copy
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from openstall_trust.canonical import SIGNATURE_FIELD, canonical_json

SIGNATURE_PREFIX = "ed25519:"
_KEY_SIZE = 32
_SIGNATURE_SIZE = 64


def generate_keypair() -> tuple[str, str]:
    """Make a new key pair: (private_b64 for PASSPORT_SIGNING_KEY, public_b64 to share)."""
    private_key = Ed25519PrivateKey.generate()
    return _b64(private_key.private_bytes_raw()), public_key_b64(private_key)


def load_private_key(b64: str) -> Ed25519PrivateKey:
    """Load a private key from base64, as generate_keypair writes it."""
    return Ed25519PrivateKey.from_private_bytes(_key_bytes(b64, "private"))


def load_public_key(b64: str) -> Ed25519PublicKey:
    """Load a public key from base64, as public_key_b64 writes it."""
    return Ed25519PublicKey.from_public_bytes(_key_bytes(b64, "public"))


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    """The public half of a key, as base64."""
    public_key = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return _b64(public_key.public_bytes_raw())


def sign_passport(passport: Mapping[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    """Return a signed copy of the passport, replacing any old signature.

    The copy is deep, so later changes to the original cannot alter what was signed.
    """
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("sign_passport needs an Ed25519 private key (see load_private_key)")
    if not isinstance(passport, Mapping):
        raise TypeError(f"a passport is a JSON object, not {type(passport).__name__}")
    signed = copy.deepcopy(dict(passport))
    signed[SIGNATURE_FIELD] = SIGNATURE_PREFIX + _b64url(private_key.sign(canonical_json(signed)))
    return signed


def verify_passport(passport: Mapping[str, Any], public_key: Ed25519PublicKey) -> bool:
    """True only if this key signed exactly this content.

    Never raises for a bad passport: a changed field, a missing or malformed signature, content
    that is not plain JSON, or a signature from another key all give False.
    """
    if not isinstance(public_key, Ed25519PublicKey):
        raise TypeError("verify_passport needs an Ed25519 public key (see load_public_key)")
    if not isinstance(passport, Mapping):
        return False
    signature = _signature_bytes(passport.get(SIGNATURE_FIELD))
    if signature is None:
        return False
    try:
        message = canonical_json(passport)
    except (TypeError, ValueError):  # not plain JSON, so it cannot be something we signed
        return False
    try:
        public_key.verify(signature, message)
    except InvalidSignature:
        return False
    return True


def _signature_bytes(signature: object) -> bytes | None:
    """The raw signature, or None unless it is spelled exactly as sign_passport writes it."""
    if not isinstance(signature, str) or not signature.startswith(SIGNATURE_PREFIX):
        return None
    encoded = signature.removeprefix(SIGNATURE_PREFIX)
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except ValueError:
        return None
    # The decoder skips stray characters and ignores spare bits, so compare against a fresh
    # encoding: each signature then has exactly one accepted spelling.
    if len(raw) != _SIGNATURE_SIZE or _b64url(raw) != encoded:
        return None
    return raw


def _key_bytes(b64: str, kind: str) -> bytes:
    # The errors never repeat the input, because it may be the secret key.
    if not isinstance(b64, str):
        raise TypeError(f"the {kind} key must be a base64 string, not {type(b64).__name__}")
    try:
        raw = base64.b64decode(b64.strip(), validate=True)
    except ValueError:
        raw = b""
    if len(raw) != _KEY_SIZE:
        raise ValueError(
            f"not a base64 Ed25519 {kind} key ({_KEY_SIZE} bytes); "
            "make a key pair with scripts/make_signing_key.py"
        )
    return raw


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
