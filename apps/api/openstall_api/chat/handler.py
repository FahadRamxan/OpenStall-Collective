"""The chat handler: what happens when a seller sends us something, on any channel.

handle_inbound finds or creates the seller and her chat, stores her message and the replies, and records both in the
event log, so pages showing the chat update live. The caller delivers the replies: the WhatsApp webhook sends them
through the Messenger. Later steps add the listing conversation itself (spec 3.1); for now the replies only say
when a file could not be kept.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.events import EventType, record_event
from openstall_api.media import MediaRejected, MediaStore
from openstall_api.models import Channel, ChatMessage, ChatSession, ChatState, DataSource, Direction, Seller, utcnow

# The countries in the demo, by dialing code. Other numbers leave the country empty until the seller says.
DIALING_CODES = {"92": "PK", "91": "IN", "52": "MX", "44": "GB", "1": "US"}
CHANNEL_WORDS = {Channel.WHATSAPP: "on WhatsApp", Channel.WEB: "in the web chat"}


@dataclass(frozen=True)
class Sender:
    """Who a message is from. On WhatsApp, her number in E.164 form, and her profile name as a first guess."""

    channel: Channel
    address: str
    name_guess: str | None = None


@dataclass(frozen=True)
class InboundFile:
    """A photo or voice note as received, before it is kept."""

    data: bytes
    content_type: str


@dataclass(frozen=True)
class Refused:
    """A file that could not even be fetched or kept, and why, in words for the seller."""

    reason: str
    content_type: str = ""


@dataclass(frozen=True)
class Reply:
    text: str


@dataclass(frozen=True)
class HandledMessage:
    seller_id: str
    message_id: str
    replies: list[Reply] = field(default_factory=list)


def country_of(number: str) -> str | None:
    digits = number.lstrip("+")
    for code in sorted(DIALING_CODES, key=len, reverse=True):
        if digits.startswith(code):
            return DIALING_CODES[code]
    return None


def find_seller(session: Session, sender: Sender) -> Seller:
    """The seller behind a sender, made on her first message. Her profile name is only a first guess at her name."""
    seller = session.scalar(select(Seller).where(Seller.whatsapp_number == sender.address))
    if seller is None:
        seller = Seller(
            name=(sender.name_guess or "New seller")[:120],
            whatsapp_number=sender.address,
            country=country_of(sender.address),
            data_source=DataSource.LIVE,
        )
        session.add(seller)
        session.flush()
    return seller


def find_chat(session: Session, seller: Seller, channel: Channel) -> ChatSession:
    chat = session.scalar(select(ChatSession).where(ChatSession.seller_id == seller.id, ChatSession.channel == channel))
    if chat is None:
        chat = ChatSession(seller_id=seller.id, channel=channel, state=ChatState.COLLECTING)
        session.add(chat)
        session.flush()
    return chat


def keep_media(store: MediaStore, files: Sequence[InboundFile | Refused]) -> list[dict[str, Any]]:
    """Each file kept in the media store, or the reason it was not, as stored on the message."""
    kept: list[dict[str, Any]] = []
    for item in files:
        if isinstance(item, Refused):
            kept.append({"refused": item.reason, "content_type": item.content_type})
            continue
        try:
            stored = store.save(item.data, item.content_type)
        except MediaRejected as error:
            kept.append({"refused": str(error), "content_type": item.content_type})
            continue
        kept.append({"key": stored.key, "url": stored.url, "content_type": stored.content_type, "size": stored.size})
    return kept


def describe(text: str, media: list[dict[str, Any]]) -> str:
    """What a message holds, for the live feed: "a photo and a message", "2 photos and a voice note" ..."""
    photos = sum(1 for item in media if str(item.get("content_type", "")).startswith("image/") and "key" in item)
    voice = sum(1 for item in media if str(item.get("content_type", "")).startswith("audio/") and "key" in item)
    parts = []
    if photos:
        parts.append("a photo" if photos == 1 else f"{photos} photos")
    if voice:
        parts.append("a voice note" if voice == 1 else f"{voice} voice notes")
    if text:
        parts.append("a message")
    if not parts:
        return "a file we could not keep" if media else "an empty message"
    return " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 1 else parts)


def save_message(
    session: Session, chat: ChatSession, direction: Direction, text: str, media: list[dict[str, Any]]
) -> ChatMessage:
    message = ChatMessage(
        session_id=chat.id, direction=direction, channel=chat.channel, text=text or None, media_json=media
    )
    session.add(message)
    chat.updated_at = utcnow()
    session.flush()
    return message


def handle_inbound(
    session: Session, store: MediaStore, sender: Sender, text: str, files: Sequence[InboundFile | Refused]
) -> HandledMessage:
    """Store a seller's message and work out the replies. The caller commits, then delivers the replies."""
    seller = find_seller(session, sender)
    chat = find_chat(session, seller, sender.channel)
    media = keep_media(store, files)
    message = save_message(session, chat, Direction.INBOUND, text, media)
    record_event(
        session,
        EventType.MESSAGE_RECEIVED,
        f"{seller.name} sent {describe(text, media)} {CHANNEL_WORDS[sender.channel]}",
        entity_id=seller.id,
        payload={"channel": sender.channel, "message_id": message.id},
    )
    replies = [
        Reply(f"Sorry, I could not keep one of your files: {item['refused']} Photos and voice notes work best.")
        for item in media
        if "refused" in item
    ]
    for reply in replies:
        sent = save_message(session, chat, Direction.OUTBOUND, reply.text, [])
        record_event(
            session,
            EventType.MESSAGE_SENT,
            f"OpenStall replied to {seller.name} {CHANNEL_WORDS[sender.channel]}",
            entity_id=seller.id,
            payload={"channel": sender.channel, "message_id": sent.id},
        )
    return HandledMessage(seller_id=seller.id, message_id=message.id, replies=replies)
