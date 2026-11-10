"""Messages OpenStall starts itself, outside a reply: sent where it reaches the seller and kept in her chat.

On WhatsApp the message is sent first and kept only if WhatsApp took it, with its WhatsApp id, so her chat shows
whether it reached her phone once WhatsApp says (chat/store.py, apply_delivery). In the web chat (her demo phone on
/seller-chat) keeping it is the delivery: the page shows it from the event stream.
"""

import logging
from collections.abc import Callable
from typing import Any

from openstall_api.chat.store import CHANNEL_WORDS, channel_for, find_chat, record_send, save_message
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.messaging import Messenger
from openstall_api.models import Channel, Direction, Seller

log = logging.getLogger(__name__)


def send_to_seller(
    seller_id: str,
    text: str,
    summary: str,
    messenger: Callable[[], Messenger],
    payload: dict[str, Any] | None = None,
) -> bool:
    """Send her `text` where OpenStall reaches her, keep it in her chat and record message.sent with `summary`, in
    which "{where}" becomes "on WhatsApp" or "in the web chat". Returns whether she got it. `messenger` is asked for
    only when the message goes out on WhatsApp."""
    with new_session() as session:
        seller = session.get(Seller, seller_id)
        if seller is None:
            return False
        channel, number = channel_for(seller), seller.whatsapp_number
    provider_id = None
    if channel == Channel.WHATSAPP:
        try:
            provider_id = messenger().send(f"whatsapp:{number}", text).message_id
        except Exception as error:  # WhatsApp refused it or Twilio is not set up: she did not get it
            log.warning("A message to seller %s could not be sent on WhatsApp: %s", seller_id, type(error).__name__)
            return False
    with session_scope() as session:
        seller = session.get(Seller, seller_id)
        assert seller is not None
        message = save_message(session, find_chat(session, seller, channel), Direction.OUTBOUND, text, [])
        if channel == Channel.WHATSAPP:  # what became of it on her phone, as WhatsApp tells it later
            record_send(session, message, provider_id)
        record_event(
            session,
            EventType.MESSAGE_SENT,
            summary.replace("{where}", CHANNEL_WORDS[channel]),
            entity_id=seller_id,
            payload={"channel": channel, "message_id": message.id, "provider_message_id": provider_id, **(payload or {})},
        )
    return True
