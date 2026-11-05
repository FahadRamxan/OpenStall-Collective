"""Feeds for agents without MCP (spec 3.2): /catalog.json, every live listing in one JSON file, and /llms.txt, a short
plain-text guide to OpenStall for language models.

The catalog's entries are the same CatalogEntry that get_product returns (catalog.py). Building it reads every live
listing and passport, so it is kept in this process for 60 seconds, and its Cache-Control says how much of that is
left: wherever a copy is read, it is never more than 60 seconds old. reset_app_state() forgets it, with the settings
and the database it was built from; clear_catalog_cache() forgets it alone.
"""

import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp.types import Tool
from pydantic import BaseModel, Field

from openstall_api.catalog import CatalogEntry, catalog_entries, public_url
from openstall_api.db import new_session
from openstall_api.settings import Settings, get_settings

CATALOG_MAX_AGE = 60  # seconds a built catalog is served for
# What OpenStall is, not what agents can do here yet: llms.txt says that.
ABOUT = (
    "Handmade goods from home makers who sell over WhatsApp, pooled into one collective supplier for AI shopping "
    "agents that buy in bulk."
)
# How an agent orders, now that MCP tools take orders (prompt 27). A test checks llms.txt says this only while
# create_collective_order exists.
ORDERING = (
    "Agents can also order: request_quote asks each matching maker's seller agent for an offer, negotiated within "
    "limits she set and checked in code, and plain code splits the order across makers, cheapest first. "
    "create_collective_order turns that plan into a draft order, which a person approves on OpenStall before PayPal "
    "holds any money."
)

# Seconds that only ever go up; tests move it forward.
monotonic: Callable[[], float] = time.monotonic


class Catalog(BaseModel):
    """GET /catalog.json. docs/catalog.schema.json describes it, and a test checks the real output against it."""

    name: str = "OpenStall Collective"
    description: str = ABOUT
    generated_at: datetime = Field(description="When this copy was built, in UTC. It is served for 60 seconds.")
    mcp_url: str = Field(description="The MCP storefront (Streamable HTTP), for agents that use MCP.")
    llms_txt_url: str = Field(description="A short plain-text guide to OpenStall for language models.")
    products: list[CatalogEntry] = Field(description="Every live listing, oldest first.")


def build_catalog(settings: Settings) -> Catalog:
    """The catalog as it is in the database now. This only reads."""
    with new_session() as session:
        products = catalog_entries(session, settings)
    return Catalog(
        generated_at=datetime.now(UTC).replace(microsecond=0),
        mcp_url=public_url(settings, "/mcp"),
        llms_txt_url=public_url(settings, "/llms.txt"),
        products=products,
    )


@dataclass(frozen=True)
class CatalogCopy:
    body: bytes  # the JSON, ready to send
    made_at: float  # monotonic() when it was built

    def max_age(self) -> int:
        """Seconds it may still be kept for: what is left of its 60, with part of a second it has lived counted as a
        whole one, so a cache that keeps it that long never holds it past 60 seconds."""
        return max(0, CATALOG_MAX_AGE - math.ceil(monotonic() - self.made_at))


_catalog: CatalogCopy | None = None
_catalog_lock = threading.Lock()


def cached_catalog() -> CatalogCopy:
    """/catalog.json: the copy built in the last 60 seconds, or a new one.

    The lock makes requests that arrive while it is being built wait for that one copy instead of each building their
    own.
    """
    global _catalog
    with _catalog_lock:
        if _catalog is None or monotonic() - _catalog.made_at >= CATALOG_MAX_AGE:
            made_at = monotonic()
            _catalog = CatalogCopy(build_catalog(get_settings()).model_dump_json().encode(), made_at)
        return _catalog


def clear_catalog_cache() -> None:
    """Forget the built catalog, so the next request builds it again. Tests use it; reset_app_state() calls it."""
    global _catalog
    with _catalog_lock:
        _catalog = None


def llms_txt(settings: Settings, tools: Sequence[Tool]) -> str:
    """/llms.txt in the llmstxt.org shape: a title, a one-line summary, then short sections of plain facts and links.

    The tools are listed from the MCP server itself, so a tool added later is named here without anyone remembering
    to. None of them spends money: no MCP tool may capture, refund or move money (CLAUDE.md, spec 3.2).
    """
    base = settings.PUBLIC_BASE_URL
    tool_lines = [f"- {tool.name}({', '.join(_parameters(tool))}): {_summary(tool)}" for tool in tools]
    if settings.OPENSTALL_MODE == "fake":
        mode = (
            "This server runs in fake mode: PayPal, WhatsApp and the AI models are simulated, so no payment here is "
            "real, not even in PayPal's sandbox."
        )
    else:
        mode = "Payments here run in PayPal's sandbox: no real money moves."
    lines = [
        "# OpenStall Collective",
        "",
        f"> {ABOUT}",
        "",
        "Agents can search the makers' live listings, and read each listing in full and each maker's trust card. "
        f"{ORDERING} Seeded makers and their numbers are made-up demo data, marked data_source "
        '"seeded_demo" wherever they appear.',
        "",
        "## MCP storefront",
        "",
        f"- MCP server: {base}/mcp (Streamable HTTP, no sign-in)",
        "",
        "Its tools (none of them spends money):",
        "",
        *tool_lines,
        "",
        "## How payment works",
        "",
        "- The buyer's human approves one PayPal authorization for the whole order. It reserves the money; nothing "
        "is taken yet.",
        "- Each maker's share is captured only when she proves she shipped: she sends a photo of her courier receipt "
        "(pay-on-proof). A maker who drops out is never paid, and her share is released.",
        "- No MCP tool captures, refunds or moves money.",
        f"- {mode}",
        "",
        "## Without MCP",
        "",
        f"- [Catalog]({base}/catalog.json): every live listing as JSON, with the seller, price, capacity per week, "
        "ship days, photos, trust score and data_source. A copy is at most 60 seconds old.",
        f"- One listing: `{base}/catalog/{{product_id}}.json`, its entry in the catalog, as get_product gives it.",
        f"- A maker's trust card: `{base}/passport/{{seller_id}}`, her trust passport, as get_trust_card gives it.",
        "",
        "## Trust passports",
        "",
        "A maker's trust card is her passport: orders delivered, on-time and dispute rates, photo originality, a score "
        "from 0 to 1 (0.4 x on time + 0.3 x (1 - disputes) + 0.3 x photo originality), when it was issued, and "
        "data_source.",
        "",
        # The rules of packages/trust's canonical_json, all of them: a test rebuilds a card's signed bytes from them.
        "To check a trust card's signature, verify it with Ed25519 over the card's canonical JSON: every field but "
        '"signature", keys sorted at every level, no whitespace, UTF-8 text rather than \\u escapes, and whole-number '
        "floats up to 2**53 written as integers (0.0 as 0, 1.0 as 1), the way JavaScript writes them. The public key "
        f"is at {base}/passport/public-key (standard base64 of its 32 raw bytes). Or ask OpenStall: "
        f"{base}/passport/{{seller_id}}/verify checks her stored card, and POST {base}/passport/verify checks any card "
        "you send it: change one number, and it fails.",
        "",
    ]
    return "\n".join(lines)


def _parameters(tool: Tool) -> list[str]:
    return list(tool.input_schema.get("properties", {}))


def _summary(tool: Tool) -> str:
    """The first paragraph of the tool's description, on one line."""
    first = (tool.description or "").strip().split("\n\n", 1)[0]
    return " ".join(first.split())
