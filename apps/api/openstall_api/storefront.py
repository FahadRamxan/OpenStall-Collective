"""Agent storefront: the MCP server that buyer agents talk to (spec 3.2).

Day-one version: one read-only tool over the seeded demo catalog. No tool here can capture a payment.
"""

import logging
import re
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette

from openstall_api import settings
from openstall_api.catalog import DEMO_PRODUCTS, Product

log = logging.getLogger(__name__)

storefront = MCPServer(
    "OpenStall Collective",
    instructions="Handmade goods from small sellers who work over WhatsApp. Tools here never spend money.",
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2}


@storefront.tool(annotations=READ_ONLY)
def search_products(
    query: str,
    max_price: float | None = None,
    ship_to: str | None = None,
    deadline: str | None = None,
    quantity: int | None = None,
) -> list[Product]:
    """Search handmade products from OpenStall sellers.

    Args:
        query: What the buyer wants in plain words, for example "embroidered cushion covers".
        max_price: Highest unit price in USD.
        ship_to: Delivery city. Accepted, not used yet.
        deadline: Delivery deadline as YYYY-MM-DD. Accepted, not used yet.
        quantity: Units needed. Accepted, not used yet.
    """
    wanted = _words(query)
    matches = [
        p
        for p in DEMO_PRODUCTS
        if wanted & _words(f"{p.title} {p.category}") and (max_price is None or p.price_usd <= max_price)
    ]
    if not matches:
        # Demand Radar (spec 3.8) will read these; for now they only go to the log.
        log.info("search with no results: %r", query)
    return matches


def storefront_http_app() -> Starlette:
    """Streamable HTTP app serving the storefront at /mcp.

    Stateless with JSON responses, so any instance of the API can answer any request.
    """
    public = urlsplit(settings.PUBLIC_BASE_URL)
    security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", public.netloc],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            f"{public.scheme}://{public.netloc}",
        ],
    )
    return storefront.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
