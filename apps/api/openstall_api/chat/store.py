"""Where sellers' chats are kept: each seller's chat per channel, its messages, and which channel reaches her.

The chat handler (handler.py), the order notices (notices.py) and pay-on-proof (proof.py) all keep messages here, so
a seller's chat shows everything she sent and was sent, whichever part of OpenStall wrote it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.models import Channel, ChatMessage, ChatSession, ChatState, Direction, Seller, utcnow

CHANNEL_WORDS = {Channel.WHATSAPP: "on WhatsApp", Channel.WEB: "in the web chat"}
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
    """One message in her chat, inbound or outbound. The caller commits."""
    message = ChatMessage(
        session_id=chat.id, direction=direction, channel=chat.channel, text=text or None, media_json=media
    )
    session.add(message)
    chat.updated_at = utcnow()
    session.flush()
    return message
