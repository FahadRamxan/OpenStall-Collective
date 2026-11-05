"""Pay-on-proof from the chat (spec 3.6, "After shipping"): a maker photographs her courier receipt, the model reads
the courier and the tracking number, she confirms them, and her share is captured and paid.

1. Before her message is stored, look_at_photo asks the vision model about the photo she sent, but only if she has a
   share waiting for proof of shipping (reserved, no tracking yet): no model is asked about photos otherwise, and no
   transaction is open while it reads.
2. Inside the chat handler's transaction, proof_turn keeps the photo and what was read on her share (proof_json) and
   asks her, in her language, to confirm the number, or to type it if it could not be read. Her "yes" confirms it: the
   share's tracking number and courier are set, and tracking.confirmed is recorded. A number she types replaces what
   was read and is asked about once more; a "no" asks her for the right one.
3. After that commit, pay_on_proof captures her share and pays her out (payments.pay_share: once, and never without a
   way to pay her), puts her tracking on her capture at PayPal (tracking.py, prompt 33), then tells her in her
   language. A maker no payout rail reaches yet (Amina, until prompt 52) keeps
   her confirmed tracking, and is told she is paid once payouts reach her country.

Nothing is paid on what the model read alone: only her confirmation moves money.
"""

import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_agents.adapters import LLM, LLMError, Media
from openstall_agents.receipt_reader import ReceiptReading, clean_tracking, read_receipt
from openstall_api.adapters import AdapterUnavailable
from openstall_api.chat.outbox import send_to_seller
from openstall_api.chat.store import known_seller
from openstall_api.claims import ClaimHeld
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.messaging import Messenger
from openstall_api.models import Channel, Order, OrderPart, OrderStatus, PartStatus, Seller, utcnow
from openstall_api.notices import ship_by
from openstall_api.payments import PAID, OrderNotFound, WrongStatus, pay_share, seller_rail
from openstall_api.settings import get_settings
from openstall_api.tracking import track_on_paypal
from openstall_api.webhooks import deliver_fake_webhooks
from openstall_api.wording import LOCALES, format_money, language_words, template_language
from openstall_paypal import RAIL_NAMES, PaymentError, PaymentGateway, PaymentUnavailable

log = logging.getLogger(__name__)

AWAITING_CONFIRMATION = "awaiting_confirmation"  # a number was read or typed; she has not confirmed it yet
AWAITING_NUMBER = "awaiting_number"  # her receipt photo is kept, but its number could not be read
CONFIRMED = "confirmed"  # she confirmed it: the share's tracking number is set
PENDING = (AWAITING_CONFIRMATION, AWAITING_NUMBER)


@dataclass(frozen=True)
class ProofPhrases:
    """One language's words for the receipt flow. Dates and money are written by wording.py."""

    ask_confirm: str  # {order_id}, {quantity}, {item}, {carrier}, {tracking}
    no_carrier: str  # in place of the courier, when none is printed
    some_items: str  # in place of the item, when her listing is gone
    ask_number: str  # {order_id}
    ask_again: str
    confirmed_paying: str  # {tracking}, {amount}
    confirmed_waiting: str  # {tracking}, {amount}: no payout rail reaches her yet
    paid: str  # {amount}, {order_id}, {rail}
    simulated: str  # added to `paid` in test mode
    payment_failed: str
    retrying: str  # {order_id}


