"""Trust passports over HTTP (spec 3.7), at the API's root like the spec's /passport/{seller_id}/verify.

GET /passport/{seller_id} gives a maker's trust card, the signed passport itself, as the MCP tool get_trust_card
does. GET /passport/public-key gives the key that checks it, GET /passport/{seller_id}/verify checks her stored
card, and POST /passport/verify checks any card sent to it, so a card that was changed anywhere fails. The
/passport/public-key and /passport/verify routes come before /passport/{seller_id}, or "public-key" would be read
as a seller's id.
"""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from openstall_api.catalog import NotFound
from openstall_api.db import get_session
from openstall_api.passports import MissingSigningKey, TrustCard, public_key, trust_card, verify_card
from openstall_api.settings import get_settings

router = APIRouter(tags=["passports"])
SessionDep = Annotated[Session, Depends(get_session)]
MAX_CARD_BYTES = 16_384  # a card is a few hundred bytes; anything far bigger is not one


class PublicKeyOut(BaseModel):
    """The key that checks every trust passport OpenStall signs."""

    algorithm: Literal["Ed25519"] = "Ed25519"
    public_key: str  # standard base64 of the key's 32 raw bytes
    signature: str = "ed25519: then base64url without padding, over the card's canonical JSON"
    canonical_json: str = (
        'every field but "signature", keys sorted at every level, no whitespace, UTF-8 text rather than \\u '
        "escapes, and whole-number floats up to 2**53 written as integers (0.0 as 0)"
    )
    # Test mode signs with a fixed key anyone can rebuild from the code: nothing it signs is trusted anywhere real.
    test_mode: bool


class Verdict(BaseModel):
    """Whether OpenStall's key signed exactly this card."""

    valid: bool
    seller_id: str | None
    reason: str  # in words, for people and agents


def _key() -> str:
    try:
        return public_key()
    except MissingSigningKey as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


def verdict(card: Any) -> Verdict:
    _key()
    seller = card.get("seller_id") if isinstance(card, dict) and isinstance(card.get("seller_id"), str) else None
    if verify_card(card):
        return Verdict(
            valid=True, seller_id=seller, reason="OpenStall signed exactly this card: nothing in it was changed."
        )
    if not isinstance(card, dict) or not card.get("signature"):
        return Verdict(valid=False, seller_id=seller, reason="This is not a signed trust card: it has no signature.")
    return Verdict(
        valid=False,
        seller_id=seller,
        reason="The signature does not match: this card was changed after OpenStall signed it, or OpenStall did "
        "not sign it.",
    )


@router.get("/passport/public-key")
def get_public_key() -> PublicKeyOut:
    """The Ed25519 key that checks every trust passport, and how a card's signed bytes are written."""
    return PublicKeyOut(public_key=_key(), test_mode=get_settings().OPENSTALL_MODE == "fake")


@router.post("/passport/verify")
def verify_any(card: Annotated[dict[str, Any], Body()]) -> Verdict:
    """Whether OpenStall signed exactly the trust card sent: change one number in it, and it fails."""
    if len(json.dumps(card, ensure_ascii=False)) > MAX_CARD_BYTES:
        raise HTTPException(status_code=413, detail="That is far bigger than a trust card.")
    return verdict(card)


@router.get("/passport/{seller_id}")
def get_passport(seller_id: str, session: SessionDep) -> TrustCard:
    """A maker's trust card: her signed passport, exactly as it was signed, with its signature."""
    try:
        return trust_card(session, seller_id)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


@router.get("/passport/{seller_id}/verify")
def verify_hers(seller_id: str, session: SessionDep) -> Verdict:
    """Whether her stored trust card still carries OpenStall's signature (spec 3.7)."""
    return verdict(get_passport(seller_id, session).model_dump())
