"""Dev endpoints for UI tests and demos, in fake mode only. In sandbox mode they do not exist."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api import quotes
from openstall_api.adapters import AdapterRegistry, get_registry
from openstall_api.chat.handler import InboundFile, Refused, Sender
from openstall_api.chat.inbox import receive
from openstall_api.chat.store import channel_for
from openstall_api.db import get_session, new_session
from openstall_api.events_api import fake_mode_only
from openstall_api.fixtures import demo_shipment, fixture_photo, fixture_receipt, fixture_voice_note
from openstall_api.models import Offer, OrderPart, PartStatus, Seller
from openstall_api.offers import OfferOut
from openstall_api.orders_api import OrderOut, _load, order_out, payment_errors
from openstall_api.payments import pay_share, release_share
from openstall_api.quotes import create_quote_request, run_quote
from openstall_api.quotes_api import QuoteOut
from openstall_api.seed import DEMO_REQUEST, story_order
from openstall_api.tracking import track_on_paypal
from openstall_api.webhooks import deliver_fake_webhooks

router = APIRouter(prefix="/api/dev", tags=["dev"], dependencies=[Depends(fake_mode_only)])

SessionDep = Annotated[Session, Depends(get_session)]

# The carrier code PayPal's tracking API takes for a courier it does not list.
SIMULATED_CARRIER = "OTHER"


class NewOrder(BaseModel):
    order_id: str


class Released(BaseModel):
    released: int  # shares released


class StoryQuote(BaseModel):
    quote: QuoteOut
    offers: list[OfferOut]  # every proposal, in the order the agents made them
    valid_offers: list[OfferOut]  # each maker's valid offer, one at most


@router.get("/samples/voice-note.wav")
def sample_voice_note() -> Response:
    """Fake mode's sample voice note, which fake mode's speech to text hears as Amina telling OpenStall about her
    cushion covers in Urdu (fixtures.SAMPLE_VOICE_NOTE_SAYS). /seller-chat offers to attach it (GET
    /api/seller-chat/samples), so anyone can try a voice note without a microphone or an OpenAI key."""
    return Response(fixture_voice_note(), media_type="audio/wav")


@router.get("/samples/photo.png")
def sample_photo() -> Response:
    """Fake mode's sample product photo: the seeded Amina's cushion cover, which fake mode's stand-in model reads as
    fixtures.SAMPLE_PRODUCT. /seller-chat offers to attach it."""
    return Response(fixture_photo(), media_type="image/png")


@router.post("/story-orders", status_code=201)
def create_story_order(session: SessionDep) -> NewOrder:
    """A fresh draft of the story's order (12/11/10/7, $815.00), so each UI test can pay for an order of its own.
    The seeded makers must exist (scripts/seed_demo.py)."""
    order = story_order(session, datetime.now(UTC).date())
    session.commit()
    return NewOrder(order_id=order.id)


@router.post("/parts/{part_id}/proof")
def simulate_proof(
    part_id: str,
    session: SessionDep,
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
    background: BackgroundTasks,
) -> OrderOut:
    """Simulated proof of shipping for one share: a made-up tracking number (SIMULATED-<part id>, carrier OTHER),
    then the same pay_share the receipt photo will call (prompt 32), so the receipt can show paid shares now.

    A share with tracking of its own keeps it. A share that cannot be paid (released, or no payout rail can reach
    her) is refused with 409, and nothing is saved.
    """
    part = session.get(OrderPart, part_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"There is no order share called {part_id!r}.")
    if not part.tracking_number:
        part.tracking_number = f"SIMULATED-{part.id}"[:64]
        part.carrier = SIMULATED_CARRIER
    with payment_errors():
        pay_share(session, part_id, registry.payment_gateway)
    session.commit()
    # Her (simulated) tracking on her capture at simulated PayPal, as after a real receipt photo (prompt 33).
    track_on_paypal(part_id, lambda: registry.payment_gateway)
    session.expire_all()
    background.add_task(deliver_fake_webhooks)  # simulated PayPal's capture and payout confirmations follow
    return order_out(session, _load(session, part.order_id))


class PlayMessage(BaseModel):
    """What a seeded maker says, played from /seller-chat in fake mode."""

    text: str = Field(default="", max_length=4000)
    # Fake mode's courier receipt photo, with a made-up courier and tracking number for her country.
    receipt: bool = False


class PlayedOut(BaseModel):
    seller_id: str
    message_id: str
    replies: list[str]


@router.post("/sellers/{seller_id}/messages", status_code=201)
def play_seller(seller_id: str, body: PlayMessage, background: BackgroundTasks) -> PlayedOut:
    """Fake mode: a message as if this maker sent it, where she chats with OpenStall (WhatsApp if she has a number,
    else her web chat), so the seeded makers, who have no phone, can send their courier receipt and confirm it.
    It takes exactly the path a real message takes (chat/inbox.py); a share she proves is paid after the answer."""
    text = body.text.strip()
    if not text and not body.receipt:
        raise HTTPException(status_code=422, detail="Write what she says, or send her courier receipt photo.")
    with new_session() as session:
        seller = session.get(Seller, seller_id)
        if seller is None:
            raise HTTPException(status_code=404, detail=f"There is no seller called {seller_id!r}.")
        channel, country = channel_for(seller), seller.country
        address = seller.whatsapp_number or seller.web_chat_id or seller.id
    files: list[InboundFile | Refused] = []
    if body.receipt:
        files.append(InboundFile(fixture_receipt(*demo_shipment(country)), "image/png"))
    handled = receive(Sender(channel, address, seller_id=seller_id), text, files, background.add_task)
    return PlayedOut(
        seller_id=handled.seller_id, message_id=handled.message_id, replies=[reply.text for reply in handled.replies]
    )


@router.post("/release-reserved-shares")
def release_reserved_shares(
    session: SessionDep,
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
    background: BackgroundTasks,
) -> Released:
    """Release every reserved share, as if each of those makers had dropped out, so every maker has her seed capacity
    back: reserved shares are her committed units (offer_rules.py). UI tests that check the seed table's numbers call
    it first, because earlier spec files reserve story orders in the same database.
    """
    part_ids = session.scalars(
        select(OrderPart.id).where(OrderPart.status == PartStatus.AUTHORIZED).order_by(OrderPart.id)
    ).all()
    with payment_errors():
        for part_id in part_ids:
            release_share(session, part_id, registry.payment_gateway)
    session.commit()
    background.add_task(deliver_fake_webhooks)  # simulated PayPal's VOIDED confirmations follow
    return Released(released=len(part_ids))


@router.post("/quote", status_code=201)
def run_story_quote(session: SessionDep, registry: Annotated[AdapterRegistry, Depends(get_registry)]) -> StoryQuote:
    """The story's request (spec section 2: 40 hand-embroidered cushion covers for corporate gifts, at most $30 each,
    due in 30 days, to Chicago) quoted with fake mode's seller agents: every matching maker's agent asked, up to 3
    rounds. The request, each round and every proposal appear on /demo as they happen."""
    today = quotes.clock.today()
    request, products = create_quote_request(
        session, [DEMO_REQUEST], 40, Decimal("30.00"), today + timedelta(days=30), "Chicago", today
    )
    session.commit()
    run_quote(session, request, products, registry.llm, today)
    proposals = sorted(request_offers(session, request.id), key=lambda offer: (offer.created_at, offer.attempt))
    return StoryQuote(
        quote=QuoteOut.of(session, request),
        offers=proposals,
        valid_offers=[offer for offer in proposals if offer.is_valid],
    )


def request_offers(session: Session, request_id: str) -> list[OfferOut]:
    return [OfferOut.of(offer) for offer in session.scalars(select(Offer).where(Offer.request_id == request_id))]
