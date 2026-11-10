"""Telling each maker about her share (spec 3.6, "After payment"), once PayPal holds the order.

Each maker whose share is reserved gets one message, in her language: the order, the item, how many, her price and
her share, the date to ship by, where it goes, and how she is paid. Code writes it from a template in her language,
never a model: it carries the numbers she will act on. The demo's languages (English, Urdu, Hindi and Spanish) have
templates; any other language gets English, and the event says so. The message promises payment on her courier
receipt only when a payout rail can reach her; otherwise it asks her to wait for us before she ships.

She is told where she chats with OpenStall: on WhatsApp when we have her number, through the Messenger, and otherwise
in the web chat on /seller-chat, her demo phone (the seeded makers have no phone, so theirs is there). Either way the
message is kept in her chat, and message.order_notice says so in the feed.

Each share is told once. It is claimed first, by setting its notified_at where that is still empty, so two requests
cannot both send it. If WhatsApp refuses the message, the claim is given back and message.order_notice_failed says
why, so the next try (reserving the order again, as the receipt page does when it is opened) sends it. A claim left
by a process that stopped mid-send is taken over after STALE_CLAIM: she may then get the message twice, which is
better than not at all.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session, selectinload

from openstall_api.chat.store import CHANNEL_WORDS, channel_for, find_chat, save_message
from openstall_api.db import session_scope
from openstall_api.events import EventType, record_event
from openstall_api.messaging import Messenger
from openstall_api.models import Channel, Direction, Event, Order, OrderPart, PartStatus, utcnow
from openstall_api.payments import RESERVED, seller_rail
from openstall_api.wording import LOCALES, format_day, format_money, say, template_language
from openstall_api.wording import language_words as words_for_language

log = logging.getLogger(__name__)

STALE_CLAIM = timedelta(minutes=2)  # a claim older than this, with no message sent, was left by a stopped process
NOTICE_EVENTS = (EventType.ORDER_NOTICE_SENT.value, EventType.ORDER_NOTICE_FAILED.value)


@dataclass(frozen=True)
class NoticeFacts:
    """Everything one maker's message says, worked out from the order's own rows."""

    maker: str
    order_id: str
    item: str | None  # her listing's title; None if the listing was deleted since
    quantity: int
    unit_price: Decimal
    amount: Decimal
    ship_by: date | None  # her delivery date less her listing's ship days: when it must leave her hands
    deliver_by: date | None
    ship_to: str | None  # where the buyer asked for it, as they gave it
    paid_on_proof: bool  # a payout rail can reach her, so she is paid when she sends her courier receipt


@dataclass(frozen=True)
class Phrases:
    """One language's wording. Each line takes its facts by name; dates and money are written as the language writes
    them (wording.py)."""

    greeting: str  # {maker}
    order: str  # {order_id}
    item: str  # {item}
    quantity: str  # {quantity}
    price: str  # {unit}, {amount}
    ship_by: str  # {date}
    deliver: str  # {place}, {date}
    deliver_to: str  # {place}, when the delivery date is not known
    deliver_by: str  # {date}, when the place is not known
    paid: str  # {amount}
    wait: str  # {amount}, when no payout rail can reach her yet
    some_items: str  # the item, when her listing is gone


PHRASES: dict[str, Phrases] = {
    "en": Phrases(
        greeting="Hello {maker}! You have a new order from OpenStall.",
        order="Order: {order_id}",
        item="Item: {item}",
        quantity="Quantity: {quantity}",
        price="Price: {unit} each, {amount} in all",
        ship_by="Ship by: {date}",
        deliver="Deliver to: {place}, by {date}",
        deliver_to="Deliver to: {place}",
        deliver_by="Deliver by: {date}",
        paid="PayPal is holding your {amount}. When you ship, send a photo of the courier receipt here, and you will "
        "be paid then.",
        wait="PayPal is holding your {amount}, but payouts to your country are not connected yet. Please wait for "
        "our message before you ship.",
        some_items="the items you offered",
    ),
    "ur": Phrases(
        greeting="السلام علیکم {maker}! OpenStall سے آپ کے لیے ایک نیا آرڈر آیا ہے۔",
        order="آرڈر: {order_id}",
        item="سامان: {item}",
        quantity="تعداد: {quantity}",
        price="قیمت: {unit} فی عدد، کل {amount}",
        ship_by="بھیجنے کی آخری تاریخ: {date}",
        deliver="پہنچانا ہے: {place}، {date} تک",
        deliver_to="پہنچانا ہے: {place}",
        deliver_by="پہنچانے کی آخری تاریخ: {date}",
        paid="PayPal نے آپ کے {amount} محفوظ کر لیے ہیں۔ سامان بھیجتے وقت کورئیر کی رسید کی تصویر یہاں بھیجیں، اسی "
        "وقت آپ کو ادائیگی ہو جائے گی۔",
        wait="PayPal نے آپ کے {amount} محفوظ کر لیے ہیں، لیکن آپ کے ملک میں ادائیگی کا انتظام ابھی مکمل نہیں ہوا۔ "
        "سامان بھیجنے سے پہلے ہمارے پیغام کا انتظار کریں۔",
        some_items="وہ سامان جس کی آپ نے پیشکش کی تھی",
    ),
    "hi": Phrases(
        greeting="नमस्ते {maker}! OpenStall से आपके लिए एक नया ऑर्डर आया है।",
        order="ऑर्डर: {order_id}",
        item="सामान: {item}",
        quantity="संख्या: {quantity}",
        price="कीमत: {unit} प्रति पीस, कुल {amount}",
        ship_by="भेजने की आख़िरी तारीख़: {date}",
        deliver="पहुँचाना है: {place}, {date} तक",
        deliver_to="पहुँचाना है: {place}",
        deliver_by="पहुँचाने की आख़िरी तारीख़: {date}",
        paid="PayPal ने आपके {amount} सुरक्षित रख लिए हैं। सामान भेजते समय कूरियर की रसीद की फ़ोटो यहाँ भेजें, उसी "
        "समय आपको भुगतान हो जाएगा।",
        wait="PayPal ने आपके {amount} सुरक्षित रख लिए हैं, लेकिन आपके देश में भुगतान की व्यवस्था अभी पूरी नहीं हुई है। "
        "सामान भेजने से पहले हमारे संदेश का इंतज़ार करें।",
        some_items="वह सामान जिसकी आपने पेशकश की थी",
    ),
    "es": Phrases(
        greeting="¡Hola, {maker}! Tienes un pedido nuevo de OpenStall.",
        order="Pedido: {order_id}",
        item="Artículo: {item}",
        quantity="Cantidad: {quantity}",
        price="Precio: {unit} cada uno, {amount} en total",
        ship_by="Fecha límite de envío: {date}",
        deliver="Entregar en: {place}, a más tardar el {date}",
        deliver_to="Entregar en: {place}",
        deliver_by="Fecha límite de entrega: {date}",
        paid="PayPal tiene reservados tus {amount}. Cuando lo envíes, manda aquí una foto del recibo de la paquetería "
        "y se te pagará en ese momento.",
        wait="PayPal tiene reservados tus {amount}, pero los pagos a tu país todavía no están conectados. Espera "
        "nuestro mensaje antes de enviar.",
        some_items="los artículos que ofreciste",
    ),
}
assert PHRASES.keys() == LOCALES.keys(), "every template language writes its own dates and money (wording.py)"


@dataclass(frozen=True)
class Notice:
    text: str
    language: str  # the template used
    requested: str | None  # her language, which may have no template yet


def compose_notice(facts: NoticeFacts, language: str | None) -> Notice:
    """Her message, in her language, with its English line (wording.say). Every number comes from `facts`; nothing is
    translated at run time."""
    code = template_language(language)
    return Notice(say(code, lambda used: _notice_text(facts, used)), code, language)


def _notice_text(facts: NoticeFacts, code: str) -> str:
    words = PHRASES[code]

    def money(value: Decimal) -> str:
        return format_money(code, value)

    def day(value: date) -> str:
        return format_day(code, value)

    lines = [
        words.greeting.format(maker=facts.maker),
        "",
        words.order.format(order_id=facts.order_id),
        words.item.format(item=facts.item or words.some_items),
        words.quantity.format(quantity=facts.quantity),
        words.price.format(unit=money(facts.unit_price), amount=money(facts.amount)),
    ]
    if facts.ship_by:
        lines.append(words.ship_by.format(date=day(facts.ship_by)))
    if facts.ship_to and facts.deliver_by:
        lines.append(words.deliver.format(place=facts.ship_to, date=day(facts.deliver_by)))
    elif facts.ship_to:
        lines.append(words.deliver_to.format(place=facts.ship_to))
    elif facts.deliver_by:
        lines.append(words.deliver_by.format(date=day(facts.deliver_by)))
    lines += ["", (words.paid if facts.paid_on_proof else words.wait).format(amount=money(facts.amount))]
    return "\n".join(lines)


def ship_by(part: OrderPart) -> date | None:
    """When her share must leave her hands to arrive by its delivery date: the date less her listing's ship days, as
    the offer rules count it (capacity_available). Without a listing, the delivery date itself."""
    if part.delivery_date is None:
        return None
    ship_days = part.product.ship_days if part.product else 0
    return part.delivery_date - timedelta(days=ship_days)


def facts_of(part: OrderPart) -> NoticeFacts:
    order = part.order
    request = order.request
    return NoticeFacts(
        maker=part.seller.name,
        order_id=order.id,
        item=part.product.title if part.product else None,
        quantity=part.quantity,
        unit_price=part.unit_price_usd,
        amount=part.amount_usd,
        ship_by=ship_by(part),
        deliver_by=part.delivery_date,
        ship_to=request.ship_to if request else order.ship_to,
        paid_on_proof=seller_rail(part.seller).available,
    )


def channel_of(part: OrderPart) -> Channel:
    """WhatsApp when we have her number; otherwise the web chat, her demo phone on /seller-chat."""
    return channel_for(part.seller)


def language_words(notice: Notice) -> str:
    """The language she was told in, for the feed: "Urdu", or "English (no template for 'bn' yet)"."""
    return words_for_language(notice.language, notice.requested)


def _day(value: date) -> str:
    return f"{value:%B} {value.day}"


def _load(session: Session, part_id: str) -> OrderPart | None:
    return session.get(
        OrderPart,
        part_id,
        options=[
            selectinload(OrderPart.seller),
            selectinload(OrderPart.product),
            selectinload(OrderPart.order).selectinload(Order.request),
        ],
        populate_existing=True,
    )


def _claim(session: Session, part_id: str, now: datetime) -> bool:
    """Take the share's notice: its notified_at, if still empty or left stale. Only one claimant can succeed."""
    told = session.scalar(
        select(Event.id).where(Event.type == EventType.ORDER_NOTICE_SENT.value, Event.entity_id == part_id).limit(1)
    )
    if told is not None:
        return False
    result = cast(
        CursorResult[Any],
        session.execute(
            update(OrderPart)
            .where(
                OrderPart.id == part_id,
                OrderPart.status == PartStatus.AUTHORIZED,
                or_(OrderPart.notified_at.is_(None), OrderPart.notified_at < now - STALE_CLAIM),
            )
            .values(notified_at=now)
            .execution_options(synchronize_session=False)
        ),
    )
    return result.rowcount == 1