PHRASES: dict[str, ProofPhrases] = {
    "en": ProofPhrases(
        ask_confirm="Thank you! I read your courier receipt for order {order_id} ({quantity} × {item}):\n"
        "Courier: {carrier}\nTracking number: {tracking}\n\nIs that right? Reply YES, or type the right tracking "
        "number.",
        no_carrier="not printed",
        some_items="your items",
        ask_number="Thank you for the photo of your courier receipt for order {order_id}. I could not read the "
        "tracking number: please type it here, or send a clearer photo.",
        ask_again="Please type the right tracking number here, or send a clearer photo of the receipt.",
        confirmed_paying="Thank you! Your tracking number {tracking} is saved, and your {amount} is being paid now.",
        confirmed_waiting="Thank you! Your tracking number {tracking} is saved. Payouts to your country are not "
        "connected yet, so your {amount} stays reserved at PayPal; we will message you as soon as we can pay you.",
        paid="You are paid! {amount} for order {order_id} has been sent to your {rail} account.",
        simulated="(Test mode: simulated PayPal, no real money moved.)",
        payment_failed="Your tracking number is saved, but the payment did not go through yet. We will try again; "
        "reply YES here to try now.",
        retrying="Your tracking number for order {order_id} is already saved. Trying your payment again now.",
    ),
    "ur": ProofPhrases(
        ask_confirm="شکریہ! میں نے آرڈر {order_id} ({quantity} × {item}) کی کورئیر رسید پڑھ لی ہے:\n"
        "کورئیر: {carrier}\nٹریکنگ نمبر: {tracking}\n\nکیا یہ درست ہے؟ \"ہاں\" لکھیں، یا درست ٹریکنگ نمبر لکھ دیں۔",
        no_carrier="رسید پر درج نہیں",
        some_items="آپ کا سامان",
        ask_number="کورئیر رسید کی تصویر کا شکریہ (آرڈر {order_id})۔ میں ٹریکنگ نمبر نہیں پڑھ سکا: براہ کرم اسے یہاں "
        "لکھ دیں، یا زیادہ صاف تصویر بھیجیں۔",
        ask_again="براہ کرم درست ٹریکنگ نمبر یہاں لکھیں، یا رسید کی زیادہ صاف تصویر بھیجیں۔",
        confirmed_paying="شکریہ! آپ کا ٹریکنگ نمبر {tracking} محفوظ ہو گیا ہے، اور آپ کے {amount} ابھی ادا کیے جا رہے "
        "ہیں۔",
        confirmed_waiting="شکریہ! آپ کا ٹریکنگ نمبر {tracking} محفوظ ہو گیا ہے۔ آپ کے ملک میں ادائیگی کا انتظام ابھی "
        "مکمل نہیں ہوا، اس لیے آپ کے {amount} PayPal کے پاس محفوظ ہیں؛ ادائیگی ممکن ہوتے ہی ہم آپ کو پیغام بھیجیں گے۔",
        paid="آپ کو ادائیگی ہو گئی! آرڈر {order_id} کے {amount} آپ کے {rail} اکاؤنٹ میں بھیج دیے گئے ہیں۔",
        simulated="(ٹیسٹ موڈ: نقلی PayPal، کوئی اصل رقم منتقل نہیں ہوئی۔)",
        payment_failed="آپ کا ٹریکنگ نمبر محفوظ ہے، لیکن ادائیگی ابھی نہیں ہو سکی۔ ہم دوبارہ کوشش کریں گے؛ ابھی کوشش "
        "کے لیے یہاں \"ہاں\" لکھیں۔",
        retrying="آرڈر {order_id} کا آپ کا ٹریکنگ نمبر پہلے سے محفوظ ہے۔ ہم ابھی دوبارہ ادائیگی کی کوشش کر رہے ہیں۔",
    ),
    "hi": ProofPhrases(
        ask_confirm="धन्यवाद! मैंने ऑर्डर {order_id} ({quantity} × {item}) की कूरियर रसीद पढ़ ली है:\n"
        "कूरियर: {carrier}\nट्रैकिंग नंबर: {tracking}\n\nक्या यह सही है? \"हाँ\" लिखें, या सही ट्रैकिंग नंबर लिख दें।",
        no_carrier="रसीद पर नहीं लिखा",
        some_items="आपका सामान",
        ask_number="कूरियर रसीद की फ़ोटो के लिए धन्यवाद (ऑर्डर {order_id})। मैं ट्रैकिंग नंबर नहीं पढ़ पाया: कृपया उसे "
        "यहाँ लिख दें, या ज़्यादा साफ़ फ़ोटो भेजें।",
        ask_again="कृपया सही ट्रैकिंग नंबर यहाँ लिखें, या रसीद की ज़्यादा साफ़ फ़ोटो भेजें।",
        confirmed_paying="धन्यवाद! आपका ट्रैकिंग नंबर {tracking} सेव हो गया है, और आपके {amount} का भुगतान अभी किया "
        "जा रहा है।",
        confirmed_waiting="धन्यवाद! आपका ट्रैकिंग नंबर {tracking} सेव हो गया है। आपके देश में भुगतान की व्यवस्था अभी "
        "पूरी नहीं हुई है, इसलिए आपके {amount} PayPal के पास सुरक्षित हैं; भुगतान संभव होते ही हम आपको संदेश भेजेंगे।",
        paid="आपको भुगतान हो गया! ऑर्डर {order_id} के {amount} आपके {rail} खाते में भेज दिए गए हैं।",
        simulated="(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)",
        payment_failed="आपका ट्रैकिंग नंबर सेव है, लेकिन भुगतान अभी नहीं हो पाया। हम फिर से कोशिश करेंगे; अभी कोशिश "
        "करने के लिए यहाँ \"हाँ\" लिखें।",
        retrying="ऑर्डर {order_id} का आपका ट्रैकिंग नंबर पहले से सेव है। हम अभी फिर से भुगतान की कोशिश कर रहे हैं।",
    ),
    "es": ProofPhrases(
        ask_confirm="¡Gracias! Leí tu recibo de paquetería del pedido {order_id} ({quantity} × {item}):\n"
        "Paquetería: {carrier}\nNúmero de guía: {tracking}\n\n¿Es correcto? Responde SÍ, o escribe el número de guía "
        "correcto.",
        no_carrier="no aparece en el recibo",
        some_items="tus artículos",
        ask_number="Gracias por la foto de tu recibo de paquetería (pedido {order_id}). No pude leer el número de "
        "guía: escríbelo aquí, por favor, o manda una foto más clara.",
        ask_again="Por favor, escribe aquí el número de guía correcto, o manda una foto más clara del recibo.",
        confirmed_paying="¡Gracias! Tu número de guía {tracking} quedó guardado, y estamos pagando tus {amount} ahora.",
        confirmed_waiting="¡Gracias! Tu número de guía {tracking} quedó guardado. Los pagos a tu país todavía no "
        "están conectados, así que tus {amount} siguen reservados en PayPal; te escribiremos en cuanto podamos "
        "pagarte.",
        paid="¡Ya te pagamos! Los {amount} del pedido {order_id} se enviaron a tu cuenta de {rail}.",
        simulated="(Modo de prueba: PayPal simulado, no se movió dinero real.)",
        payment_failed="Tu número de guía está guardado, pero el pago todavía no se completó. Lo intentaremos de "
        "nuevo; responde SÍ aquí para intentarlo ahora.",
        retrying="Tu número de guía del pedido {order_id} ya está guardado. Estamos intentando tu pago de nuevo.",
    ),
}
assert PHRASES.keys() == LOCALES.keys(), "every template language has the receipt flow's words too"

