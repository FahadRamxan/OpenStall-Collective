"""The stalls over HTTP, for the web app: GET /api/sellers, /api/sellers/{id} and /api/products."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from openstall_api.catalog import ProductOut, SellerCard, SellerDetail, live_products, seller_cards, seller_detail
from openstall_api.db import get_session

router = APIRouter(prefix="/api", tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/sellers")
def list_sellers(session: SessionDep) -> list[SellerCard]:
    return seller_cards(session)


@router.get("/sellers/{seller_id}")
def get_seller(seller_id: str, session: SessionDep) -> SellerDetail:
    detail = seller_detail(session, seller_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"There is no stall called {seller_id!r}.")
    return detail


@router.get("/products")
def list_products(session: SessionDep, seller_id: str | None = None) -> list[ProductOut]:
    return [ProductOut.of(product) for product in live_products(session, seller_id)]
