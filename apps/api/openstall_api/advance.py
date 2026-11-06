"""A materials advance for a trusted maker (prompt 37). A maker whose signed trust passport scores 0.90 or more can ask
in her chat for part of a reserved share ahead, to buy her cloth and thread. OpenStall pays it from its own balance, by
Payouts on her rail: nothing is taken from the buyer's hold. When she proves she shipped, her share is captured whole
as always, and her payout then is that much less. If she never ships, the advance is OpenStall's loss, never the
buyer's: that is why only a strong, signed record earns one.

1. Inside her message's transaction, advance_turn answers "can I have an advance?" (in her language): the amount (a
   quarter of her share, in whole cents) and a question, or why she cannot have one (her score, no share waiting on
   her, no payout rail yet). Her yes accepts it; her no takes it back.
2. After that commit, pay_advance_after pays it out (gateway.pay_advance, claimed like every PayPal write), records
   advance.paid and tells her, in her language.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from sqlalchemy.orm import Session

from openstall_api.chat.outbox import send_to_seller
from openstall_api.claims import paypal_claim
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.healing import state_of as drop_state
from openstall_api.messaging import Messenger
from openstall_api.models import OrderPart, PartStatus, Passport, Seller, utcnow
from openstall_api.payments import load_part, seller_rail, share_of
from openstall_api.proof import PAYMENT_TROUBLE, PENDING, awaiting_proof, is_no, is_yes, normalise
from openstall_api.settings import get_settings
from openstall_api.wording import LOCALES, format_money, language_words, template_language
from openstall_paypal import RAIL_NAMES, Advance, PaymentGateway
from openstall_trust import trust_score

log = logging.getLogger(__name__)

ADVANCE_RATE = Decimal("0.25")  # a quarter of her share
MIN_SCORE = 0.90  # her signed trust score must be at least this
CENT = Decimal("0.01")

ASKED = "asked"  # offered to her; she has not said yes yet
ACCEPTED = "accepted"  # she said yes; paid out after the commit
PAID = "paid"


@dataclass(frozen=True)
class AdvancePhrases:
    """One language's words for the advance. Money is written by wording.py."""

    offer: str  # {amount}, {order_id}, {share}, {rest}
    accepted: str  # {amount}
    paid: str  # {amount}, {rail}
    paid_bank: str  # {amount}: to her bank through Hyperwallet
    simulated: str  # added to `paid` in test mode
    hyperwallet: str  # added to `paid_bank` in sandbox mode: Hyperwallet is simulated
    declined: str
    low_score: str  # {score}
    no_share: str
    no_rail: str
    already: str  # {amount}