# What counts as "yes" and "no" in the demo's languages, after normalise(): lower case, punctuation gone.
YES = frozenset(
    {
        "yes", "y", "yeah", "yep", "yup", "ok", "okay", "correct", "right", "sure", "confirm", "confirmed",
        "haan", "han", "ha", "haa", "ji", "jee", "ji haan", "haan ji", "theek", "theek hai", "thik hai", "sahi",
        "ہاں", "ہاں جی", "جی", "جی ہاں", "ٹھیک", "ٹھیک ہے", "درست", "صحیح",
        "हाँ", "हां", "हा", "जी", "जी हाँ", "जी हां", "हाँ जी", "हां जी", "ठीक", "ठीक है", "सही",
        "sí", "si", "claro", "correcto", "así es", "exacto", "vale", "de acuerdo",
    }
)  # fmt: skip
NO = frozenset(
    {
        "no", "n", "nope", "wrong", "incorrect", "not right",
        "nahi", "nahin", "nai", "na", "galat", "نہیں", "غلط", "नहीं", "नही", "ना", "गलत", "ग़लत",
        "incorrecto", "está mal", "esta mal", "no es correcto",
    }
)  # fmt: skip
THUMBS_UP = "👍"


@dataclass(frozen=True)
class PhotoReading:
    """What the model made of the photo she sent, before her message is stored."""

    part_id: str  # the share it would prove: her open share due to ship first
    photo_index: int  # which of the files in her message was read
    reading: ReceiptReading | None  # None when the model could not be asked or did not answer
    read_by: str  # who read it, in words for people
    error: str | None = None  # why there is no reading


@dataclass(frozen=True)
class ProofTurn:
    """The chat's answer to a message in the receipt flow, and the shares to pay once it is committed."""

    replies: list[str]
    pay_after: list[str] = field(default_factory=list)