def _record_sent(session: Session, part: OrderPart, notice: Notice, channel: Channel, provider_id: str | None) -> None:
    chat = find_chat(session, part.seller, channel)
    message = save_message(session, chat, Direction.OUTBOUND, notice.text, [])
    part.notified_at = utcnow()
    when = ship_by(part)
    record_event(
        session,
        EventType.ORDER_NOTICE_SENT,
        f"{part.seller.name} was told about her share {CHANNEL_WORDS[channel]}, in {language_words(notice)}: "
        f"{part.quantity} to ship" + (f" by {_day(when)}" if when else ""),
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "seller_id": part.seller_id,
            "channel": channel,
            "language": notice.language,
            "requested_language": notice.requested,
            "message_id": message.id,
            "provider_message_id": provider_id,
        },
    )


def tell_maker(part_id: str, messenger: Callable[[], Messenger]) -> bool:
    """Tell one maker about her reserved share, unless she was told already or another request is telling her.
    Returns whether she was told now. `messenger` is asked for only when the message goes out on WhatsApp."""
    now = utcnow()
    with session_scope() as session:
        if not _claim(session, part_id, now):
            return False
        part = _load(session, part_id)
        assert part is not None  # the claim found it
        notice = compose_notice(facts_of(part), part.seller.language)
        channel = channel_of(part)
        to = part.seller.whatsapp_number
        if channel == Channel.WEB:  # nothing leaves OpenStall: her demo phone shows the stored message
            _record_sent(session, part, notice, channel, None)
            return True
    assert to is not None
    try:
        sent = messenger().send(f"whatsapp:{to}", notice.text)
    except Exception as error:  # anything WhatsApp says, or Twilio not set up: give the claim back and say why
        reason = _reason(error)
        log.warning("The order notice for share %s could not be sent: %s", part_id, reason)
        with session_scope() as session:
            session.execute(
                update(OrderPart)
                .where(OrderPart.id == part_id, OrderPart.notified_at == now)
                .values(notified_at=None)
                .execution_options(synchronize_session=False)
            )
            part = _load(session, part_id)
            assert part is not None
            record_event(
                session,
                EventType.ORDER_NOTICE_FAILED,
                f"{part.seller.name} could not be told about her share on WhatsApp: {reason}",
                entity_id=part.id,
                payload={
                    "order_id": part.order_id,
                    "seller_id": part.seller_id,
                    "channel": Channel.WHATSAPP,
                    "reason": reason,
                },
            )
        return False
    with session_scope() as session:
        part = _load(session, part_id)
        assert part is not None
        _record_sent(session, part, notice, Channel.WHATSAPP, sent.message_id)
    return True


