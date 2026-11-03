"""Feeds for agents without MCP (spec 3.2), at the API's root like /mcp: GET /catalog.json, GET
/catalog/{product_id}.json (one entry, the same as the MCP tool get_product) and GET /llms.txt."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from openstall_api import feeds
from openstall_api.catalog import CatalogEntry, NotFound, catalog_entry
from openstall_api.db import get_session
from openstall_api.settings import get_settings
from openstall_api.storefront import storefront

router = APIRouter(tags=["agents"])

SessionDep = Annotated[Session, Depends(get_session)]

# One entry is read afresh each time, so it may be kept for the catalog's full minute. llms.txt changes only when the
# API is deployed with new tools or settings.
ENTRY_CACHE = f"public, max-age={feeds.CATALOG_MAX_AGE}"
LLMS_TXT_CACHE = "public, max-age=3600"


@router.get("/catalog.json", response_class=Response, responses={200: {"content": {"application/json": {}}}})
def catalog_json() -> Response:
    """Every live listing, for agents that do not use MCP. docs/catalog.schema.json describes it."""
    copy = feeds.cached_catalog()
    return Response(
        copy.body, media_type="application/json", headers={"Cache-Control": f"public, max-age={copy.max_age()}"}
    )


@router.get("/catalog/{product_id}.json")
def catalog_entry_json(product_id: str, session: SessionDep, response: Response) -> CatalogEntry:
    """One live listing, as the MCP tool get_product gives it."""
    try:
        entry = catalog_entry(session, product_id, get_settings())
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    response.headers["Cache-Control"] = ENTRY_CACHE
    return entry


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt() -> PlainTextResponse:
    """A short guide to OpenStall for language models: the MCP server, its tools, payment, the feeds and passports."""
    text = feeds.llms_txt(get_settings(), await storefront.list_tools())
    return PlainTextResponse(text, headers={"Cache-Control": LLMS_TXT_CACHE})