PHRASES: dict[str, AdvancePhrases] = {
    "en": AdvancePhrases(
        offer="Yes: your trust record lets OpenStall pay you {amount} now for materials, ahead of your {share} share "
        "of order {order_id}. You get the other {rest} when you send your courier receipt. If you could not deliver, "
        "you would not have to pay it back. Reply YES to take it, or NO.",
        accepted="Thank you! Your {amount} advance is on its way.",
        paid="Your advance of {amount} for materials has been sent to your {rail} account.",
        paid_bank="Your advance of {amount} for materials has been sent to your bank account through Hyperwallet.",
        simulated="(Test mode: simulated PayPal, no real money moved.)",
        hyperwallet="(Hyperwallet is simulated here: no real money reached your bank.)",
        declined="All right: no advance. You are paid your whole share when you send your courier receipt.",
        low_score="An advance needs a trust score of 0.90 or more, and yours is {score}. Every delivery on time raises "
        "it.",
        no_share="An advance is paid on an order you have not shipped yet, and you have none right now.",
        no_rail="Payouts to your country are not connected yet, so OpenStall cannot send you an advance.",
        already="You already have an advance of {amount} on this order.",
    ),
    "ur": AdvancePhrases(
        offer="جی ہاں: آپ کے اعتماد کے ریکارڈ کی بنا پر OpenStall آپ کو آرڈر {order_id} میں آپ کے {share} کے حصے میں "
        "سے "
        "{amount} ابھی سامان کے لیے دے سکتا ہے۔ باقی {rest} آپ کو کورئیر رسید بھیجنے پر ملیں گے۔ اگر آپ ڈیلیور نہ کر "
        "سکیں تو یہ "
        "رقم واپس نہیں کرنی ہوگی۔ لینے کے لیے \"ہاں\" لکھیں، ورنہ \"نہیں\"۔",
        accepted="شکریہ! آپ کی {amount} کی پیشگی رقم بھیجی جا رہی ہے۔",
        paid="سامان کے لیے آپ کی {amount} کی پیشگی رقم آپ کے {rail} اکاؤنٹ میں بھیج دی گئی ہے۔",
        paid_bank="سامان کے لیے آپ کی {amount} کی پیشگی رقم Hyperwallet کے ذریعے آپ کے بینک اکاؤنٹ میں بھیج دی "
        "گئی ہے۔",
        simulated="(ٹیسٹ موڈ: نقلی PayPal، کوئی اصل رقم منتقل نہیں ہوئی۔)",
        hyperwallet="(یہاں Hyperwallet نقلی ہے: آپ کے بینک میں کوئی اصل رقم نہیں پہنچی۔)",
        declined="ٹھیک ہے: کوئی پیشگی نہیں۔ کورئیر رسید بھیجنے پر آپ کو پورا حصہ ملے گا۔",
        low_score="پیشگی رقم کے لیے اعتماد کا اسکور کم از کم 0.90 ہونا چاہیے، اور آپ کا {score} ہے۔ ہر بروقت ڈیلیوری "
        "سے یہ "
        "بڑھتا ہے۔",
        no_share="پیشگی رقم اس آرڈر پر ملتی ہے جو آپ نے ابھی بھیجا نہ ہو، اور ابھی آپ کے پاس ایسا کوئی آرڈر نہیں۔",
        no_rail="آپ کے ملک میں ادائیگی کا انتظام ابھی مکمل نہیں ہوا، اس لیے OpenStall آپ کو پیشگی رقم نہیں بھیج سکتا۔",
        already="اس آرڈر پر آپ کو {amount} کی پیشگی رقم پہلے ہی مل چکی ہے۔",
    ),
    "hi": AdvancePhrases(
        offer="हाँ: आपके भरोसे के रिकॉर्ड की वजह से OpenStall आपको ऑर्डर {order_id} में आपके {share} के हिस्से में से "
        "{amount} अभी सामान के लिए दे सकता है। बाकी {rest} आपको कूरियर रसीद भेजने पर मिलेंगे। अगर आप डिलीवर न कर "
        "सकें तो "
        "यह रकम लौटानी नहीं होगी। लेने के लिए \"हाँ\" लिखें, वरना \"नहीं\"।",
        accepted="धन्यवाद! आपकी {amount} की अग्रिम राशि भेजी जा रही है।",
        paid="सामान के लिए आपकी {amount} की अग्रिम राशि आपके {rail} खाते में भेज दी गई है।",
        paid_bank="सामान के लिए आपकी {amount} की अग्रिम राशि Hyperwallet के ज़रिए आपके बैंक खाते में भेज दी गई "
        "है।",
        simulated="(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)",
        hyperwallet="(यहाँ Hyperwallet नकली है: आपके बैंक में कोई असली पैसा नहीं पहुँचा।)",
        declined="ठीक है: कोई अग्रिम नहीं। कूरियर रसीद भेजने पर आपको पूरा हिस्सा मिलेगा।",
        low_score="अग्रिम राशि के लिए भरोसे का स्कोर कम से कम 0.90 होना चाहिए, और आपका {score} है। हर समय पर डिलीवरी "
        "से "
        "यह बढ़ता है।",
        no_share="अग्रिम राशि उस ऑर्डर पर मिलती है जो आपने अभी भेजा न हो, और अभी आपके पास ऐसा कोई ऑर्डर नहीं है।",
        no_rail="आपके देश में भुगतान की व्यवस्था अभी पूरी नहीं हुई है, इसलिए OpenStall आपको अग्रिम राशि नहीं भेज सकता।",
        already="इस ऑर्डर पर आपको {amount} की अग्रिम राशि पहले ही मिल चुकी है।",
    ),
    "es": AdvancePhrases(
        offer="Sí: tu historial de confianza permite que OpenStall te pague {amount} ahora para materiales, a cuenta "
        "de "
        "tu parte de {share} del pedido {order_id}. Los otros {rest} te llegan cuando mandes tu recibo de paquetería. "
        "Si no pudieras entregar, no tendrías que devolverlo. Responde SÍ para aceptarlo, o NO.",
        accepted="¡Gracias! Tu anticipo de {amount} va en camino.",
        paid="Tu anticipo de {amount} para materiales se envió a tu cuenta de {rail}.",
        paid_bank="Tu anticipo de {amount} para materiales se envió a tu cuenta bancaria a través de "
        "Hyperwallet.",
        simulated="(Modo de prueba: PayPal simulado, no se movió dinero real.)",
        hyperwallet="(Aquí Hyperwallet es simulado: no llegó dinero real a tu banco.)",
        declined="Muy bien: sin anticipo. Recibes tu parte completa cuando mandes tu recibo de paquetería.",
        low_score="Un anticipo necesita una puntuación de confianza de 0.90 o más, y la tuya es {score}. Cada "
        "entrega a "
        "tiempo la sube.",
        no_share="Un anticipo se paga sobre un pedido que todavía no has enviado, y ahora no tienes ninguno.",
        no_rail="Los pagos a tu país todavía no están conectados, así que OpenStall no puede enviarte un anticipo.",
        already="Ya tienes un anticipo de {amount} en este pedido.",
    ),
}
assert PHRASES.keys() == LOCALES.keys(), "every template language has the advance's words too"