def normalise(text: str) -> str:
    """Lower case, with only letters, marks, digits and single spaces left: "Yes!" and "  yes " are both "yes"."""
    kept = "".join(char if unicodedata.category(char)[0] in "LMN" else " " for char in text.lower())
    return " ".join(kept.split())


def is_yes(text: str) -> bool:
    words = normalise(text)
    if text.strip().startswith(THUMBS_UP) or words in YES:
        return True
    first = words.split(" ", 1)[0] if words else ""
    return first in YES and len(words.split()) <= 4 and not any(char.isdigit() for char in words)


def is_no(text: str) -> bool:
    words = normalise(text)
    return words in NO or (words.split(" ", 1)[0] in NO and not any(char.isdigit() for char in words))


def _number_like(chunk: str) -> bool:
    """A piece of a number typed with spaces: digits ("123456789"), or a short capital code ("EE", "IN")."""
    if any(char.isdigit() for char in chunk):
        return True
    return chunk.isalpha() and chunk.isupper() and len(chunk) <= 3 and chunk.lower() not in YES | NO


def typed_tracking(text: str) -> str | None:
    """A tracking number she typed: the whole message when every piece of it looks like part of one ("EE 123456789
    IN", "7712 3456 78"), else the first word of it that passes clean_tracking ("my number is 7712345678")."""
    chunks = text.strip(" .!?").split()
    if chunks and len(text) <= 48 and all(_number_like(chunk) for chunk in chunks):
        whole = clean_tracking("".join(chunks))
        if whole:
            return whole
    for word in re.split(r"[\s,;:]+", text):
        found = clean_tracking(word.strip(".!?()[]#\"'"))
        if found:
            return found
    return None


def awaiting_proof(session: Session, seller_id: str) -> list[OrderPart]:
    """Her shares waiting for proof of shipping: reserved, with no tracking yet, on an order PayPal holds. The one due
    to ship first comes first."""
    rows = session.scalars(
        select(OrderPart)
        .join(Order, Order.id == OrderPart.order_id)
        .where(
            OrderPart.seller_id == seller_id,
            OrderPart.status == PartStatus.AUTHORIZED,
            OrderPart.tracking_number.is_(None),
            Order.status.in_([OrderStatus.AUTHORIZED, OrderStatus.PARTLY_SHIPPED]),
        )
    ).all()
    return sorted(rows, key=lambda part: (ship_by(part) or date.max, part.order.created_at, part.reference_id))


def read_by_words() -> str:
    if get_settings().OPENSTALL_MODE == "fake":
        return "the stand-in model of test mode"
    return f"Claude ({get_settings().LLM_MODEL})"


def look_at_photo(
    channel: Channel,
    address: str,
    seller_id: str | None,
    photo: tuple[int, bytes, str],
    llm: Callable[[], LLM],
) -> PhotoReading | None:
    """If the sender has a share waiting for proof of shipping, what the model reads on her photo; else None, and no
    model is asked. Call it before the message's transaction: the model may take seconds."""
    index, data, content_type = photo
    with new_session() as session:
        seller = known_seller(session, channel, address, seller_id)
        waiting = awaiting_proof(session, seller.id) if seller is not None else []
        if seller is None or not waiting:
            return None
        part_id, maker = waiting[0].id, seller.name
    try:
        reading: ReceiptReading | None = read_receipt(llm(), Media(data, content_type), maker=maker)
        error = None
    except (LLMError, AdapterUnavailable) as failure:
        log.warning("The receipt photo from %s could not be read: %s", maker, failure)
        reading, error = None, str(failure)[:200]
    return PhotoReading(part_id, index, reading, read_by_words(), error)


