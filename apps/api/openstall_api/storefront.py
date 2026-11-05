"""Agent storefront: the MCP server that buyer agents talk to (spec 3.2).

search_products over the live listings in the database (search.py), which adds each search to the search log that
the public /demo page shows; get_product, one listing in full; and get_trust_card, a maker's trust passport. The last
two only read, and give exactly what the API's feeds give (GET /catalog/{product_id}.json and
GET /passport/{seller_id}): the same functions make both. request_quote asks the makers' seller agents for offers and
plans the split (quotes.py); create_collective_order turns the plan into a draft order (collective.py). No tool here
can reserve, capture or pay out money, and none takes a price or a total from an agent: checkout gives the link a person approves on, and get_order_status only reads (tests/test_no_tool_moves_money.py calls every tool).
"""

from datetime import UTC, date, datetime
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
from openstall_api.delivery import delivered_utc, on_time
from openstall_api.healing import DROPPED
from openstall_api.models import Order, OrderStatus, Passport
from openstall_api.notices import notice_states, ship_by
from openstall_api.orders import server_total
from openstall_api.orders_api import payout_words
from openstall_api.passports import TrustCard, trust_card
from openstall_api.search import SearchError, SearchFilters, SearchResult
from openstall_api.settings import Settings, get_settings

storefront = MCPServer(
    "OpenStall Collective",
    instructions=(
        "Handmade goods from small sellers who work over WhatsApp, pooled into one collective supplier. Tools here "
        "never spend money. To order: request_quote asks each matching maker's seller agent for an offer and splits "
        "the order across makers; create_collective_order drafts it; checkout gives the link a person opens to "
        "approve it. Approving reserves the total through one PayPal authorization; each maker's share is captured "
        "only when she proves she shipped, and a share she cannot deliver is released. No tool approves, captures, "
        "refunds or pays out: get_order_status follows each share."
    ),
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
    "seeded_demo" marks made-up demo numbers, and live_deliveries how many of her orders came through OpenStall. It is
    the signed passport itself: "signature" is OpenStall's Ed25519 signature over the canonical JSON of every other
    field. Check it with the key at /passport/public-key, or ask /passport/{seller_id}/verify.
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
            order = collective.draft_from_plan(session, request_id, accept_partial=accept_partial, source="mcp")
        except collective.DraftError as error:
            raise ToolError(str(error)) from None
        return collective.draft_out(order)


# Giving the approval link records, once per order, that it was sent: the order, its total and the money stay as they
# are. Asked again, it gives the same link and records nothing more.
GIVES_THE_APPROVAL_LINK = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


class ApprovalLink(BaseModel):
    """Where a person approves the order: OpenStall's own approval page, never PayPal's."""

    order_id: str
    approval_url: str = Field(description="OpenStall's approval page for the order. Send it to your human.")
    status: str = Field(description='The order\'s status, such as "draft" (waiting for approval) or "authorized".')
    total_usd: Decimal = Field(description="The order's total, worked out by OpenStall, in whole cents.")
    next_step: str


class ShareStatus(BaseModel):
    """One maker's share of the order, and where its payment stands."""

    seller_id: str
    seller_name: str
    quantity: int
    status: str = Field(description="pending, authorized (reserved at PayPal), captured (paid), delivered or released.")
    status_words: str
    ship_by: date | None = Field(description="When her share must leave her to arrive by its delivery date.")
    told_at: datetime | None = Field(
        description="When OpenStall told her about her share, in her language, on WhatsApp or in the web chat. "
        "None until the order is approved, or while she cannot be reached."
    )
    carrier: str | None = Field(description="Her courier, once she has sent the tracking.")
    tracking_number: str | None
    tracking_on_paypal: bool = Field(
        description="Whether her tracking is on her payment on the PayPal order, so the payer sees it at PayPal."
    )
    delivered_at: datetime | None = Field(
        default=None, description="When the buyer confirmed her parcel arrived. None until then."
    )
    on_time: bool | None = Field(
        default=None,
        description="Whether her parcel arrived by its delivery date. None until it arrived.",
    )
    payout_rail: str = Field(description="How she is paid: paypal, venmo, hyperwallet, or unavailable.")
    payout_words: str
    dropped_out: bool = Field(
        default=False,
        description="She told OpenStall she could not make it and confirmed: her share was released, never "
        "charged, and her units were asked of the other makers (see top_ups).",
    )
    paid_through_paypal: bool = Field(description="Whether her payout goes through PayPal Payouts.")


class TopUpStatus(BaseModel):
    """A top-up order that repairs this one: other makers' units for a share that was dropped."""

    order_id: str
    status: str
    status_words: str
    total_usd: Decimal
    units: int
    makers: list[str]
    replaces: str | None = Field(description="The dropped share it replaces, in words.")
    approved: bool
    approval_link: str = Field(
        description="Where a person approves it, like any order: nothing is charged for it before. Send it "
        "to your human, or call checkout with its order_id."
    )


class OrderStatusOut(BaseModel):
    """An order's status and each maker's share, as a buyer agent follows it."""

    order_id: str
    status: str
    status_words: str
    total_usd: Decimal
    units: int
    approved: bool = Field(description="Whether a person has approved it and PayPal holds the money.")
    shares: list[ShareStatus]
    simulated: bool = Field(description="True in test mode, where PayPal is simulated and no payment is real.")
    top_ups: list[TopUpStatus] = Field(
        default_factory=list,
        description="When a maker drops out, OpenStall asks the other makers for her units and drafts them as a "
        "top-up order, which a person approves like any order. Oldest first.",
    )
    replaces: str | None = Field(
        default=None, description="On a top-up order: the dropped share of the first order that it replaces."
    )


@storefront.tool(annotations=GIVES_THE_APPROVAL_LINK)
def checkout(
    order_id: Annotated[
        str, Field(min_length=1, max_length=64, description="The order_id that create_collective_order gave.")
    ],
) -> ApprovalLink:
    """The link your human opens to approve the order. It spends no money and changes no order.

    The link is OpenStall's own approval page, never PayPal's, so the person sees each maker's share, the total and
    why the split before PayPal is involved. Approving there reserves the total through one PayPal authorization;
    each maker's share is captured only when she proves she shipped. No tool can approve, capture, refund or pay out.
    """
    with session_scope() as session:
        try:
            order = collective.load_order(session, order_id)
        except collective.DraftError as error:
            raise ToolError(str(error)) from None
        url = collective.approval_link(session, order)
        return ApprovalLink(
            order_id=order.id,
            approval_url=url,
            status=order.status.value,
            total_usd=server_total(order),
            next_step=(
                "Send this link to your human. After they approve, get_order_status shows the money reserved and "
                "each maker's share paid as she ships."
                if order.status is OrderStatus.DRAFT
                else "This order is already approved: get_order_status shows each maker's share."
            ),
        )


@storefront.tool(annotations=READS_ONLY)
def get_order_status(
    order_id: Annotated[
        str, Field(min_length=1, max_length=64, description="The order_id that create_collective_order gave.")
    ],
) -> OrderStatusOut:
    """An order's status and each maker's share. It only reads: it never spends money and changes no order.

    For each share: her units, where her payment stands (reserved at PayPal, captured when she proved she shipped,
    or released if she could not deliver), when it must leave her and when she was told about it, her courier and
    tracking number once she has sent them, and how she is paid. In test mode PayPal is simulated, and the answer
    says so.
    """
    settings = get_settings()
    with new_session() as session:
        try:
            order = collective.load_order(session, order_id)
        except collective.DraftError as error:
            raise ToolError(str(error)) from None
        notices = notice_states(session, order.parts)
        shares = []
        for part in order.parts:
            rail, words, via_paypal = payout_words(part, settings)
            notice = notices.get(part.id)
            shares.append(
                ShareStatus(
                    seller_id=part.seller_id,
                    seller_name=part.seller.name,
                    quantity=part.quantity,
                    status=part.status.value,
                    status_words=collective.PART_STATUS_WORDS[part.status],
                    ship_by=ship_by(part),
                    told_at=_utc(notice.at) if notice and notice.state == "sent" else None,
                    carrier=part.carrier,
                    tracking_number=part.tracking_number,
                    tracking_on_paypal=part.paypal_tracker_id is not None,
                    delivered_at=delivered_utc(part),
                    on_time=on_time(part),
                    payout_rail=rail,
                    payout_words=words,
                    paid_through_paypal=via_paypal,
                    dropped_out=(part.drop_json or {}).get("state") == DROPPED,
                )
            )
        top_ups = session.scalars(
            select(Order).where(Order.parent_order_id == order.id).order_by(Order.created_at, Order.id)
        ).all()
        parent = session.get(Order, order.parent_order_id) if order.parent_order_id else None
        return OrderStatusOut(
            order_id=order.id,
            status=order.status.value,
            status_words=collective.ORDER_STATUS_WORDS[order.status],
            total_usd=server_total(order),
            units=sum(part.quantity for part in order.parts),
            approved=order.approved_at is not None,
            shares=shares,
            simulated=settings.OPENSTALL_MODE == "fake",
            top_ups=[
                TopUpStatus(
                    order_id=top_up.id,
                    status=top_up.status.value,
                    status_words=collective.ORDER_STATUS_WORDS[top_up.status],
                    total_usd=server_total(top_up),
                    units=sum(line.quantity for line in top_up.parts),
                    makers=[line.seller.name for line in top_up.parts],
                    replaces=_replaced(order, top_up),
                    approved=top_up.approved_at is not None,
                    approval_link=collective.approval_url(top_up.id),
                )
                for top_up in top_ups
            ],
            replaces=_replaced(parent, order),
        )


def _replaced(parent: Order | None, top_up: Order) -> str | None:
    """The dropped share of `parent` that `top_up` replaces, in words."""
    if parent is None or top_up.request_id is None:
        return None
    for part in parent.parts:
        if (part.drop_json or {}).get("request_id") == top_up.request_id:
            return f"{part.seller.name}'s {part.quantity} units of order {parent.id}, which she could not make"
    return None


def _utc(moment: datetime) -> datetime:
    """SQLite drops the zone; we always store UTC, so say so."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


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
