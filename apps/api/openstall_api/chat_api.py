"""Seller chats over HTTP, for the /seller-chat page: who has chatted, and each conversation."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openstall_api.db import get_session
from openstall_api.models import Channel, ChatMessage, ChatSession, ChatState, Direction, Seller

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


class MessageOut(BaseModel):
    id: str
    direction: Direction
    channel: Channel
    text: str | None
    media: list[MediaOut]
    created_at: datetime


class ChatSummary(BaseModel):
    seller: ChatSeller
    channel: Channel
    state: ChatState
    updated_at: datetime
    last_text: str | None
    messages: int


class Conversation(BaseModel):
    seller: ChatSeller
    messages: list[MessageOut]


def seller_out(seller: Seller) -> ChatSeller:
    return ChatSeller(id=seller.id, name=seller.name, city=seller.city, country=seller.country)


def media_out(item: dict[str, Any]) -> MediaOut:
    return MediaOut(
        url=item.get("url"),
        content_type=str(item.get("content_type") or ""),
        size=item.get("size"),
        refused=item.get("refused"),
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
    return Conversation(
        seller=seller_out(seller),
        messages=[
            MessageOut(
                id=message.id,
                direction=message.direction,
                channel=message.channel,
                text=message.text,
                media=[media_out(item) for item in message.media_json],
                created_at=aware(message.created_at),
            )
            for message in reversed(recent)
        ],
    )
