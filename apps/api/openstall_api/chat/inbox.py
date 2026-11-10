"""Everything that happens when a seller writes, whichever way she writes: WhatsApp, the web chat, or fake mode
playing a seeded maker. One path, so every channel behaves the same.

1. Her photo is looked at first, outside any transaction (the vision model may take seconds), if she has a share
   waiting for proof of shipping (handler.look_at_photos); her voice notes are turned into text, also outside it,
   with the language she is known to speak as a hint (handler.listen_to_voice_notes, voice.language_hint); and a
   seller drafting her listing has it read from her whole chat (handler.read_listing_from, chat/listing.py).
2. Her message, what her voice notes said, her listing draft and the replies are stored in one transaction
   (handler.handle_inbound), and committed; her yes publishes her listing in it (chat/publish.py), and the
   cached catalog is forgotten after the commit.
3. If her message held a voice note, each reply is spoken too, outside any transaction (chat/spoken.py). On WhatsApp
   the replies are sent through the Messenger, each spoken one after them as a voice note at its public address,
   and each send is kept with WhatsApp's id for what becomes of it (send_replies); the web chat shows them from the
   answer.
4. Any share she proved she shipped is captured and paid (proof.pay_on_proof), now or as a background task.
5. Any share she dropped out of is released and her units re-planned as a top-up order (healing.heal_after),
   and any advance she accepted is paid out (advance.pay_advance_after), now or as a background task.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from openstall_api.adapters import AdapterRegistry, AdapterUnavailable, get_registry
from openstall_api.catalog import public_url
from openstall_api.chat.handler import (
    HandledMessage,
    InboundFile,
    Refused,
    Sender,
    handle_inbound,
    listen_to_voice_notes,
    look_at_photos,
    read_listing_from,
)
from openstall_api.chat.spoken import Spoken, speak_replies
from openstall_api.chat.store import TEXT, VOICE_NOTE, record_send, record_undelivered
from openstall_api.chat.voice import language_hint, written_language
from openstall_api.db import session_scope
from openstall_api.feeds import clear_catalog_cache
from openstall_api.media import get_media_store
from openstall_api.models import Channel, ChatMessage
from openstall_api.whatsapp import MessengerError
from openstall_api.wording import buttons_of
from openstall_api.advance import pay_advance_after
from openstall_api.healing import heal_after
from openstall_api.proof import pay_on_proof

log = logging.getLogger(__name__)

# How the caller runs follow-up work: FastAPI's BackgroundTasks.add_task, so the answer is not held up by PayPal.
Later = Callable[..., Any]


def receive(
    sender: Sender, text: str, files: Sequence[InboundFile | Refused], later: Later | None = None
) -> HandledMessage:
    """Handle one message from a seller, end to end. Without `later`, payments run before this returns."""
    registry = get_registry()
    store = get_media_store()
    photo = look_at_photos(sender, files, lambda: registry.llm)
    hint = None
    if any_voice_note(files):
        hint = language_hint(sender.channel, sender.address, sender.seller_id) or written_language(text)
    heard = listen_to_voice_notes(files, lambda: registry.speech_to_text, hint)
    reading = read_listing_from(sender, text, files, heard, store, lambda: registry.llm)
    with session_scope() as session:
        handled = handle_inbound(session, store, sender, text, files, photo, heard, reading)
    if handled.published:
        clear_catalog_cache()  # /catalog.json lists her new listing at once
    spoken = (
        speak_replies(handled, heard, store, lambda: registry.text_to_speech)
        if registry.settings.SPOKEN_REPLIES
        else []
    )
    if sender.channel == Channel.WHATSAPP:
        send_replies(handled, spoken, sender.address, registry)
    for part_id in handled.pay_after:
        args = (part_id, lambda: registry.payment_gateway, lambda: registry.messenger)
        if later is not None:
            later(pay_on_proof, *args)
        else:
            pay_on_proof(*args)
    for part_id in handled.advance_after:
        paying = (part_id, lambda: registry.payment_gateway, lambda: registry.messenger)
        if later is not None:
            later(pay_advance_after, *paying)
        else:
            pay_advance_after(*paying)
    for part_id in handled.heal_after:
        heal = (part_id, lambda: registry.payment_gateway, lambda: registry.llm)
        if later is not None:
            later(heal_after, *heal)
        else:
            heal_after(*heal)
    return handled


def send_replies(handled: HandledMessage, spoken: Sequence[Spoken], address: str, registry: AdapterRegistry) -> None:
    """Her replies on WhatsApp: each text, then each spoken answer as a voice note at its public address. Each send is
    kept on its message with WhatsApp's id, so her chat shows what became of it once WhatsApp says; one refused at
    once is kept as failed, with why, and the rest still go."""
    outgoing: list[tuple[str, str, list[str], str]] = [
        (message_id, reply.text, [], TEXT)
        for message_id, reply in zip(handled.reply_ids, handled.replies, strict=True)
    ] + [(item.message_id, "", [public_url(registry.settings, item.audio.url)], VOICE_NOTE) for item in spoken]
    sends: list[tuple[str, str | None, str, str | None]] = []
    for message_id, text, media, part in outgoing:
        try:
            # A reply that offers buttons (wording.Said) has them under its text, where the provider can show them.
            sent = registry.messenger.send(f"whatsapp:{address}", text, media, buttons_of(text))
            sends.append((message_id, sent.message_id, part, None))
        except (MessengerError, AdapterUnavailable) as error:  # WhatsApp refused it, or is not set up here
            log.warning("A WhatsApp reply to seller %s could not be sent: %s", handled.seller_id, error)
            sends.append((message_id, None, part, str(error)))
        except Exception as error:  # a bug, not WhatsApp: logged in full
            log.exception("A WhatsApp reply to seller %s could not be sent", handled.seller_id)
            sends.append((message_id, None, part, f"It could not be sent ({type(error).__name__})."))
    if not sends:
        return
    with session_scope() as session:
        reported: set[str] = set()
        for message_id, provider_id, part, refused in sends:
            message = session.get(ChatMessage, message_id)
            if message is None:
                continue
            send = record_send(session, message, provider_id, part, refused)
            if send.error is not None and message.id not in reported:  # once per message, for the feed and her chat
                reported.add(message.id)
                record_undelivered(session, message, send.error, provider_message_id=None)


def any_voice_note(files: Sequence[InboundFile | Refused]) -> bool:
    """Whether she sent a voice note to hear: only then is her language looked up as a hint."""
    return any(isinstance(item, InboundFile) and item.content_type.startswith("audio/") for item in files)
