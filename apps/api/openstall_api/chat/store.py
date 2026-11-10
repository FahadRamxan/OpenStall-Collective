"""Where sellers' chats are kept: each seller's chat per channel, its messages, and which channel reaches her.

The chat handler (handler.py), the order notices (notices.py) and pay-on-proof (proof.py) all keep messages here, so
a seller's chat shows everything she sent and was sent, whichever part of OpenStall wrote it.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.events import EventType, record_event
from openstall_api.models import (
    Channel,
    ChatMessage,
    ChatSession,
    ChatState,
    Delivery,
    Direction,
    Seller,
    WhatsAppSend,
    utcnow,
)
from openstall_api.wording import buttons_of, english_of

CHANNEL_WORDS = {Channel.WHATSAPP: "on WhatsApp", Channel.WEB: "in the web chat"}
# The parts a message of ours goes out as on WhatsApp: its text, then its spoken voice note (chat/spoken.py).
TEXT, VOICE_NOTE = "text", "voice note"
# How far a message of ours has got on WhatsApp. A later status never moves it back: Meta's can arrive out of order.
PROGRESS = {Delivery.SENT: 1, Delivery.DELIVERED: 2, Delivery.READ: 3}
# A phone number, as a provider may quote one in an error ("The 'To' number +92300... is not valid"): 7 to 15 digits.
PHONE_NUMBER = re.compile(r"(?:whatsapp:)?\+?\d[\d\s-]{5,17}\d")
# The countries in the demo, by dialing code. Other numbers leave the country empty until the seller says.
DIALING_CODES = {"92": "PK", "91": "IN", "52": "MX", "44": "GB", "1": "US"}


def country_of(number: str) -> str | None:
    """Her country from her WhatsApp number, by its dialing code: "+923001234567" is PK."""
    digits = number.lstrip("+")
    for code in sorted(DIALING_CODES, key=len, reverse=True):
        if digits.startswith(code):
            return DIALING_CODES[code]
    return None


def channel_for(seller: Seller) -> Channel:
    """Where OpenStall reaches her on its own: WhatsApp when we have her number; otherwise the web chat, her demo
    phone on /seller-chat (the seeded makers have no phone, so theirs is there)."""
    return Channel.WHATSAPP if seller.whatsapp_number else Channel.WEB


def known_seller(session: Session, channel: Channel, address: str, seller_id: str | None = None) -> Seller | None:
    """The seller behind a sender, if she has written before: by id when one is given (fake mode playing a seeded
    maker), else by her WhatsApp number or her web chat's demo phone id. Never makes one."""
    if seller_id is not None:
        return session.get(Seller, seller_id)
    if channel == Channel.WHATSAPP:
        return session.scalar(select(Seller).where(Seller.whatsapp_number == address))
    return session.scalar(select(Seller).where(Seller.web_chat_id == address))


def find_chat(session: Session, seller: Seller, channel: Channel) -> ChatSession:
    """Her chat on this channel, made on first use."""
    chat = session.scalar(select(ChatSession).where(ChatSession.seller_id == seller.id, ChatSession.channel == channel))
    if chat is None:
        chat = ChatSession(seller_id=seller.id, channel=channel, state=ChatState.COLLECTING)
        session.add(chat)
        session.flush()
    return chat


def save_message(
    session: Session, chat: ChatSession, direction: Direction, text: str, media: list[dict[str, object]]
) -> ChatMessage:
    """One message in her chat, inbound or outbound. The caller commits. A message composed with wording.say keeps
    its English line and the buttons it offers her."""
    message = ChatMessage(
        session_id=chat.id,
        direction=direction,
        channel=chat.channel,
        text=text or None,
        media_json=media,
        english=english_of(text),
        buttons_json=list(buttons_of(text)) or None,
    )
    session.add(message)
    chat.updated_at = utcnow()
    session.flush()
    return message


def public_reason(text: str) -> str:
    """A provider's reason, fit for the public pages and feed: any phone number in it taken out."""
    return PHONE_NUMBER.sub("her number", text).strip()[:300] or "no reason given"


def record_send(
    session: Session, message: ChatMessage, provider_id: str | None, part: str = TEXT, error: str | None = None
) -> WhatsAppSend:
    """One WhatsApp message of ours as handed to the provider: taken, with its id, or refused at once and why. The
    caller commits."""
    send = WhatsAppSend(
        message_id=message.id,
        provider_id=provider_id or None,
        part=part,
        status=Delivery.SENT if error is None else Delivery.FAILED,
        error=None if error is None else public_reason(error),
    )
    session.add(send)
    return send


def record_undelivered(
    session: Session,
    message: ChatMessage | None,
    reason: str,
    *,
    provider_message_id: str | None,
    seller: Seller | None = None,
) -> None:
    """A message of ours WhatsApp could not deliver, for the live feed (which makes her chat on the pages look again),
    with the provider's reason, numbers taken out. `seller` when the message is not known. The caller commits."""
    if seller is None and message is not None:
        seller = message.session.seller
    record_event(
        session,
        EventType.MESSAGE_UNDELIVERED,
        f"WhatsApp could not deliver a message to {seller.name if seller else 'a seller'}: {public_reason(reason)}",
        entity_id=seller.id if seller else None,
        payload={
            "message_id": message.id if message is not None else None,
            "provider_message_id": provider_message_id,
            "reason": public_reason(reason),
        },
    )


def apply_delivery(session: Session, provider_id: str, status: str, error: str | None = None) -> WhatsAppSend | None:
    """What the provider says became of one of our WhatsApp messages. Delivered and read only move it forward; failed
    is final, with the provider's reasons. Returns the send it changed; None for an id that is not ours (or from
    before sends were kept), a status OpenStall does not keep, or nothing new. The caller commits."""
    try:
        new = Delivery(status)
    except ValueError:
        return None
    send = session.scalar(
        select(WhatsAppSend)
        .where(WhatsAppSend.provider_id == provider_id)
        .order_by(WhatsAppSend.created_at.desc())
        .limit(1)
    )
    if send is None or send.status == Delivery.FAILED:
        return None
    if new == Delivery.FAILED:
        send.status, send.error = new, public_reason(error or "")
    elif PROGRESS[new] > PROGRESS[send.status]:
        send.status = new
    else:
        return None
    return send


def delivery_of(message: ChatMessage) -> tuple[Delivery | None, str | None]:
    """What became of a message of ours on WhatsApp, all its parts together, for the pages: failed if any part failed,
    with a sentence saying why; else as far as its slowest part has got. (None, None) when it went out as no WhatsApp
    message: her own messages, the web chat's, and ours from before sends were kept."""
    sends = message.sends
    if not sends:
        return None, None
    failed = [send for send in sends if send.status == Delivery.FAILED]
    if not failed:
        return min((send.status for send in sends), key=lambda status: PROGRESS[status]), None
    if all(send.part == VOICE_NOTE for send in failed) and len(failed) < len(sends):
        what = "its spoken voice note"
    else:
        what = "it"
    reasons = "; ".join(dict.fromkeys(send.error or "no reason given" for send in failed))
    return Delivery.FAILED, f"WhatsApp could not deliver {what}: {reasons}"