# A phone number, as Twilio may quote one in an error ("The 'To' number +92300... is not valid"): 7 to 15 digits.
PHONE_NUMBER = re.compile(r"(?:whatsapp:)?\+?\d[\d\s-]{5,17}\d")


def _reason(error: Exception) -> str:
    """Why a message did not go out, in words. It is shown on the public /demo feed and the receipt, so any phone
    number in it (Twilio quotes the recipient's in some errors) is taken out; our own errors hold no secrets."""
    text = PHONE_NUMBER.sub("her number", str(error)).strip().rstrip(".")
    return text[:200] if text else type(error).__name__


def notify_order(order_id: str, messenger: Callable[[], Messenger]) -> list[str]:
    """Tell every maker whose share of the order is reserved and who has not been told. Safe to call again: each
    share is told once. Returns the ids of the shares told now. Called after the reservation is committed."""
    with session_scope() as session:
        order = session.get(Order, order_id, options=[selectinload(Order.parts)])
        if order is None or order.status not in RESERVED:
            return []
        waiting = [part.id for part in order.parts if part.status == PartStatus.AUTHORIZED]
    told = []
    for part_id in waiting:
        try:
            if tell_maker(part_id, messenger):
                told.append(part_id)
        except Exception:  # one maker's trouble must not keep the others from hearing
            log.exception("The order notice for share %s could not be handled", part_id)
    return told


