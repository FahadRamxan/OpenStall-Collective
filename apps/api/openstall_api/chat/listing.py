"""Her listing, drafted from her chat (spec 3.1, step 3): what she sends becomes a draft listing, kept on her chat
(ChatSession.draft_json) until she confirms it (prompt 19).

read_her_listing runs before her message is stored and outside any transaction, as look_at_photos and the voice notes
do: the vision model may take seconds. It reads everything she has said in this chat (typed, and her voice notes as
text) with her latest photos, so each reading is of the whole chat, not one message. Only a seller who has no live
listing yet is read: a maker already selling, such as the seeded ones, is answered by her own flows (pay-on-proof).

update_draft then merges the reading into her draft inside the transaction: a field read now replaces the one kept,
and one not read keeps it, so a fact she gave once is not lost when a later message does not repeat it. The photos are
hers, chosen by code: every photo she sent in this chat, latest last, at most MAX_PHOTOS.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_agents.adapters import LLM, LLMError, Media
from openstall_agents.listing_reader import ListingReading, Said, read_listing
from openstall_api.adapters import AdapterUnavailable
from openstall_api.chat.store import known_seller
from openstall_api.chat.voice import Heard
from openstall_api.db import new_session
from openstall_api.events import EventType, record_event
from openstall_api.media import MediaStore
from openstall_api.models import (
    Channel,
    ChatMessage,
    ChatSession,
    ChatState,
    Direction,
    Product,
    ProductStatus,
    Seller,
)

log = logging.getLogger(__name__)

MAX_PHOTOS = 5
# The listing's fields in the spec's order (3.1, "Required listing fields"), and how each is named to a person.
FIELDS: dict[str, str] = {
    "title": "what it is",
    "description": "a description",
    "category": "a category",
    "variants": "the colours or styles",
    "price_usd": "the price",
    "capacity_per_week": "how many a week",
    "ship_days": "how many days delivery takes",
    "ship_from_city": "the city it ships from",
    "photos": "a photo",
}
MAX_SOURCE = 4000  # her words kept on the draft, the latest last
# Where her listing is still being drafted; later states belong to confirming and publishing (prompts 18 and 19).
DRAFTING = frozenset({ChatState.COLLECTING, ChatState.ASKING})


@dataclass(frozen=True)
class Gathered:
    """Her chat so far, read before this message is stored: what she said and the keys of her kept photos."""

    maker: str
    said: list[Said]
    photo_keys: list[str]


def gather(
    session: Session, channel: Channel, address: str, seller_id: str | None, name_guess: str | None
) -> Gathered | None:
    """What she has said in this chat, or None when her listing is not being drafted: she already has a live
    listing, or her chat is past drafting."""
    seller = known_seller(session, channel, address, seller_id)
    if seller is None:
        return Gathered(maker=name_guess or "a new seller", said=[], photo_keys=[])
    if session.scalar(select(Product.id).where(Product.seller_id == seller.id, Product.status == ProductStatus.LIVE)):
        return None
    chat = session.scalar(select(ChatSession).where(ChatSession.seller_id == seller.id, ChatSession.channel == channel))
    if chat is not None and chat.state not in DRAFTING:
        return None
    said: list[Said] = []
    keys: list[str] = []
    if chat is not None:
        for message in session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat.id, ChatMessage.direction == Direction.INBOUND)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        ):
            said.extend(said_in(message.text, message.transcript, message.language))
            keys.extend(
                str(item["key"])
                for item in message.media_json
                if str(item.get("content_type", "")).startswith("image/") and "key" in item
            )
    return Gathered(maker=seller.name, said=said, photo_keys=keys)


def said_in(text: str | None, transcript: str | None, language: str | None) -> list[Said]:
    said = []
    if text:
        said.append(Said(text))
    if transcript:
        said.append(Said(transcript, voice_note=True, language=language))
    return said


def read_her_listing(
    channel: Channel,
    address: str,
    seller_id: str | None,
    name_guess: str | None,
    text: str,
    photos: Sequence[Media],
    heard: Heard,
    store: MediaStore,
    llm: Callable[[], LLM],
) -> ListingReading | None:
    """Before her message is stored: her listing as everything she has said and her latest photos tell it, with this
    message's words and photos. None, without asking any model, when this message adds nothing to read or her listing
    is not being drafted; None, logged, when the model cannot answer: her message is kept either way."""
    new_said = said_in(text, heard.transcript, heard.language)
    if not new_said and not photos:
        return None
    with new_session() as session:
        gathered = gather(session, channel, address, seller_id, name_guess)
    if gathered is None:
        return None
    earlier: list[Media] = []
    for key in gathered.photo_keys[-MAX_PHOTOS:]:
        try:
            earlier.append(Media(store.read(key), _image_type(key)))
        except (KeyError, OSError):
            log.warning("Her earlier photo %s could not be read for her listing", key)
    try:
        return read_listing(llm(), [*gathered.said, *new_said], [*earlier, *photos], maker=gathered.maker)
    except (LLMError, AdapterUnavailable) as error:
        log.warning("Her listing could not be read: %s", error)
        return None


def _image_type(key: str) -> str:
    return {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[key.rsplit(".", 1)[-1]]


def given(value: object) -> bool:
    """Whether a draft field has a value: any number is one; an empty text or list is not."""
    return value is not None and value != "" and value != []


def update_draft(session: Session, chat: ChatSession, seller: Seller, reading: ListingReading) -> dict[str, Any]:
    """Her draft with this reading merged in, kept on her chat, in the caller's transaction; the live feed is told
    when the listing changed. Call it after her message is saved, so its photos and words are counted."""
    draft: dict[str, Any] = dict(chat.draft_json or {})
    before = {name: draft.get(name) for name in FIELDS}
    read: dict[str, Any] = {
        "title": reading.title,
        "description": reading.description,
        "category": reading.category,
        "variants": list(reading.variants),
        "price_usd": str(reading.price_usd) if reading.price_usd is not None else None,
        "capacity_per_week": reading.capacity_per_week,
        "ship_days": reading.ship_days,
        "ship_from_city": reading.ship_from_city,
    }
    for name, value in read.items():
        if given(value) or name not in draft:
            draft[name] = value
    inbound = list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat.id, ChatMessage.direction == Direction.INBOUND)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    )
    # Each photo once (the store keeps the same photo once, so the same address), in the order she first sent it.
    draft["photos"] = list(
        dict.fromkeys(
            str(item["url"])
            for message in inbound
            for item in message.media_json
            if str(item.get("content_type", "")).startswith("image/") and item.get("url")
        )
    )[-MAX_PHOTOS:]
    draft["words"] = {**draft.get("words", {}), **reading.words}
    draft["source_text"] = "\n".join(
        said.words for message in inbound for said in said_in(message.text, message.transcript, message.language)
    )[-MAX_SOURCE:]
    draft["missing"] = [name for name in FIELDS if not given(draft.get(name))]
    chat.draft_json = draft
    if {name: draft.get(name) for name in FIELDS} != before:
        record_event(
            session,
            EventType.LISTING_DRAFT_UPDATED,
            draft_words(seller.name, draft),
            entity_id=seller.id,
            payload={"chat_id": chat.id, "title": draft.get("title"), "missing": draft["missing"]},
        )
    return draft


def described(draft: dict[str, Any]) -> str:
    """The draft in a few words: "Hand-embroidered cushion cover, $18.00 each, 4 a week, arrives in 9 days, from
    Lahore"."""
    parts = [str(draft.get("title") or "your item, not named yet")]
    if given(draft.get("price_usd")):
        parts.append(f"${draft['price_usd']} each")
    if given(draft.get("capacity_per_week")):
        parts.append(f"{draft['capacity_per_week']} a week")
    if given(draft.get("ship_days")):
        parts.append(f"arrives in {draft['ship_days']} days")
    if given(draft.get("ship_from_city")):
        parts.append(f"from {draft['ship_from_city']}")
    return ", ".join(parts)


def missing_words(draft: dict[str, Any]) -> str:
    names = [FIELDS[name] for name in draft.get("missing", [])]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)


def draft_words(name: str, draft: dict[str, Any]) -> str:
    """The live feed's line: "Amina's listing draft: Hand-embroidered cushion cover, $18.00 each, 4 a week; still to
    ask: how many days delivery takes and the city it ships from"."""
    if not draft.get("missing"):
        return f"{name}'s listing draft has everything it needs: {described(draft)}"
    return f"{name}'s listing draft: {described(draft)}; still to ask: {missing_words(draft)}"


def listing_reply(draft: dict[str, Any]) -> str:
    """What she is told after her listing is read: the draft so far, and what it still needs."""
    if not draft.get("missing"):
        return f"Your listing so far: {described(draft)}. That is everything it needs."
    return f"Your listing so far: {described(draft)}. Still needed: {missing_words(draft)}."
