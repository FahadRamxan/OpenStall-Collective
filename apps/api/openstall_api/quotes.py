"""Quote requests and negotiation rounds (spec 3.2, request_quote; spec 3.3, the negotiation limit).

One request asks every matching maker's agent for an offer. The agents run side by side, each within a time limit; a
maker whose agent runs out of time makes no offer that round. After a round, makers without a valid offer get another
chance with the buyer's limits as feedback, up to 3 rounds in all, and the quote stops early once every maker asked
has a valid offer. Matching is search_products' own (search.py): the request's words, and makers who can make some
by the deadline. A list price over the buyer's maximum does not leave a maker out, since her agent can come down.

The agents themselves only talk to the model, in threads of their own; every read and write of the database happens
here, on the caller's session. run_quote commits after each round, so /demo shows each round as it ends, and no
transaction stays open while the agents wait for the model.
"""

from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from openstall_agents.adapters import LLM
from openstall_agents.seller_agent import OfferOutcome, Proposal, make_offer
from openstall_allocator import Clock, SystemClock
from openstall_api.allocation import plan_quote
from openstall_api.events import EventType, record_event
from openstall_api.models import Offer, Product
from openstall_api.models import QuoteRequest as QuoteRequestRow
from openstall_api.offers import AgentInputs, prepare, save_outcome
from openstall_api.search import SearchError, SearchFilters, find_products

MAX_ROUNDS = 3  # spec 3.3: at most 3 rounds per seller for each request
AGENT_TIME_LIMIT = 20.0  # seconds one maker's agent has for a round

# Where "today" comes from: UTC, like the offer rules and search. Tests fix it with a FixedClock.
clock: Clock = SystemClock()


class QuoteError(ValueError):
    """The request cannot be quoted as asked. The message says why, in words a buyer agent can act on."""


@dataclass(frozen=True)
class QuoteResult:
    """A finished quote: the request, each maker's valid offer, and how much the valid offers add up to."""

    request: QuoteRequestRow
    asked: tuple[str, ...]  # seller ids, best match first
    offers: dict[str, Offer]  # seller id: her valid offer, one at most
    rounds: int

    @property
    def total_capacity(self) -> int:
        return sum(offer.quantity for offer in self.offers.values())

    @property
    def short_by(self) -> int:
        return max(0, self.request.quantity - self.total_capacity)


def create_quote_request(
    session: Session,
    queries: Sequence[str],
    quantity: int,
    max_unit_price: Decimal,
    deadline: date,
    ship_to: str,
    today: date,
) -> tuple[QuoteRequestRow, list[Product]]:
    """Store the request and find the makers to ask: each matching maker once, with her best-matching listing.
    Raises QuoteError for a request that cannot be quoted. The caller commits."""
    wanted = [query.strip() for query in queries if query.strip()]
    if not wanted:
        raise QuoteError("Say what you want: give at least one item, such as 'embroidered cushion covers'.")
    if quantity < 1:
        raise QuoteError(f"The quantity must be at least 1, not {quantity}.")
    if max_unit_price <= 0 or max_unit_price != max_unit_price.quantize(Decimal("0.01")):
        raise QuoteError(f"The maximum unit price must be more than $0 and in whole cents, not {max_unit_price}.")
    if deadline <= today:
        raise QuoteError(f"The deadline {deadline.isoformat()} must be after today, {today.isoformat()} (UTC).")
    if not ship_to.strip():
        raise QuoteError("Say which city the order ships to.")
    try:
        found = find_products(
            session, " ".join(wanted), SearchFilters(quantity=quantity, deadline=deadline, ship_to=ship_to), today
        )
    except SearchError as error:
        raise QuoteError(str(error)) from error
    products: list[Product] = []
    for result in found:
        if all(product.seller_id != result.seller_id for product in products):
            product = session.get(Product, result.product_id)
            assert product is not None
            products.append(product)
    request = QuoteRequestRow(
        items_json=[{"query": query} for query in wanted],
        quantity=quantity,
        max_unit_price=max_unit_price,
        deadline=deadline,
        ship_to=ship_to.strip(),
        asked=len(products),
        created_at=datetime.now(UTC),
    )
    session.add(request)
    session.flush()
    makers = "1 maker matches" if len(products) == 1 else f"{len(products)} makers match"
    record_event(
        session,
        EventType.QUOTE_REQUESTED,
        f"A buyer agent asked for {quantity} × “{'; '.join(wanted)}” at most ${max_unit_price:,.2f} each by "
        f"{deadline:%B} {deadline.day}, to {request.ship_to}: {makers}",
        entity_id=request.id,
        payload={
            "queries": wanted,
            "quantity": quantity,
            "max_unit_price": max_unit_price,
            "deadline": deadline,
            "ship_to": request.ship_to,
            "asked": [product.seller_id for product in products],
        },
    )
    return request, products