NoticeStep = Literal["sent", "sending", "failed"]
ChannelName = Literal["whatsapp", "web"]


@dataclass(frozen=True)
class NoticeState:
    """Whether a maker was told about her share, for the receipt and get_order_status."""

    # sent; sending (claimed, on its way to WhatsApp); failed (WhatsApp refused it; tried again when the order is
    # reserved again)
    state: NoticeStep
    channel: ChannelName | None
    language: str | None
    at: datetime
    reason: str | None = None


def _channel(value: Any) -> ChannelName | None:
    if value == "whatsapp":
        return "whatsapp"
    if value == "web":
        return "web"
    return None


def notice_states(session: Session, parts: list[OrderPart]) -> dict[str, NoticeState]:
    """Each share's latest notice, by share id: sent, failed, or being sent (claimed with nothing recorded yet).
    A share with none is not in the result."""
    ids = [part.id for part in parts]
    latest: dict[str, Event] = {}
    if ids:
        for row in session.scalars(
            select(Event).where(Event.type.in_(NOTICE_EVENTS), Event.entity_id.in_(ids)).order_by(Event.id)
        ):
            if row.entity_id is not None and (
                row.entity_id not in latest or latest[row.entity_id].type != EventType.ORDER_NOTICE_SENT.value
            ):
                latest[row.entity_id] = row  # a sent notice stays sent; otherwise the newest wins
    states = {}
    for part in parts:
        event = latest.get(part.id)
        if event is not None and event.type == EventType.ORDER_NOTICE_SENT.value:
            payload = event.payload_json
            states[part.id] = NoticeState(
                "sent", _channel(payload.get("channel")), payload.get("language"), event.created_at
            )
        elif part.notified_at is not None:
            states[part.id] = NoticeState("sending", None, None, part.notified_at)
        elif event is not None:
            payload = event.payload_json
            states[part.id] = NoticeState(
                "failed", _channel(payload.get("channel")), None, event.created_at, reason=payload.get("reason")
            )
    return states