def proof_turn(
    session: Session,
    seller: Seller,
    text: str,
    media: Sequence[dict[str, Any]],
    photo: PhotoReading | None,
    message_id: str,
) -> ProofTurn | None:
    """The receipt flow's answer to her message, or None when the message is not part of it. The caller commits."""
    code = template_language(seller.language)
    if photo is not None:
        kept = media[photo.photo_index] if photo.photo_index < len(media) else {}
        url = kept.get("url")
        if url and (photo.reading is None or photo.reading.is_receipt):
            part = _locked(session, photo.part_id)
            if part is not None and part.status == PartStatus.AUTHORIZED and part.tracking_number is None:
                return _receipt_read(session, part, photo, str(url), message_id, code)
        return None  # not a receipt, or not kept: the chat's usual turn answers it
    pending = _pending(session, seller.id)
    if pending is not None:
        part = _locked(session, pending.id)
        if part is not None and (part.proof_json or {}).get("state") in PENDING and part.tracking_number is None:
            return _answer_pending(session, part, text, code)
    if is_yes(text):
        unpaid = _confirmed_unpaid(session, seller.id)
        if unpaid:
            return ProofTurn(
                [PHRASES[code].retrying.format(order_id=unpaid[0].order_id)], [part.id for part in unpaid]
            )
    return None


def _locked(session: Session, part_id: str) -> OrderPart | None:
    # Locked on Postgres, so two messages at once cannot both confirm (and pay) the same share.
    return session.get(OrderPart, part_id, with_for_update=True, populate_existing=True)


def _pending(session: Session, seller_id: str) -> OrderPart | None:
    """Her share whose receipt is waiting on her: a number to confirm, or one to type. The latest read, if several."""
    waiting = [part for part in awaiting_proof(session, seller_id) if (part.proof_json or {}).get("state") in PENDING]
    return max(waiting, key=lambda part: str((part.proof_json or {}).get("read_at", "")), default=None)


def _confirmed_unpaid(session: Session, seller_id: str) -> list[OrderPart]:
    """Her shares she proved she shipped that are still not paid, where a payout rail can pay her: a payment that
    failed, tried again when she says yes."""
    rows = session.scalars(
        select(OrderPart).where(
            OrderPart.seller_id == seller_id,
            OrderPart.status == PartStatus.AUTHORIZED,
            OrderPart.tracking_number.is_not(None),
        )
    ).all()
    return [part for part in rows if seller_rail(part.seller).available]


def _item(part: OrderPart, code: str) -> str:
    return part.product.title if part.product else PHRASES[code].some_items


def _ask_confirm(part: OrderPart, code: str) -> str:
    proof = part.proof_json or {}
    words = PHRASES[code]
    return words.ask_confirm.format(
        order_id=part.order_id,
        quantity=part.quantity,
        item=_item(part, code),
        carrier=proof.get("carrier") or words.no_carrier,
        tracking=proof.get("tracking_number"),
    )


def _receipt_read(
    session: Session, part: OrderPart, photo: PhotoReading, url: str, message_id: str, code: str
) -> ProofTurn:
    reading = photo.reading
    tracking = reading.tracking_number if reading else None
    carrier = reading.carrier if reading else None
    proof: dict[str, Any] = {
        "photo_url": url,
        "photo_message_id": message_id,
        "carrier": carrier,
        "tracking_number": tracking,
        "source": "photo",
        "read_by": photo.read_by,
        "state": AWAITING_CONFIRMATION if tracking else AWAITING_NUMBER,
        "read_at": utcnow().isoformat(),
    }
    if photo.error:
        proof["read_error"] = photo.error
    part.proof_json = proof
    name = part.seller.name
    if tracking:
        summary = (
            f"{name}'s courier receipt for order {part.order_id} reads {carrier or 'no courier name'}, tracking "
            f"{tracking} (read by {photo.read_by}). She is asked to confirm it"
        )
    else:
        summary = (
            f"{name} sent a courier receipt for order {part.order_id}, but its tracking number could not be read. "
            "She is asked to type it"
        )
    record_event(
        session,
        EventType.TRACKING_READ,
        summary,
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "seller_id": part.seller_id,
            "carrier": carrier,
            "tracking_number": tracking,
            "source": "photo",
            "photo_url": url,
            "read_by": photo.read_by,
        },
    )
    reply = _ask_confirm(part, code) if tracking else PHRASES[code].ask_number.format(order_id=part.order_id)
    return ProofTurn([reply])


