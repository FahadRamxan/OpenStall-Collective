"""Agent storefront: the MCP server that buyer agents talk to (spec 3.2).

search_products over the live listings in the database (search.py), which adds each search to the search log that
the public /demo page shows; get_product, one listing in full; and get_trust_card, a maker's trust passport. The last
two only read, and give exactly what the API's feeds give (GET /catalog/{product_id}.json and
GET /passport/{seller_id}): the same functions make both. request_quote asks the makers' seller agents for offers and
plans the split (quotes.py); create_collective_order turns the plan into a draft order (collective.py). No tool here
can reserve, capture or pay out money, and none takes a price or a total from an agent.
"""

from datetime import date
from decimal import Decimal
from functools import partial
from typing import Annotated
from urllib.parse import urlsplit

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.applications import Starlette

from openstall_api import collective, quotes, search
from openstall_api.adapters import get_registry
from openstall_api.allocation import PlanOut, stored_plan
from openstall_api.catalog import CatalogEntry, NotFound, TrustSummary, catalog_entry
from openstall_api.collective import DraftOrder
from openstall_api.db import new_session, session_scope
from openstall_api.models import Passport
from openstall_api.passports import TrustCard, trust_card
from openstall_api.search import SearchError, SearchFilters, SearchResult
from openstall_api.settings import Settings, get_settings

storefront = MCPServer(
    "OpenStall Collective",
    instructions="Handmade goods from small sellers who work over WhatsApp. Tools here never spend money.",
)

# A search changes nothing a buyer or seller has, but it is not read-only: each one adds a row to the search log, and
# /demo shows the query and the city to anyone. Adding a row is all it does, so it is not destructive either.
LOGS_EACH_SEARCH = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
# Reading a listing or a trust card adds and changes nothing, so asking twice gives the same answer. Every hint is set,
# as for search_products: a client that is told nothing must assume a tool may be destructive.
READS_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


@storefront.tool(annotations=LOGS_EACH_SEARCH)
def search_products(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=300,
            description='What the buyer wants, in plain words, for example "embroidered cushion covers". Words are '
            "matched in each listing's title, description, category and colours.",
        ),
    ],
    max_price: Annotated[
        float | None,
        Field(
            ge=0.01,
            le=1_000_000,
            allow_inf_nan=False,
            description="Highest unit price in USD, for example 30. Dearer listings are left out. Prices are whole "
            "cents, so a cap with more decimal places is rounded down to the cent (29.999 to 29.99).",
        ),
    ] = None,
    ship_to: Annotated[
        str | None,
        Field(
            max_length=120,
            description='Delivery city, for example "Chicago". For now every listing\'s ship days are its days in '
            "transit to a US city, and they are used whatever city is given.",
        ),
    ] = None,
    deadline: Annotated[
        date | None,
        Field(
            description="Date the goods must arrive by, as YYYY-MM-DD, after today. Makers who cannot make and ship "
            "at least one unit by then are left out: a maker needs her minimum lead days' notice, then her "
            "production time plus the ship days. Without it, capacity_by_deadline counts to 30 days from today (UTC)."
        ),
    ] = None,
    quantity: Annotated[
        int | None,
        Field(
            ge=1,
            description="Units the buyer needs in all. OpenStall pools makers, so one maker need not make them "
            "all: makers who can make none by the deadline are left out, and each result's capacity_by_deadline "
            "says how many that maker can make.",
        ),
    ] = None,
) -> list[SearchResult]:
    """Search handmade products from OpenStall's makers. It never spends money and changes no order.

    A listing is found when it has at least half of the query's words and one of them is in its title or category.
    Results come best match first: a word a listing has ranks above one it only starts, then the lower price. Each
    result has the maker's name, a summary of her trust record, data_source ("seeded_demo" marks made-up demo data)
    and capacity_by_deadline: how many she can still make and ship by the deadline, after the orders she already has
    reserved. With no deadline, that is counted to 30 days from today (UTC). Ship days are days to US cities for now,
    whatever ship_to says. Every search is logged (the query, the filters and how many results it found), so searches
    that find nothing show what buyers want and nobody makes yet. The log is public: OpenStall's /demo page shows each
    search's query and filters, the city included, to anyone, so leave names and other personal details out.
    """
    try:
        # Runs of spaces and line breaks become one space, so the log and the /demo panel show the query on one line.
        words = search.one_line(query, "The query")
        filters = SearchFilters(
            max_price=None if max_price is None else search.price_cap(max_price),
            quantity=quantity,
            deadline=deadline,
            ship_to=search.one_line(ship_to or "", "ship_to") or None,
        )
    except SearchError as error:
        raise ToolError(str(error)) from None
    if not words:
        raise ToolError('Say what the buyer wants, for example "embroidered cushion covers".')
    with session_scope() as session:
        try:
            results = search.find_products(session, words, filters, search.clock.today())
        except SearchError as error:
            raise ToolError(str(error)) from None
        search.log_search(session, words, filters, len(results))
    return results