# "Can I have an advance?", as makers write it, compared after proof.normalise. Asking only gets an answer: nothing is
# paid before her yes.
ASKING = tuple(
    normalise(phrase)
    for phrase in (
        "advance", "pay me ahead", "money for materials", "money up front", "money upfront",
        "پیشگی", "ایڈوانس",
        "अग्रिम", "एडवांस",
        "anticipo", "adelanto",
    )
)  # fmt: skip


def asks_for_advance(words: str) -> bool:
    said = f" {normalise(words)} "
    return any(f" {phrase} " in said for phrase in ASKING)


@dataclass(frozen=True)
class AdvanceTurn:
    replies: list[str]
    pay_after: list[str] = field(default_factory=list)  # advances to pay out once the message is committed


def state_of(part: OrderPart) -> str | None:
    return (part.advance_json or {}).get("state")


def advance_amount(part: OrderPart) -> Decimal:
    return (part.amount_usd * ADVANCE_RATE).quantize(CENT, rounding=ROUND_DOWN)


def score_of(session: Session, seller_id: str) -> float | None:
    passport = session.get(Passport, seller_id)
    if passport is None:
        return None
    metrics = passport.metrics_json
    return float(trust_score(metrics["on_time_rate"], metrics["dispute_rate"], metrics["photo_originality"]))


