"""Trust passport scoring, Ed25519 signing and photo checks (spec 3.7)."""

from openstall_trust.canonical import canonical_json
from openstall_trust.score import trust_score
from openstall_trust.signing import (
    SIGNATURE_PREFIX,
    generate_keypair,
    load_private_key,
    load_public_key,
    public_key_b64,
    sign_passport,
    verify_passport,
)

__all__ = [
    "SIGNATURE_PREFIX",
    "canonical_json",
    "generate_keypair",
    "load_private_key",
    "load_public_key",
    "public_key_b64",
    "sign_passport",
    "trust_score",
    "verify_passport",
]