@storefront.tool(annotations=READS_ONLY)
def get_product(
    product_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            description='A listing\'s product_id, as search_products gives it, for example "p_noor_cushion".',
        ),
    ],
) -> CatalogEntry:
    """One live listing in full. It only reads: it never spends money and changes no order.

    It has everything a search_products result has (the maker's name, her trust record in brief, the list price in
    USD, capacity per week and ship days, data_source: "seeded_demo" marks made-up demo data), plus her photos as
    full URLs, her stall page for people, and her trust card's address. For how many she can make by a deadline, use
    search_products with that deadline. A listing that is not live (a draft, or paused) is not found.
    """
    with new_session() as session:
        try:
            return catalog_entry(session, product_id, get_settings())
        except NotFound as error:
            raise ToolError(str(error)) from None


@storefront.tool(annotations=READS_ONLY)
def get_trust_card(
    seller_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            description='The maker\'s seller_id, as each listing gives it, for example "s_noor".',
        ),
    ],
) -> TrustCard:
    """A maker's trust passport. It only reads: it never spends money and changes no order.

    Her orders delivered, on-time and dispute rates, photo originality, the score worked out from them (0.4 x on
    time + 0.3 x (1 - disputes) + 0.3 x photo originality, from 0 to 1), when it was issued, and data_source:
    "seeded_demo" marks made-up demo numbers. "signature" reads "pending": OpenStall does not yet publish the key that
    checks passports, so treat the numbers as unverified.
    """
    with new_session() as session:
        try:
            return trust_card(session, seller_id)
        except NotFound as error:
            raise ToolError(str(error)) from None


# Asking for a quote stores the request and the makers' offers, which /demo shows, and asks each maker's agent: it
# changes OpenStall's records but spends no money. Asked twice, it makes two requests.
ASKS_FOR_A_QUOTE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
# Drafting an order from a plan writes the draft once: asked again for the same request, it gives back the same draft.
DRAFTS_AN_ORDER = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


class QuotedOffer(BaseModel):
    """One maker's valid offer: the price her agent proposed and code accepted, for the units code set."""

    seller_id: str
    seller_name: str
    unit_price: Decimal = Field(description="USD per unit, in whole cents, as a string such as \"29.00\".")
    quantity: int = Field(description="Units she offers: the most she can make by the deadline, at most the request.")
    delivery_date: date
    trust_score: float | None = Field(description="Her trust score from 0 to 1; null until she has a passport.")
    message: str | None = Field(description="Her agent's one sentence to the buyer.")


class Quote(BaseModel):
    """A finished quote: each maker's valid offer, and the plan that splits the order across them."""

    request_id: str = Field(description="Give this to create_collective_order to draft the order.")
    rounds: int = Field(description="Negotiation rounds run, at most 3.")
    makers_asked: int
    offers: list[QuotedOffer] = Field(description="Each maker's valid offer, cheapest first.")
    plan: PlanOut = Field(description="How the order is split, cheapest first, with its explanation in words.")
    next_step: str


