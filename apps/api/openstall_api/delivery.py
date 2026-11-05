"""Delivery and the end of an order (prompt 34): each maker's parcel confirmed delivered, and the order completed once
every parcel is in.

PayPal's order trackers only say a parcel was shipped (its SDK: "the latest status of the parcel must be retrieved
from the carrier"), and OpenStall has no courier feed, so delivery is confirmed by the buyer, who receives the parcels:
on the order's receipt page, share by share (POST /api/orders/{order_id}/parts/{part_id}/delivered).

Confirming moves her share from captured to delivered and records when it arrived (`delivered_at`), and whether that
was by the date the order promised (`on_time`: on or before the share's `delivery_date`, in UTC), which her trust
passport will count (prompt 36). No money moves: she was paid when she proved she shipped. She is told, in her
language, once, after the commit. The order is completed once no share waits and every paid share is delivered
(payments.settle_order), however the last share settles: delivered, or released.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from openstall_api.chat.outbox import send_to_seller
from openstall_api.db import new_session
from openstall_api.events import EventType, record_event
from openstall_api.messaging import Messenger
from openstall_api.models import OrderPart, PartStatus, utcnow
from openstall_api.orders import move_part
from openstall_api.payments import WrongStatus, load_part, settle_order
from openstall_api.wording import LOCALES, format_day, language_words, template_language

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveredPhrases:
    """One language's words for telling a maker her parcel arrived."""

    arrived: str  # {maker}, {order_id}, {date}
    on_time: str  # added when it arrived by its delivery date


DELIVERED: dict[str, DeliveredPhrases] = {
    "en": DeliveredPhrases(
        arrived="Good news, {maker}! The buyer received your parcel for order {order_id} on {date}{on_time}. "
        "Thank you!",
        on_time=", on time",
    ),
    "ur": DeliveredPhrases(
        arrived="خوشخبری، {maker}! خریدار کو آرڈر {order_id} کا آپ کا پارسل {date} کو مل گیا{on_time}۔ شکریہ!",
        on_time="، وقت پر",
    ),
    "hi": DeliveredPhrases(
        arrived="खुशखबरी, {maker}! खरीदार को ऑर्डर {order_id} का आपका पार्सल {date} को मिल गया{on_time}। धन्यवाद!",
        on_time=", समय पर",
    ),
    "es": DeliveredPhrases(
        arrived="¡Buenas noticias, {maker}! El comprador recibió tu paquete del pedido {order_id} el {date}{on_time}. "
        "¡Gracias!",
        on_time=", a tiempo",
    ),
}
assert DELIVERED.keys() == LOCALES.keys(), "every template language tells her the parcel arrived"


def delivered_utc(part: OrderPart) -> datetime | None:
    """When her parcel arrived, in UTC: SQLite gives back the stored UTC time with no zone, and Postgres may give it
    in its own zone."""
    moment = part.delivered_at
    if moment is None:
        return None
    return moment.astimezone(UTC) if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def arrived_on(part: OrderPart) -> date | None:
    """The day her parcel arrived, in UTC, once it is delivered."""
    moment = delivered_utc(part)
    return moment.date() if moment is not None else None


def on_time(part: OrderPart) -> bool | None:
    """Whether her parcel arrived by the date the order promised. None until it arrived, or when no date was set."""
    day = arrived_on(part)
    if day is None or part.delivery_date is None:
        return None
    return day <= part.delivery_date


def _day(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def confirm_delivery(session: Session, part_id: str, now: datetime | None = None) -> bool:
    """The buyer confirms one maker's parcel arrived: her share moves to delivered, with when, and the order is
    completed if it was the last. True when this call delivered it; False when it already was. Raises WrongStatus for a
    share that has not shipped (she proves shipping before she is paid) or was released. The caller commits."""
    part = load_part(session, part_id)  # locks the order: two confirmations cannot both deliver it
    name = part.seller.name
    if part.status == PartStatus.DELIVERED:
        return False
    if part.status == PartStatus.RELEASED:
        raise WrongStatus(f"{name}'s share was released, so there is no parcel of hers to receive.")
    if part.status != PartStatus.CAPTURED:
        raise WrongStatus(f"{name} has not shipped her share yet: she is paid when she proves she shipped it.")
    delivered_at = now or utcnow()
    part.delivered_at = delivered_at
    move_part(part, PartStatus.DELIVERED)
    kept = on_time(part)
    day = arrived_on(part) or delivered_at.date()
    timing = ""
    if kept is not None and part.delivery_date is not None:
        timing = ", on time" if kept else f", late: it was due {_day(part.delivery_date)}"
    record_event(
        session,
        EventType.DELIVERY_CONFIRMED,
        f"The buyer received {name}'s parcel for order {part.order_id} on {_day(day)}{timing}",
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "seller_id": part.seller_id,
            "delivered_at": part.delivered_at,
            "delivery_date": part.delivery_date,
            "on_time": kept,
        },
    )
    settle_order(part.order)
    return True


def tell_maker_delivered(part_id: str, messenger: Callable[[], Messenger]) -> bool:
    """After the commit: tell her, in her language, that the buyer received her parcel. Returns whether she got it;
    a message that cannot be sent is logged, and her share stays delivered."""
    with new_session() as session:
        part = session.get(OrderPart, part_id)
        if part is None or part.status != PartStatus.DELIVERED or part.delivered_at is None:
            return False
        seller = part.seller
        language = template_language(seller.language)
        phrases = DELIVERED[language]
        text = phrases.arrived.format(
            maker=seller.name,
            order_id=part.order_id,
            date=format_day(language, arrived_on(part) or part.delivered_at.date()),
            on_time=phrases.on_time if on_time(part) else "",
        )
        seller_id, order_id, used = seller.id, part.order_id, language_words(language, seller.language)
        name = seller.name
    sent = send_to_seller(
        seller_id,
        text,
        f"OpenStall told {name} {{where}}, in {used}, that the buyer received her parcel for order {order_id}",
        messenger,
        payload={"order_id": order_id, "part_id": part_id, "language": language},
    )
    if not sent:
        log.warning("Seller %s could not be told that her parcel for %s arrived", seller_id, order_id)
    return sent