def _answer_pending(session: Session, part: OrderPart, text: str, code: str) -> ProofTurn:
    proof = dict(part.proof_json or {})
    words = PHRASES[code]
    if proof.get("state") == AWAITING_CONFIRMATION and is_yes(text):
        return _confirm(session, part, code)
    typed = typed_tracking(text)
    if typed:
        part.proof_json = {**proof, "tracking_number": typed, "source": "typed", "state": AWAITING_CONFIRMATION}
        record_event(
            session,
            EventType.TRACKING_READ,
            f"{part.seller.name} typed her tracking number for order {part.order_id}: {typed}. She is asked to "
            "confirm it",
            entity_id=part.id,
            payload={
                "order_id": part.order_id,
                "seller_id": part.seller_id,
                "carrier": proof.get("carrier"),
                "tracking_number": typed,
                "source": "typed",
            },
        )
        return ProofTurn([_ask_confirm(part, code)])
    if is_no(text):
        part.proof_json = {**proof, "tracking_number": None, "state": AWAITING_NUMBER}
        return ProofTurn([words.ask_again])
    # Anything else: ask again for what is still missing.
    return ProofTurn([_ask_confirm(part, code) if proof.get("state") == AWAITING_CONFIRMATION else words.ask_again])


def _confirm(session: Session, part: OrderPart, code: str) -> ProofTurn:
    proof = dict(part.proof_json or {})
    tracking = str(proof["tracking_number"])
    carrier = proof.get("carrier")
    part.tracking_number = tracking
    part.carrier = carrier
    part.proof_json = {**proof, "state": CONFIRMED, "confirmed_at": utcnow().isoformat()}
    record_event(
        session,
        EventType.TRACKING_CONFIRMED,
        f"{part.seller.name} confirmed her tracking for order {part.order_id}: "
        f"{(carrier + ' ') if carrier else ''}{tracking}",
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "seller_id": part.seller_id,
            "carrier": carrier,
            "tracking_number": tracking,
            "source": proof.get("source"),
        },
    )
    words = PHRASES[code]
    amount = format_money(code, part.amount_usd)
    if seller_rail(part.seller).available:
        return ProofTurn([words.confirmed_paying.format(tracking=tracking, amount=amount)], [part.id])
    return ProofTurn([words.confirmed_waiting.format(tracking=tracking, amount=amount)])


PAYMENT_TROUBLE = (WrongStatus, ClaimHeld, OrderNotFound, PaymentError, PaymentUnavailable, AdapterUnavailable)


def pay_on_proof(
    part_id: str, gateway: Callable[[], PaymentGateway], messenger: Callable[[], Messenger]
) -> bool:
    """Capture and pay one share she proved she shipped, then tell her, in her language, where she chats. Called
    after the message that confirmed her tracking is committed. Returns whether she was paid now."""
    with new_session() as session:
        part = session.get(OrderPart, part_id)
        if part is None or part.status in PAID or part.tracking_number is None:
            return False  # nothing to pay: already paid, or no confirmed tracking
    try:
        with session_scope() as session:
            pay_share(session, part_id, gateway())
    except PAYMENT_TROUBLE as trouble:
        log.warning("Share %s could not be paid on proof: %s", part_id, trouble)
        _tell(part_id, "payment_failed", messenger, reason=str(trouble))
        return False
    deliver_fake_webhooks()  # fake mode: simulated PayPal's capture and payout confirmations follow, as for real
    track_on_paypal(part_id, gateway)  # her tracking on her capture at PayPal (prompt 33); retried later if refused
    _tell(part_id, "paid", messenger)
    return True


def _tell(part_id: str, kind: str, messenger: Callable[[], Messenger], reason: str | None = None) -> None:
    with new_session() as session:
        part = session.get(OrderPart, part_id)
        if part is None:
            return
        seller = part.seller
        code = template_language(seller.language)
        words = PHRASES[code]
        language = language_words(code, seller.language)
        if kind == "paid":
            rail = RAIL_NAMES[seller_rail(seller).kind]
            text = words.paid.format(amount=format_money(code, part.amount_usd), order_id=part.order_id, rail=rail)
            if get_settings().OPENSTALL_MODE == "fake":
                text = f"{text}\n{words.simulated}"
            summary = f"{seller.name} was told {{where}}, in {language}, that she is paid for order {part.order_id}"
        else:
            text = words.payment_failed
            summary = (
                f"{seller.name} was told {{where}}, in {language}, that her payment for order {part.order_id} did "
                f"not go through yet ({(reason or 'no reason given')[:160]})"
            )
        seller_id = seller.id
    send_to_seller(seller_id, text, summary, messenger, payload={"part_id": part_id, "kind": f"proof_{kind}"})