@storefront.tool(annotations=ASKS_FOR_A_QUOTE)
async def request_quote(
    items: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=300)]],
        Field(
            min_length=1,
            max_length=5,
            description='What the buyer wants, one entry per item, in plain words, for example ["40 '
            'hand-embroidered cushion covers for corporate gifts"]. Makers are matched as search_products matches.',
        ),
    ],
    quantity: Annotated[int, Field(ge=1, le=100_000, description="Units the buyer needs in all.")],
    max_unit_price: Annotated[
        float,
        Field(gt=0, le=1_000_000, allow_inf_nan=False, description="The most the buyer pays per unit, in USD."),
    ],
    deadline: Annotated[
        date, Field(description="Date the goods must arrive by, as YYYY-MM-DD, after today (UTC).")
    ],
    ship_to: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            description='Delivery city, for example "Chicago". For now ship days are days to a US city.',
        ),
    ],
) -> Quote:
    """Ask OpenStall's makers for a quote. It spends no money: it stores the request and asks each maker's agent.

    Every maker whose listing matches is asked, side by side: her seller agent proposes a price within limits she
    set, and code checks each one against those limits and max_unit_price. A refused price goes back to her agent
    with the reason; makers without a valid offer get up to 3 rounds. The valid offers are then split across makers
    by plain code, cheapest first, and the plan comes with 2 or 3 sentences explaining it (every number in them is
    checked against the plan). This can take up to a minute. Nothing is ordered: create_collective_order turns the
    plan into a draft, and a person must approve that before any money is reserved through PayPal.
    """
    try:
        cap = search.price_cap(max_unit_price)
        queries = [search.one_line(item, "Each item") for item in items]
        city = search.one_line(ship_to, "ship_to")
    except SearchError as error:
        raise ToolError(str(error)) from None
    return await anyio.to_thread.run_sync(partial(_request_quote, queries, quantity, cap, deadline, city))


def _request_quote(queries: list[str], quantity: int, cap: Decimal, deadline: date, ship_to: str) -> Quote:
    today = quotes.clock.today()
    with new_session() as session:
        try:
            request, products = quotes.create_quote_request(session, queries, quantity, cap, deadline, ship_to, today)
        except quotes.QuoteError as error:
            raise ToolError(str(error)) from None
        session.commit()
        result = quotes.run_quote(session, request, products, get_registry().llm, today)
        plan = stored_plan(session, request)
        assert plan is not None  # run_quote plans every finished quote
        offers = sorted(result.offers.values(), key=lambda offer: (offer.unit_price, offer.seller_id))
        passports = {p.seller_id: p for p in session.scalars(select(Passport).where(Passport.seller_id.in_(result.offers)))}
        return Quote(
            request_id=request.id,
            rounds=result.rounds,
            makers_asked=len(result.asked),
            offers=[
                QuotedOffer(
                    seller_id=offer.seller_id,
                    seller_name=offer.seller.name,
                    unit_price=offer.unit_price,
                    quantity=offer.quantity,
                    delivery_date=offer.delivery_date,
                    trust_score=(
                        float(TrustSummary.of(passports[offer.seller_id]).score)
                        if offer.seller_id in passports
                        else None
                    ),
                    message=offer.message,
                )
                for offer in offers
            ],
            plan=plan,
            next_step=(
                f"Call create_collective_order with request_id {request.id!r} to draft the order"
                + ("." if plan.complete else ", with accept_partial true to order only what is possible.")
            ),
        )


@storefront.tool(annotations=DRAFTS_AN_ORDER)
def create_collective_order(
    request_id: Annotated[
        str,
        Field(min_length=1, max_length=64, description="The request_id that request_quote gave."),
    ],
    accept_partial: Annotated[
        bool,
        Field(
            description="Draft the order even if the plan covers only part of the quantity. Without it, a plan "
            "that is short is refused, and nothing is drafted."
        ),
    ] = False,
) -> DraftOrder:
    """Turn a quote's plan into one draft collective order. It spends no money.

    Each maker's share and the total come from the stored plan and are worked out by OpenStall: no tool takes a
    price or a total from an agent. Calling it again for the same request gives back the same draft. Nothing is
    reserved or paid: a person must approve the draft on OpenStall's approval page, and only then does PayPal hold the
    money, with each maker's share captured when she proves she shipped.
    """
    with session_scope() as session:
        try:
            order = collective.draft_from_plan(session, request_id, accept_partial=accept_partial)
        except collective.DraftError as error:
            raise ToolError(str(error)) from None
        return collective.draft_out(order)


def storefront_http_app(settings: Settings) -> Starlette:
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
