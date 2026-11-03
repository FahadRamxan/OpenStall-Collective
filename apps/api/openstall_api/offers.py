"""Seller agents on real data (spec 3.3): a maker's agent makes its offer for a stored quote request, and every
proposal is saved and shown on /demo.

The agent is packages/agents (seller_agent.py). This module builds its inputs from the database through
offer_rules.py, saves each proposal to offers with the code check's verdict, and records offer.proposed, then
offer.accepted or offer.rejected, in the caller's transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from openstall_agents.adapters import LLM
from openstall_agents.seller_agent import Maker, OfferOutcome, Proposal, make_offer, reason_words
from openstall_allocator import Listing, QuoteRequest, RejectionReason, SellerPolicy, lowest_allowed_price
from openstall_api.events import EventType, record_event
from openstall_api.models import Offer, Product
from openstall_api.models import QuoteRequest as QuoteRequestRow
from openstall_api.offer_rules import PolicyError, committed_units, listing_of, quote_request_of, seller_policy


class OfferOut(BaseModel):
    """One proposal a seller agent made, and what the code check said: a row of the /demo offers table."""

    id: str
    request_id: str
    seller_id: str
    seller_name: str
    product_id: str | None
    round: int
    attempt: int = Field(description="1 to 3 within the round: a refused proposal is retried with the reason.")
    unit_price: Decimal  # sent as a string such as "29.00", so it stays exact
    quantity: int
    delivery_date: date
    message: str | None
    is_valid: bool
    rejection_reason: RejectionReason | None
    why: str = Field(description='"valid", or why the code refused it, in words.')
    created_at: datetime

    @classmethod
    def of(cls, offer: Offer) -> "OfferOut":
        created_at = offer.created_at
        if created_at.tzinfo is None:  # SQLite drops the zone; we always store UTC, so say so for the browser
            created_at = created_at.replace(tzinfo=UTC)
        reason = None if offer.rejection_reason is None else RejectionReason(offer.rejection_reason)
        return cls(
            id=offer.id,
            request_id=offer.request_id,
            seller_id=offer.seller_id,
            seller_name=offer.seller.name,
            product_id=offer.product_id,
            round=offer.round,
            attempt=offer.attempt,
            unit_price=offer.unit_price,
            quantity=offer.quantity,
            delivery_date=offer.delivery_date,
            message=offer.message,
            is_valid=offer.is_valid,
            rejection_reason=reason,
            why=_why(offer, reason),
            created_at=created_at,
        )


def request_text(request: QuoteRequestRow) -> str:
    """What the buyer asked for, in their own words: each item's query."""
    queries = [str(item.get("query", "")).strip() for item in request.items_json if isinstance(item, dict)]
    return "; ".join(query for query in queries if query)


@dataclass(frozen=True)
class AgentInputs:
    """Everything one maker's agent needs for a round, read from the database before it runs, so the agent never
    touches the session: quotes.py runs agents side by side, in threads."""

    maker: Maker
    listing: Listing
    policy: SellerPolicy
    request: QuoteRequest
    committed_units: int
    request_text: str


def prepare(session: Session, request: QuoteRequestRow, product: Product) -> AgentInputs:
    """Her agent's inputs for this request. A maker whose policy cannot be read raises PolicyError."""
    seller = product.seller
    return AgentInputs(
        maker=Maker(seller_id=seller.id, name=seller.name, product_title=product.title),
        listing=listing_of(product),
        policy=seller_policy(seller, product),
        request=quote_request_of(request),
        committed_units=committed_units(session, [seller.id])[seller.id],
        request_text=request_text(request),
    )


def save_outcome(session: Session, request: QuoteRequestRow, product: Product, outcome: OfferOutcome) -> Offer | None:
    """A round's proposals saved, each with its events; her valid offer's row, if she made one. The caller commits."""
    valid = None
    for proposal in outcome.proposals:
        offer = _save(session, request, product, outcome.quantity, proposal)
        if offer is not None and offer.is_valid:
            valid = offer
    return valid


def ask_seller(
    session: Session,
    request: QuoteRequestRow,
    product: Product,
    llm: LLM,
    today: date,
    *,
    round: int = 1,
    history: Sequence[Proposal] = (),
    feedback: str | None = None,
) -> OfferOutcome:
    """One round of one maker's agent for the request: each proposal saved, and its events recorded. The caller
    commits. A maker whose policy cannot be read raises PolicyError, and nothing is saved."""
    agent = prepare(session, request, product)
    outcome = make_offer(
        agent.maker,
        agent.listing,
        agent.policy,
        agent.request,
        round,
        history,
        llm=llm,
        today=today,
        committed_units=agent.committed_units,
        request_text=agent.request_text,
        feedback=feedback,
    )
    save_outcome(session, request, product, outcome)
    return outcome


def _save(
    session: Session, request: QuoteRequestRow, product: Product, quantity: int, proposal: Proposal
) -> Offer | None:
    name = product.seller.name
    if proposal.unit_price is None:
        # No price, so no offer row. The feed still shows the try: every proposal is logged (spec 3.3, step 6).
        record_event(
            session,
            EventType.OFFER_REJECTED,
            f"{name}'s agent gave no usable price: {proposal.problem}",
            payload={
                "request_id": request.id,
                "seller_id": product.seller_id,
                "round": proposal.round,
                "attempt": proposal.attempt,
                "problem": proposal.problem,
            },
        )
        return None
    offer = Offer(
        request_id=request.id,
        seller_id=product.seller_id,
        product_id=product.id,
        unit_price=proposal.unit_price,
        quantity=quantity,
        delivery_date=request.deadline,
        message=proposal.message or None,
        is_valid=proposal.valid,
        rejection_reason=None if proposal.reason is None else proposal.reason.value,
        round=proposal.round,
        attempt=proposal.attempt,
        created_at=datetime.now(UTC),
    )
    offer.seller = product.seller
    offer.request = request
    session.add(offer)
    session.flush()
    row = OfferOut.of(offer).model_dump(mode="json")
    price = f"${proposal.unit_price:,.2f}"
    record_event(
        session,
        EventType.OFFER_PROPOSED,
        f"{name}'s agent proposed {price} each for {quantity}",
        entity_id=offer.id,
        payload=row,
    )
    if proposal.valid:
        summary = f"Code accepted {name}'s offer: {quantity} at {price} each"
        record_event(session, EventType.OFFER_ACCEPTED, summary, entity_id=offer.id, payload=row)
    else:
        summary = f"Code refused {name}'s {price}: {row['why']}"
        record_event(session, EventType.OFFER_REJECTED, summary, entity_id=offer.id, payload=row)
    return offer


def _why(offer: Offer, reason: RejectionReason | None) -> str:
    """The code check's verdict in words, with her lowest price and the buyer's maximum."""
    lowest = Decimal("0.00")
    if reason is RejectionReason.BELOW_FLOOR:
        product = next((p for p in offer.seller.products if p.id == offer.product_id), None)
        if product is None:
            return "below her lowest price"
        try:
            lowest = lowest_allowed_price(seller_policy(offer.seller, product), listing_of(product))
        except PolicyError:
            return "below her lowest price"
    return reason_words(reason, quote_request_of(offer.request), lowest)
