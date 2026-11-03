"""Trust passports over HTTP (spec 3.7), at the API's root like the spec's /passport/{seller_id}/verify.

For now GET /passport/{seller_id}: a maker's trust card, the same as the MCP tool get_trust_card, with its signature
"pending". Prompt 35 signs it and adds the public key and the verify endpoints here; declare /passport/public-key
before /passport/{seller_id}, or "public-key" would be read as a seller's id.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from openstall_api.catalog import NotFound
from openstall_api.db import get_session
from openstall_api.passports import TrustCard, trust_card

router = APIRouter(tags=["passports"])


@router.get("/passport/{seller_id}")
def get_passport(seller_id: str, session: Annotated[Session, Depends(get_session)]) -> TrustCard:
    """A maker's trust card: her passport's numbers and score, data_source, and the signature ("pending" for now)."""
    try:
        return trust_card(session, seller_id)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
