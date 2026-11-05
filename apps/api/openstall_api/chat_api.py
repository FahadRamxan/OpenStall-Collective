"""Seller chats over HTTP, for the /seller-chat page: who has chatted, and each conversation."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openstall_api.db import get_session
from openstall_api.models import Channel, ChatMessage, ChatSession, ChatState, Direction, Product, Seller
from openstall_api.settings import get_settings

router = APIRouter(prefix="/api", tags=["chats"])

SessionDep = Annotated[Session, Depends(get_session)]
MAX_MESSAGES = 200  # the most recent messages a conversation shows


def aware(moment: datetime) -> datetime:
    """SQLite drops the time zone; we always store UTC, so say so for the browser."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class ChatSeller(BaseModel):
    id: str
    name: str
    city: str | None
    country: str | None


class MediaOut(BaseModel):
    """A kept photo or voice note (url), or a file that was not kept and why (refused)."""

    url: str | None = None
    content_type: str
    size: int | None = None
    refused: str | None = None
    # OpenStall's answer spoken, in the message's language, for a maker who sent a voice note.
    spoken: bool = False


class MessageOut(BaseModel):
    id: str
    direction: Direction
    channel: Channel
    text: str | None
    media: list[MediaOut]
    # What her voice notes said, word for word as she said them (never translated), and the language it was heard
    # in (ISO 639-1). None when the message had no voice note, or none could be heard.
    transcript: str | None = None
    language: str | None = None
    created_at: datetime


class ChatSummary(BaseModel):
    seller: ChatSeller
    channel: Channel
    state: ChatState
    updated_at: datetime
    last_text: str | None
    messages: int


class ListingDraftOut(BaseModel):
    """Her listing as far as her chat has told it (spec 3.1 steps 3 and 4), before she confirms it: not live for
    buyers. Her limits (spec 3.3) are only for her own seller agent: the lowest price she would take for one and the
    fewest days she needs to make an order. `words`: the words she used for each number and her city, so a wrong
    reading can be traced. `missing`: the fields still to ask her for, in the spec's order, then her limits. `asked`:
    the one she was asked last, which her next message answers."""

    title: str | None = None
    description: str | None = None
    category: str | None = None
    variants: list[str] = Field(default_factory=list)
    price_usd: str | None = None
    capacity_per_week: int | None = None
    ship_days: int | None = None
    ship_from_city: str | None = None
    photos: list[str] = Field(default_factory=list)
    floor_price_usd: str | None = None
    min_lead_days: int | None = None
    words: dict[str, str] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    asked: str | None = None
    # Nothing is left to ask: she was sent all of it, and her yes would publish it (spec 3.1 step 5).
    confirming: bool = False


class LiveListingOut(BaseModel):
    """Her listing once her yes published it from this chat (spec 3.1 step 6): live for buyers' agents."""

    product_id: str
    title: str
    price_usd: str
    stall_path: str  # her stall page on the web app


class Conversation(BaseModel):
    seller: ChatSeller
    messages: list[MessageOut]
    # Her listing draft, while she is making one and until her yes (prompts 17 to 19); None otherwise.
    draft: ListingDraftOut | None = None
    # The listing her yes published from her chat (prompt 19); None before.
    listing: LiveListingOut | None = None
    # Fake mode only, for a maker with no phone of her own (the seeded makers): /seller-chat can play her, through
    # POST /api/dev/sellers/{id}/messages, to send her courier receipt and answer OpenStall.
    playable: bool = False


def seller_out(seller: Seller) -> ChatSeller:
    return ChatSeller(id=seller.id, name=seller.name, city=seller.city, country=seller.country)


def media_out(item: dict[str, Any]) -> MediaOut:
    return MediaOut(
        url=item.get("url"),
        content_type=str(item.get("content_type") or ""),
        size=item.get("size"),
        refused=item.get("refused"),
        spoken=bool(item.get("spoken")),
    )


@router.get("/chats")
def list_chats(session: SessionDep) -> list[ChatSummary]:
    """Every conversation with at least one message, the most recent first."""
    counts = (
        select(ChatMessage.session_id, func.count().label("messages"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    rows = session.execute(
        select(ChatSession, counts.c.messages)
        .join(counts, counts.c.session_id == ChatSession.id)
        .where(ChatSession.seller_id.is_not(None))
        .order_by(ChatSession.updated_at.desc())
    ).all()
    summaries = []
    for chat, messages in rows:
        last = session.scalar(
            select(ChatMessage.text)
            .where(ChatMessage.session_id == chat.id, ChatMessage.text.is_not(None))
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        summaries.append(
            ChatSummary(
                seller=seller_out(chat.seller),
                channel=chat.channel,
                state=chat.state,
                updated_at=aware(chat.updated_at),
                last_text=last,
                messages=messages,
            )
        )
    return summaries


@router.get("/chats/{seller_id}")
def get_conversation(seller_id: str, session: SessionDep) -> Conversation:
    """One seller's messages on every channel, oldest first."""
    seller = session.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail=f"There is no seller called {seller_id!r}.")
    recent = list(
        session.scalars(
            select(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.seller_id == seller_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(MAX_MESSAGES)
        )
    )
    drafting = session.scalar(
        select(ChatSession)
        .where(ChatSession.seller_id == seller_id, ChatSession.draft_json.is_not(None))
        .order_by(ChatSession.updated_at.desc())
        .limit(1)
    )
    draft, listing = None, None
    if drafting is not None and drafting.draft_json:
        if drafting.state != ChatState.LIVE:
            confirming = drafting.state == ChatState.AWAITING_CONFIRMATION
            draft = ListingDraftOut.model_validate({**drafting.draft_json, "confirming": confirming})
        elif (product := session.get(Product, drafting.draft_json.get("published", ""))) is not None:
            listing = LiveListingOut(
                product_id=product.id,
                title=product.title,
                price_usd=f"{product.price_usd:.2f}",
                stall_path=f"/stall/{seller.id}",
            )
    return Conversation(
        seller=seller_out(seller),
        draft=draft,
        listing=listing,
        playable=get_settings().OPENSTALL_MODE == "fake" and not seller.whatsapp_number and not seller.web_chat_id,
        messages=[
            MessageOut(
                id=message.id,
                direction=message.direction,
                channel=message.channel,
                text=message.text,
                media=[media_out(item) for item in message.media_json],
                transcript=message.transcript,
                language=message.language,
                created_at=aware(message.created_at),
            )
            for message in reversed(recent)
        ],
    )