def run_quote(
    session: Session,
    request: QuoteRequestRow,
    products: Sequence[Product],
    llm: LLM,
    today: date,
    *,
    time_limit: float = AGENT_TIME_LIMIT,
    max_rounds: int = MAX_ROUNDS,
) -> QuoteResult:
    """Ask each maker's agent, side by side, round by round, and keep each maker's valid offer. When the rounds are
    done, the valid offers are split with the allocator (allocation.py). Commits after each round and at the end."""
    by_seller = {product.seller_id: product for product in products}
    waiting = list(by_seller)
    history: dict[str, list[Proposal]] = defaultdict(list)
    offers: dict[str, Offer] = {}
    rounds = 0
    for round in range(1, max_rounds + 1):
        if not waiting:
            break
        rounds = round
        inputs = {seller_id: prepare(session, request, by_seller[seller_id]) for seller_id in waiting}
        session.commit()  # nothing stays locked while the agents wait for the model
        feedback = None if round == 1 else round_feedback(request)
        outcomes = _ask_side_by_side(inputs, llm, today, round, history, feedback, time_limit)
        for seller_id in list(waiting):
            product = by_seller[seller_id]
            outcome = outcomes.get(seller_id)
            if not isinstance(outcome, OfferOutcome):
                why = "ran out of time" if outcome is None else f"failed ({type(outcome).__name__})"
                record_event(
                    session,
                    EventType.OFFER_REJECTED,
                    f"{product.seller.name}'s agent {why} in round {round}: no offer this round",
                    payload={"request_id": request.id, "seller_id": seller_id, "round": round},
                )
                continue
            history[seller_id].extend(outcome.proposals)
            valid = save_outcome(session, request, product, outcome)
            if valid is not None:
                offers[seller_id] = valid
                waiting.remove(seller_id)
            elif outcome.quantity == 0:
                waiting.remove(seller_id)  # she can make none by the deadline: asking again cannot help
        request.rounds = round
        record_event(
            session,
            EventType.QUOTE_ROUND_FINISHED,
            f"Round {round} done: {len(offers)} of {len(by_seller)} makers have a valid offer",
            entity_id=request.id,
            payload={"round": round, "valid_offers": len(offers), "asked": len(by_seller)},
        )
        session.commit()
    result = QuoteResult(request=request, asked=tuple(by_seller), offers=offers, rounds=rounds)
    request.completed_at = datetime.now(UTC)
    valid = "1 valid offer" if len(offers) == 1 else f"{len(offers)} valid offers"
    short = f", {result.short_by} short of the {request.quantity} asked for" if result.short_by else ""
    record_event(
        session,
        EventType.QUOTE_COMPLETED,
        f"The quote is done: {valid} for {result.total_capacity} units{short}",
        entity_id=request.id,
        payload={
            "rounds": rounds,
            "valid_offers": len(offers),
            "total_capacity": result.total_capacity,
            "requested": request.quantity,
        },
    )
    plan_quote(session, request)
    session.commit()
    return result


def round_feedback(request: QuoteRequestRow) -> str:
    """What every maker still without a valid offer hears before the next round: the buyer's limits."""
    return (
        f"The buyer's maximum is ${request.max_unit_price:,.2f} a unit, for {request.quantity} units by "
        f"{request.deadline:%B} {request.deadline.day}. Your earlier prices were refused: offer one within your limits "
        "and theirs."
    )


def _ask_side_by_side(
    inputs: dict[str, AgentInputs],
    llm: LLM,
    today: date,
    round: int,
    history: dict[str, list[Proposal]],
    feedback: str | None,
    time_limit: float,
) -> dict[str, OfferOutcome | BaseException]:
    """Each agent's round, in threads of their own. An agent still busy at the time limit is left out of the answer;
    its thread finishes on its own, and nothing it returns is saved. An agent that failed gives its exception."""
    pool = ThreadPoolExecutor(max_workers=max(1, len(inputs)), thread_name_prefix="seller-agent")
    try:
        futures = {
            pool.submit(
                make_offer,
                agent.maker,
                agent.listing,
                agent.policy,
                agent.request,
                round,
                history[seller_id],
                llm=llm,
                today=today,
                committed_units=agent.committed_units,
                request_text=agent.request_text,
                feedback=feedback,
            ): seller_id
            for seller_id, agent in inputs.items()
        }
        done, _ = wait(futures, timeout=time_limit)
        return {futures[future]: future.exception() or future.result() for future in done}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
