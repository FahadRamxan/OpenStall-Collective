"""The chat handler: what happens when a seller sends us something, on WhatsApp or on /seller-chat.

handle_inbound is the one function both channels call (spec 3.1), so the same input gives the same stored messages
and the same replies. It finds or creates the seller and her chat, stores her message and the replies, and records
both in the event log, so pages showing the chat update live. The caller delivers the replies: the WhatsApp webhook
sends them through the Messenger, and the web chat shows them.

The chat moves through the states collecting, asking, awaiting_confirmation and live. A new seller is welcomed; while
her listing is drafted (collecting, then asking), each answer tells her the listing so far and asks one question, in
her language (chat/asking.py). Once nothing is missing she gets all of it back and must say yes; her yes publishes it
(chat/publish.py), in this transaction, and anything else is read as a change. Once live, she is told where it is.

Her voice notes are turned into text before the message is stored (listen_to_voice_notes, outside any transaction;
chat/voice.py): the words go on her message as she said them, and their language on her profile if she has none yet.
Then, while she has no live listing, her whole chat is read into a draft listing (read_listing_from, chat/listing.py),
kept on her chat. Her language decides the templates she is answered in: the welcome and the questions.

A maker whose share waits for proof of shipping is answered by the receipt flow first (proof.py): her courier receipt
photo is read before the message is stored (look_at_photos, outside any transaction), she confirms the number, and the
shares to pay come back in HandledMessage.pay_after, for the caller to pay once the message is committed.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_agents.adapters import LLM, Media, SpeechToText
from openstall_agents.listing_reader import ListingReading
from openstall_api.chat.asking import asking_reply, live_reply
from openstall_api.chat.listing import DRAFTING, read_her_listing, update_draft
from openstall_api.chat.publish import publish, said_yes, stall_url
from openstall_api.chat.store import CHANNEL_WORDS, DIALING_CODES, country_of, find_chat, save_message
from openstall_api.chat.voice import (
    LANGUAGE_BY_COUNTRY,
    Heard,
    listen,
    remember_language,
    transcribed_words,
    unclear,
    written_language,
)
from openstall_api.settings import get_settings
from openstall_api.events import EventType, record_event
from openstall_api.media import ALLOWED_TYPES, MAX_BYTES, MediaRejected, MediaStore
from openstall_api.models import Channel, ChatMessage, ChatSession, ChatState, DataSource, Direction, Seller
from openstall_api.advance import advance_turn
from openstall_api.healing import drop_turn
from openstall_api.proof import PhotoReading, look_at_photo, proof_turn
from openstall_api.wording import LOCALES, say, template_language

# Kept here too: they moved to chat/store.py.
__all__ = ["CHANNEL_WORDS", "DIALING_CODES", "country_of", "find_chat", "save_message"]


# The first answer a seller gets, in her language when it is known (from her first voice note, or her profile).
WELCOMES = {
    "en": "Welcome to OpenStall! Send photos of what you make and tell me about it, by text or a voice note. I will "
    "turn it into a listing that AI shopping agents can find, and you are paid through PayPal when you ship.",
    "ur": "OpenStall میں خوش آمدید! اپنی ہاتھ سے بنی چیزوں کی تصویریں بھیجیں، اور ان کے بارے میں لکھ کر یا وائس نوٹ "
    "میں بتائیں۔ ہم اس سے آپ کا اشتہار بنائیں گے جسے اے آئی شاپنگ ایجنٹ ڈھونڈ سکیں گے، اور سامان بھیجنے پر آپ کو "
    "PayPal سے ادائیگی ہوگی۔",
    "hi": "OpenStall में आपका स्वागत है! अपनी हाथ से बनी चीज़ों की फ़ोटो भेजें, और उनके बारे में लिखकर या वॉइस नोट में "
    "बताएँ। हम इससे आपकी लिस्टिंग बनाएँगे जिसे AI शॉपिंग एजेंट ढूँढ सकेंगे, और सामान भेजने पर आपको PayPal से भुगतान "
    "होगा।",
    "es": "¡Te damos la bienvenida a OpenStall! Mándame fotos de lo que haces y cuéntame de ello, por mensaje o nota de "
    "voz. Con eso armo un anuncio que los agentes de compra con IA pueden encontrar, y PayPal te paga cuando envías.",
}
assert WELCOMES.keys() == LOCALES.keys(), "every template language welcomes her in its own words"
WELCOME = WELCOMES["en"]
NUDGE = "Send photos of what you make, or tell me the price and how many you can make each week."
# The answer when there is nothing to ask her yet (no draft listing, no live one), in her template language. English
# names what arrived; the others thank her for her message, whatever it was. Urdu and Hindi are written so that they
# fit any maker, a man as well as a woman: the verb agrees with the item, never with the maker (test_wording_fits).
THANKS = {
    "en": "Thank you, I have {what}. " + NUDGE,
    "ur": "شکریہ، آپ کا پیغام مل گیا۔ اپنی چیز کی تصویریں بھیجیں، یا اس کی قیمت بتائیں اور یہ کہ ہفتے میں کتنے تیار ہو "
    "سکتے ہیں۔",
    "hi": "धन्यवाद, आपका संदेश मिल गया। अपनी चीज़ की फ़ोटो भेजें, या उसकी कीमत बताएँ और यह कि हफ़्ते में कितने तैयार हो "
    "सकते हैं।",
    "es": "Gracias, ya recibí tu mensaje. Mándame fotos de lo que haces, o dime el precio y cuántos puedes hacer por "
    "semana.",
}
assert THANKS.keys() == LOCALES.keys(), "every template language thanks her in its own words"


@dataclass(frozen=True)
class Sender:
    """Who a message is from. On WhatsApp: her number in E.164 form, and her profile name as a first guess at her
    name. On the web: the demo phone id her browser keeps. `seller_id`: fake mode playing a seeded maker, who has no
    phone of her own (POST /api/dev/sellers/{id}/messages)."""

    channel: Channel
    address: str
    name_guess: str | None = None
    seller_id: str | None = None


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
    # Shares she proved she shipped, to capture and pay once this message is committed (proof.pay_on_proof).
    pay_after: list[str] = field(default_factory=list)
    # Shares she dropped out of, to release and re-plan once this message is committed (healing.heal_after).
    heal_after: list[str] = field(default_factory=list)
    # Advances she accepted, to pay out once this message is committed (advance.pay_advance_after).
    advance_after: list[str] = field(default_factory=list)
    # The listing her yes published, for the caller to announce once this message is committed.
    published: str | None = None
    # Each reply's stored message, in order, and the template language they are in: a maker who sent a voice note
    # hears them spoken (chat/spoken.py).
    reply_ids: list[str] = field(default_factory=list)
    language: str = "en"


def opening_language(seller: Seller, text: str) -> str | None:
    """Her country's language (Urdu for Pakistan) for a message that says nothing of her own: only the start word her
    link to OpenStall wrote for her (WHAPI_START_WORD). Not saved: her own words decide her language."""
    word = get_settings().WHAPI_START_WORD
    if word and text.strip().strip("!.").casefold() == word.casefold():
        return LANGUAGE_BY_COUNTRY.get(seller.country or "")
    return None


def find_seller(session: Session, sender: Sender) -> Seller:
    """The seller behind a sender, made on her first message. Her profile name is only a first guess at her name."""
    if sender.seller_id is not None:  # fake mode playing a seeded maker: the caller checked she exists
        played = session.get(Seller, sender.seller_id)
        if played is None:
            raise LookupError(f"There is no seller called {sender.seller_id!r}.")
        return played
    if sender.channel == Channel.WHATSAPP:
        seller = session.scalar(select(Seller).where(Seller.whatsapp_number == sender.address))
        made = {"whatsapp_number": sender.address, "country": country_of(sender.address)}
        name = sender.name_guess or "New seller"
    else:
        seller = session.scalar(select(Seller).where(Seller.web_chat_id == sender.address))
        made = {"web_chat_id": sender.address}
        name = sender.name_guess or f"Web seller {sender.address[-4:].upper()}"
    if seller is None:
        seller = Seller(name=name[:120], data_source=DataSource.LIVE, **made)
        session.add(seller)
        session.flush()
    return seller


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


def received(text: str, media: list[dict[str, Any]]) -> str | None:
    """What arrived, in words for the seller: "your photo and your message". None when nothing was kept."""
    photos = sum(1 for item in media if str(item.get("content_type", "")).startswith("image/") and "key" in item)
    voice = sum(1 for item in media if str(item.get("content_type", "")).startswith("audio/") and "key" in item)
    parts = []
    if photos:
        parts.append("your photo" if photos == 1 else f"your {photos} photos")
    if voice:
        parts.append("your voice note" if voice == 1 else f"your {voice} voice notes")
    if text:
        parts.append("your message")
    if not parts:
        return None
    return " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 1 else parts)


def refusals(media: list[dict[str, Any]]) -> list[Reply]:
    """One apology for each file that could not be kept."""
    return [
        Reply(f"Sorry, I could not keep one of your files: {item['refused']} Photos and voice notes work best.")
        for item in media
        if "refused" in item
    ]


def turn(
    chat: ChatSession,
    first: bool,
    text: str,
    media: list[dict[str, Any]],
    heard: Heard,
    draft: dict[str, Any] | None = None,
    language: str = "en",
    live_at: str | None = None,
) -> list[Reply]:
    """The chat's answer to one message, from its state. Files that could not be kept, then voice notes that could not
    be heard, are always said first. While her listing is drafted (`draft`), she is told the listing so far and asked
    the one question open now, in her template language. Once her listing is live (`live_at`, her stall), she is
    told where it is."""
    replies = refusals(media) + [Reply(words) for words in unclear(heard)]
    what = received(text, media)
    if first:
        replies.append(Reply(say(language, lambda code: WELCOMES[code])))
    if draft is not None:
        replies.append(Reply(asking_reply(draft, language, thanks=bool(what) and not first)))
    elif live_at is not None:
        replies.append(Reply(live_reply(language, live_at, again=True)))
    elif what and not first:
        code = language if language in THANKS else "en"
        replies.append(Reply(say(code, lambda used: THANKS[used].format(what=what))))
    return replies


def look_at_photos(
    sender: Sender, files: Sequence[InboundFile | Refused], llm: Callable[[], LLM]
) -> PhotoReading | None:
    """Before her message is stored: if she has a share waiting for proof of shipping, what the vision model reads on
    the first photo she sent (proof.look_at_photo). None, without asking any model, otherwise."""
    photos = [
        (index, item.data, item.content_type)
        for index, item in enumerate(files)
        if isinstance(item, InboundFile) and item.content_type.startswith("image/")
    ]
    if not photos:
        return None
    return look_at_photo(sender.channel, sender.address, sender.seller_id, photos[0], llm)


def keepable(files: Sequence[InboundFile | Refused], kind: str) -> list[Media]:
    """Her files of one kind ("image/" or "audio/") that the media store will keep: only these are sent anywhere."""
    return [
        Media(item.data, item.content_type)
        for item in files
        if isinstance(item, InboundFile)
        and item.content_type.startswith(kind)
        and item.content_type in ALLOWED_TYPES
        and len(item.data) <= MAX_BYTES
    ]


def listen_to_voice_notes(
    files: Sequence[InboundFile | Refused], speech: Callable[[], SpeechToText], language: str | None = None
) -> Heard:
    """Before her message is stored: what each voice note she sent says (voice.listen), with the language she is
    known to speak as a hint (voice.language_hint). The adapter is not even made when there are none."""
    return listen(keepable(files, "audio/"), speech, language)


def read_listing_from(
    sender: Sender,
    text: str,
    files: Sequence[InboundFile | Refused],
    heard: Heard,
    store: MediaStore,
    llm: Callable[[], LLM],
) -> ListingReading | None:
    """Before her message is stored: her listing as her whole chat tells it, with this message (listing.py). None
    when there is nothing new to read, or she is not drafting a listing."""
    return read_her_listing(
        sender.channel,
        sender.address,
        sender.seller_id,
        sender.name_guess,
        text,
        keepable(files, "image/"),
        heard,
        store,
        llm,
    )


def handle_inbound(
    session: Session,
    store: MediaStore,
    sender: Sender,
    text: str,
    files: Sequence[InboundFile | Refused],
    photo: PhotoReading | None = None,
    heard: Heard | None = None,
    reading: ListingReading | None = None,
) -> HandledMessage:
    """Store a seller's message and work out the replies. The caller commits, then delivers the replies, then pays
    any share in `pay_after`. `photo` is what look_at_photos read on her photo, `heard` what listen_to_voice_notes
    heard in her voice notes, and `reading` her listing as read_listing_from read it, all before this transaction."""
    heard = heard or Heard()
    seller = find_seller(session, sender)
    chat = find_chat(session, seller, sender.channel)
    first = not session.scalar(
        select(ChatMessage.id).where(ChatMessage.session_id == chat.id, ChatMessage.direction == Direction.INBOUND)
    )
    media = keep_media(store, files)
    message = save_message(session, chat, Direction.INBOUND, text, media)
    message.transcript = heard.transcript
    message.language = heard.language
    record_event(
        session,
        EventType.MESSAGE_RECEIVED,
        f"{seller.name} sent {describe(text, media)} {CHANNEL_WORDS[sender.channel]}",
        entity_id=seller.id,
        payload={"channel": sender.channel, "message_id": message.id},
    )
    if heard.texts:
        saved = remember_language(seller, heard.language)
        record_event(
            session,
            EventType.MESSAGE_TRANSCRIBED,
            transcribed_words(seller.name, heard, saved),
            entity_id=seller.id,
            payload={
                "channel": sender.channel,
                "message_id": message.id,
                "language": heard.language,
                "language_saved": saved,
            },
        )
    # Typed in Urdu (or Hindi), with no language on her profile yet: that is her language from now on.
    remember_language(seller, written_language(text, seller.country))
    proof = proof_turn(session, seller, text, media, photo, message.id)
    # Her words typed and said: "I can't make it" counts in a voice note too.
    said = " ".join(words for words in (text, heard.transcript) if words)
    drop = drop_turn(session, seller, said, message.id) if proof is None else None
    advance = advance_turn(session, seller, said, message.id) if proof is None and drop is None else None
    language = template_language(seller.language or opening_language(seller, text))
    published: str | None = None
    if proof is not None:
        replies = refusals(media) + [Reply(words) for words in unclear(heard)] + [Reply(r) for r in proof.replies]
    elif drop is not None:
        replies = refusals(media) + [Reply(words) for words in unclear(heard)] + [Reply(r) for r in drop.replies]
    elif advance is not None:
        replies = (
            refusals(media) + [Reply(words) for words in unclear(heard)] + [Reply(r) for r in advance.replies]
        )
    elif confirmed(chat, text, heard, media):
        published = publish(session, chat, seller).id
        live = [Reply(live_reply(language, stall_url(seller)))]
        replies = refusals(media) + [Reply(words) for words in unclear(heard)] + live
    else:
        # A draft starts once something for a listing is read; once there is one, every message of hers counts, even
        # one the model could not read, so the question open is asked again.
        started = bool(chat.draft_json) or (reading is not None and not reading.empty)
        drafting = chat.state in DRAFTING and started
        draft = update_draft(session, chat, seller, reading, message.id) if drafting else None
        live_at = stall_url(seller) if chat.state == ChatState.LIVE else None
        replies = turn(chat, first, text, media, heard, draft, language, live_at)
    reply_ids: list[str] = []
    for reply in replies:
        sent = save_message(session, chat, Direction.OUTBOUND, reply.text, [])
        reply_ids.append(sent.id)
        record_event(
            session,
            EventType.MESSAGE_SENT,
            f"OpenStall replied to {seller.name} {CHANNEL_WORDS[sender.channel]}",
            entity_id=seller.id,
            payload={"channel": sender.channel, "message_id": sent.id},
        )
    return HandledMessage(
        seller_id=seller.id,
        message_id=message.id,
        replies=replies,
        pay_after=proof.pay_after if proof else [],
        heal_after=drop.heal_after if drop else [],
        advance_after=advance.pay_after if advance else [],
        published=published,
        reply_ids=reply_ids,
        language=language,
    )


def confirmed(chat: ChatSession, text: str, heard: Heard, media: list[dict[str, Any]]) -> bool:
    """Whether this message is her yes to the listing she was sent (spec 3.1 step 5): only then is it published."""
    if chat.state != ChatState.AWAITING_CONFIRMATION or not chat.draft_json or chat.draft_json.get("missing"):
        return False
    photos = sum(1 for item in media if str(item.get("content_type", "")).startswith("image/") and "key" in item)
    return said_yes(text, heard, photos)