def advance_turn(session: Session, seller: Seller, words: str, message_id: str) -> AdvanceTurn | None:
    """The advance's answer to her message, or None when the message is not about one. The caller commits."""
    code = template_language(seller.language)
    phrases = PHRASES[code]
    waiting = [
        part
        for part in awaiting_proof(session, seller.id)
        if (part.proof_json or {}).get("state") not in PENDING and drop_state(part) is None
    ]
    offered = next((part for part in waiting if state_of(part) == ASKED), None)
    if offered is not None and (is_yes(words) or is_no(words)):
        part = session.get(OrderPart, offered.id, with_for_update=True, populate_existing=True)
        if part is not None and state_of(part) == ASKED and part.status == PartStatus.AUTHORIZED:
            amount = Decimal(str((part.advance_json or {})["amount_usd"]))
            if is_no(words):
                part.advance_json = None
                return AdvanceTurn([phrases.declined])
            part.advance_json = {**(part.advance_json or {}), "state": ACCEPTED, "accepted_at": utcnow().isoformat()}
            return AdvanceTurn([phrases.accepted.format(amount=format_money(code, amount))], [part.id])
    if not asks_for_advance(words):
        return None
    if not waiting:
        return AdvanceTurn([phrases.no_share])
    part = waiting[0]
    if state_of(part) in (ACCEPTED, PAID):
        amount = Decimal(str((part.advance_json or {})["amount_usd"]))
        return AdvanceTurn([phrases.already.format(amount=format_money(code, amount))])
    score = score_of(session, seller.id)
    if score is None or score < MIN_SCORE:
        return AdvanceTurn([phrases.low_score.format(score=f"{score or 0:.2f}")])
    if not seller_rail(seller).available:
        return AdvanceTurn([phrases.no_rail])
    amount = advance_amount(part)
    part.advance_json = {"state": ASKED, "amount_usd": str(amount), "asked_at": utcnow().isoformat(), "score": score}
    record_event(
        session,
        EventType.ADVANCE_REQUESTED,
        f"{seller.name} asked for an advance on her share of order {part.order_id}: her trust score {score:.2f} earns "
        f"${amount:,.2f} for materials, paid by OpenStall, not the buyer",
        entity_id=part.id,
        payload={"order_id": part.order_id, "amount_usd": amount, "score": score, "message_id": message_id},
    )
    return AdvanceTurn(
        [
            phrases.offer.format(
                amount=format_money(code, amount),
                share=format_money(code, part.amount_usd),
                rest=format_money(code, part.amount_usd - amount),
                order_id=part.order_id,
            )
        ]
    )


def pay_advance_after(
    part_id: str, gateway: Callable[[], PaymentGateway], messenger: Callable[[], Messenger]
) -> bool:
    """Pay out an advance she accepted, once, then tell her. Called after the message with her yes is committed.
    Returns whether it was paid now."""
    try:
        with session_scope() as session:
            part = load_part(session, part_id)  # locks the order: two calls cannot both pay it
            if state_of(part) != ACCEPTED or part.status != PartStatus.AUTHORIZED:
                return False
            amount = Decimal(str((part.advance_json or {})["amount_usd"]))
            name = part.seller.name
            with paypal_claim(
                session,
                f"advance:{part.id}",
                f"openstall-advance-{part.id}",
                busy=f"{name}'s advance is being paid by another request. Try again in a moment.",
            ) as claim:
                payment = gateway().pay_advance(Advance(share_of(part), amount))
                claim.result = payment.payout_batch_id or "simulated"
            part.advance_json = {
                **(part.advance_json or {}),
                "state": PAID,
                "paid_at": utcnow().isoformat(),
                "payout_batch_id": payment.payout_batch_id,
                "payout_simulated": payment.payout_simulated,
            }
            simulated = (
                " (simulated PayPal)"
                if get_settings().OPENSTALL_MODE == "fake"
                else " (simulated Hyperwallet)"
                if payment.payout_rail == "hyperwallet"
                else ""
            )
            record_event(
                session,
                EventType.ADVANCE_PAID,
                f"OpenStall paid {name} a ${amount:,.2f} advance for materials, ahead of her share of order "
                f"{part.order_id}{simulated}: her payout when she ships is that "
                "much less",
                entity_id=part.id,
                payload={"order_id": part.order_id, "amount_usd": amount, "payout_batch_id": payment.payout_batch_id},
            )
            seller_id, code, rail = part.seller_id, template_language(part.seller.language), seller_rail(part.seller)
            language = language_words(code, part.seller.language)
            order_id = part.order_id
    except PAYMENT_TROUBLE as trouble:
        log.warning("The advance on share %s could not be paid: %s", part_id, trouble)
        return False
    words = PHRASES[code]
    if rail.kind == "hyperwallet":
        text = words.paid_bank.format(amount=format_money(code, amount))
    else:
        text = words.paid.format(amount=format_money(code, amount), rail=RAIL_NAMES[rail.kind])
    if get_settings().OPENSTALL_MODE == "fake":
        text = f"{text}\n{words.simulated}"
    elif rail.kind == "hyperwallet":
        text = f"{text}\n{words.hyperwallet}"
    send_to_seller(
        seller_id,
        text,
        f"{name} was told {{where}}, in {language}, that her advance for order {order_id} is paid",
        messenger,
        payload={"part_id": part_id, "kind": "advance_paid"},
    )
    return True
