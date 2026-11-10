"""Disputes answered with the proof (prompt 56).

A buyer who says a maker's parcel never came can open a dispute at PayPal on her capture. PayPal tells OpenStall with
CUSTOMER.DISPUTE.CREATED, then .UPDATED, and .RESOLVED once it decides:

1. In the webhook's transaction, on_dispute_event keeps PayPal's dispute on the share it is about (found by its
   capture id) as `dispute_json`, and records dispute.opened once, in words.
2. After the commit, answer_dispute sends PayPal her proof of shipping: her courier and tracking number (always on a
   paid share: she is captured only once she confirmed them), what happened in words (and that the buyer confirmed
   the parcel arrived, if they did), and her courier receipt photo when she sent one. Only for a parcel the buyer says
   never came, only while PayPal waits for the seller and offers provide_evidence, and once: a claim on the dispute
   id. Anything else needs a person: the receipt says why, and nothing is sent.
3. She is told in her language, after the commit, that PayPal has her proof and she need do nothing; and again once
   PayPal decides.
4. A dispute PayPal decides for the buyer counts against her trust passport (delivery.refresh_passport).

Nothing here moves money: PayPal decides, and any refund is PayPal's.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.adapters import AdapterUnavailable, get_registry
from openstall_api.chat.outbox import send_to_seller
from openstall_api.claims import ClaimHeld, paypal_claim
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.media import ALLOWED_TYPES, URL_PREFIX, get_media_store
from openstall_api.messaging import Messenger
from openstall_api.models import OrderPart, utcnow
from openstall_api.payments import PAID, OrderNotFound, WrongStatus, load_part
from openstall_api.settings import get_settings
from openstall_api.wording import LOCALES, language_words, say, template_language
from openstall_paypal import DisputeEvidence, PaymentError, PaymentGateway, PaymentUnavailable
from openstall_paypal.disputes import ANSWERABLE, REASONS, can_answer, disputed_captures

log = logging.getLogger(__name__)

# Where a dispute stands on our side.
OPEN = "open"  # to be answered with her proof, after the commit
WAITING = "waiting"  # answerable, but PayPal does not take the seller's evidence yet
ANSWERED = "answered"
NEEDS_PERSON = "needs_person"  # not answered by code: a person must
RESOLVED = "resolved"

DisputeState = Literal["open", "waiting", "answered", "needs_person", "resolved"]
Outcome = Literal["seller", "buyer", "other"]
OUTCOMES: dict[str, Outcome] = {"RESOLVED_SELLER_FAVOUR": "seller", "RESOLVED_BUYER_FAVOUR": "buyer"}
OUTCOME_WORDS: dict[Outcome, str] = {
    "seller": "in her favour",
    "buyer": "for the buyer",
    "other": "closed",
}
# After the commit: answer it with her proof, or tell her PayPal decided.
FollowUp = tuple[Literal["answer", "tell_resolved"], str]


@dataclass(frozen=True)
class DisputePhrases:
    """One language's words for a dispute on her share."""

    answered: str  # {order_id}, {reason}, {tracking}, {receipt}
    receipt: str  # added to `answered` when her courier receipt photo went too
    not_received: str  # the reason in her words: the parcel did not arrive
    other_reason: str  # any other reason, which a person answers
    resolved_mine: str  # {order_id}
    resolved_buyer: str  # {order_id}
    resolved_other: str  # {order_id}
    simulated: str  # added in test mode


PHRASES: dict[str, DisputePhrases] = {
    "en": DisputePhrases(
        answered="A buyer opened a PayPal dispute on order {order_id}, saying {reason}. OpenStall has sent PayPal "
        "your tracking number {tracking}{receipt}. You do not need to do anything.",
        receipt=" and the photo of your courier receipt",
        not_received="the parcel did not arrive",
        other_reason="there is a problem",
        resolved_mine="PayPal closed the dispute on order {order_id} in your favour. Your payment stays yours.",
        resolved_buyer="PayPal decided the dispute on order {order_id} for the buyer. OpenStall will contact you "
        "about it.",
        resolved_other="PayPal closed the dispute on order {order_id}.",
        simulated="(Test mode: simulated PayPal, no real money moved.)",
    ),
    "ur": DisputePhrases(
        answered="ایک خریدار نے آرڈر {order_id} پر PayPal میں شکایت کی ہے کہ {reason}۔ OpenStall نے PayPal کو آپ کا "
        "ٹریکنگ نمبر {tracking}{receipt} بھیج دیا ہے۔ آپ کو کچھ کرنے کی ضرورت نہیں۔",
        receipt=" اور کورئیر رسید کی تصویر",
        not_received="پارسل نہیں پہنچا",
        other_reason="کوئی مسئلہ ہے",
        resolved_mine="PayPal نے آرڈر {order_id} کی شکایت آپ کے حق میں بند کر دی ہے۔ آپ کی ادائیگی آپ ہی کی ہے۔",
        resolved_buyer="PayPal نے آرڈر {order_id} کی شکایت کا فیصلہ خریدار کے حق میں کیا ہے۔ OpenStall اس بارے میں "
        "آپ سے رابطہ کرے گا۔",
        resolved_other="PayPal نے آرڈر {order_id} کی شکایت بند کر دی ہے۔",
        simulated="(ٹیسٹ موڈ: نقلی PayPal، کوئی اصل رقم منتقل نہیں ہوئی۔)",
    ),
    "hi": DisputePhrases(
        answered="एक खरीदार ने ऑर्डर {order_id} पर PayPal में शिकायत की है कि {reason}। OpenStall ने PayPal को "
        "आपका ट्रैकिंग नंबर {tracking}{receipt} भेज दिया है। आपको कुछ करने की ज़रूरत नहीं है।",
        receipt=" और कूरियर रसीद की फ़ोटो",
        not_received="पार्सल नहीं पहुँचा",
        other_reason="कोई समस्या है",
        resolved_mine="PayPal ने ऑर्डर {order_id} की शिकायत आपके पक्ष में बंद कर दी है। आपका भुगतान आपका ही रहेगा।",
        resolved_buyer="PayPal ने ऑर्डर {order_id} की शिकायत का फ़ैसला खरीदार के पक्ष में किया है। OpenStall इस "
        "बारे में आपसे संपर्क करेगा।",
        resolved_other="PayPal ने ऑर्डर {order_id} की शिकायत बंद कर दी है।",
        simulated="(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)",
    ),
    "es": DisputePhrases(
        answered="Un comprador abrió una disputa en PayPal por el pedido {order_id}: dice que {reason}. OpenStall ya "
        "envió a PayPal tu número de guía {tracking}{receipt}. No tienes que hacer nada.",
        receipt=" y la foto de tu recibo de paquetería",
        not_received="el paquete no llegó",
        other_reason="hay un problema",
        resolved_mine="PayPal cerró la disputa del pedido {order_id} a tu favor. Tu pago sigue siendo tuyo.",
        resolved_buyer="PayPal resolvió la disputa del pedido {order_id} a favor del comprador. OpenStall se pondrá "
        "en contacto contigo.",
        resolved_other="PayPal cerró la disputa del pedido {order_id}.",
        simulated="(Modo de prueba: PayPal simulado, no se movió dinero real.)",
    ),
}
assert PHRASES.keys() == LOCALES.keys(), "every template language has the dispute's words too"

PAYMENT_TROUBLE = (WrongStatus, ClaimHeld, OrderNotFound, PaymentError, PaymentUnavailable, AdapterUnavailable)
MEDIA_TYPES = {extension: kind for kind, extension in ALLOWED_TYPES.items()}


def _simulated() -> str:
    return " (simulated PayPal)" if get_settings().OPENSTALL_MODE == "fake" else ""


def reason_words(reason: str | None) -> str:
    return REASONS.get(reason or "OTHER", REASONS["OTHER"])


def on_dispute_event(session: Session, kind: str, dispute: Mapping[str, Any]) -> FollowUp | None:
    """Keep PayPal's dispute on the share it is about, in the webhook's transaction. Returns what to do after the
    commit: answer it with her proof, or tell her PayPal decided."""
    dispute_id = str(dispute.get("dispute_id") or "")[:64]
    captures = disputed_captures(dispute)
    if not dispute_id or not captures:
        return None
    part = session.scalar(select(OrderPart).where(OrderPart.capture_id.in_(captures)))
    if part is None:
        log.warning("PayPal dispute %s names no share of ours (%s)", dispute_id, ", ".join(captures))
        return None
    old = dict(part.dispute_json or {})
    first = old.get("dispute_id") != dispute_id
    if first:
        old = {}
    reason = str(dispute.get("reason") or "OTHER")
    status = str(dispute.get("status") or "")
    amount = (dispute.get("dispute_amount") or {}).get("value")
    record: dict[str, Any] = {
        **old,
        "dispute_id": dispute_id,
        "reason": reason,
        "status": status,
        "stage": dispute.get("dispute_life_cycle_stage"),
        "amount_usd": str(amount) if amount is not None else None,
        "due": dispute.get("seller_response_due_date"),
        "opened_at": old.get("opened_at") or utcnow().isoformat(),
    }
    name, order_id = part.seller.name, part.order_id

    if kind == "CUSTOMER.DISPUTE.RESOLVED" or status == "RESOLVED":
        if old.get("state") == RESOLVED:
            part.dispute_json = record
            return None
        code = str((dispute.get("dispute_outcome") or {}).get("outcome_code") or "")
        outcome: Outcome = OUTCOMES.get(code, "other")
        record.update(state=RESOLVED, outcome=outcome, outcome_code=code or None, resolved_at=utcnow().isoformat())
        part.dispute_json = record
        record_event(
            session,
            EventType.DISPUTE_RESOLVED,
            f"PayPal decided the buyer's dispute on {name}'s share of order {order_id}: {OUTCOME_WORDS[outcome]}"
            f"{_simulated()}",
            entity_id=part.id,
            payload={"order_id": order_id, "dispute_id": dispute_id, "outcome": outcome, "outcome_code": code or None},
        )
        if outcome == "buyer":
            from openstall_api.delivery import refresh_passport  # delivery imports payments, as this module does

            refresh_passport(session, part.seller_id)
        return ("tell_resolved", part.id)

    if old.get("state") in (ANSWERED, NEEDS_PERSON):
        part.dispute_json = {**record, "state": old["state"]}  # PayPal's news on a dispute already handled
        return None
    if reason not in ANSWERABLE:
        state, why = NEEDS_PERSON, f"the buyer says {reason_words(reason)}, which proof of shipping does not answer"
    elif part.status not in PAID or not part.tracking_number:
        state, why = NEEDS_PERSON, "her share has no confirmed tracking to send"
    elif can_answer(dispute):
        state, why = OPEN, None
    else:
        state, why = WAITING, "PayPal does not take the seller's evidence on it yet"
    part.dispute_json = {**record, "state": state, "why": why}
    if first:
        money = f" (${float(amount):,.2f})" if amount is not None else ""
        then = {
            OPEN: "OpenStall answers with her proof of shipping",
            WAITING: f"OpenStall answers with her proof once PayPal asks for it: {why}",
            NEEDS_PERSON: f"It needs a person: {why}",
        }[state]
        record_event(
            session,
            EventType.DISPUTE_OPENED,
            f"The buyer opened a PayPal dispute on {name}'s share of order {order_id}{money}: "
            f"{reason_words(reason)}. {then}{_simulated()}",
            entity_id=part.id,
            payload={"order_id": order_id, "dispute_id": dispute_id, "reason": reason, "state": state},
        )
    return ("answer", part.id) if state == OPEN else None


def evidence_for(part: OrderPart, dispute_id: str) -> DisputeEvidence:
    """Her proof of shipping, as PayPal takes it: her courier and tracking, what happened in words, her receipt photo."""
    assert part.tracking_number is not None
    proof = part.proof_json or {}
    carrier = part.carrier or str(proof.get("carrier") or "") or "her courier (not named)"
    photo = photo_name = photo_type = None
    url = str(proof.get("photo_url") or "")
    if url.startswith(f"{URL_PREFIX}/"):
        key = url.rsplit("/", 1)[1]
        extension = "." + key.rsplit(".", 1)[-1]
        try:
            photo, photo_type = get_media_store().read(key), MEDIA_TYPES.get(extension, "image/jpeg")
            photo_name = f"courier-receipt-{part.id}{extension}"
        except (KeyError, OSError):
            log.warning("Share %s's receipt photo %s could not be read for its dispute", part.id, key)
    seller = part.seller
    where = ", ".join(place for place in (seller.city, seller.country) if place)
    item = part.product.title if part.product else "her items"
    confirmed = proof.get("confirmed_at")
    notes = (
        f"OpenStall Collective order {part.order_id}: {part.quantity} x {item}, made and sent by {seller.name}"
        f"{f' ({where})' if where else ''}. Shipped with {carrier}, tracking number {part.tracking_number}"
        f"{f', confirmed by her on {str(confirmed)[:10]}' if confirmed else ''}."
    )
    if part.delivered_at is not None:
        notes += f" The buyer confirmed on {part.delivered_at:%Y-%m-%d} that the parcel arrived."
    if photo is not None:
        notes += " Her courier receipt photo is attached."
    return DisputeEvidence(
        dispute_id=dispute_id,
        part_id=part.id,
        carrier=carrier,
        tracking_number=part.tracking_number,
        notes=notes,
        photo=photo,
        photo_name=photo_name,
        photo_type=photo_type,
    )


def answer_dispute(part_id: str, gateway: Callable[[], PaymentGateway], messenger: Callable[[], Messenger]) -> bool:
    """After the commit: send PayPal her proof for the dispute on her share, once, then tell her. Returns whether it
    was sent now. Trouble leaves the dispute open with the reason, for a person or PayPal's next update."""
    try:
        with session_scope() as session:
            part = load_part(session, part_id)  # locks the order: two calls cannot both answer it
            record = dict(part.dispute_json or {})
            if record.get("state") != OPEN:
                return False
            dispute_id = str(record["dispute_id"])
            evidence = evidence_for(part, dispute_id)
            with paypal_claim(
                session,
                f"dispute:{dispute_id}",
                f"openstall-evidence-{dispute_id}",
                busy=f"The dispute on {part.seller.name}'s share is being answered by another request.",
            ) as claim:
                gateway().answer_dispute(evidence)
                claim.result = dispute_id
            record.update(
                state=ANSWERED,
                answered_at=utcnow().isoformat(),
                evidence={
                    "carrier": evidence.carrier,
                    "tracking_number": evidence.tracking_number,
                    "photo": evidence.photo is not None,
                    "delivered": part.delivered_at is not None,
                },
                error=None,
            )
            part.dispute_json = record
            sent = f"{evidence.carrier} {evidence.tracking_number}" + (
                ", her courier receipt photo" if evidence.photo is not None else ""
            )
            if part.delivered_at is not None:
                sent += ", and the buyer's own confirmation that it arrived"
            record_event(
                session,
                EventType.DISPUTE_ANSWERED,
                f"OpenStall answered the buyer's PayPal dispute on {part.seller.name}'s share of order "
                f"{part.order_id} with her proof of shipping: {sent}{_simulated()}",
                entity_id=part.id,
                payload={"order_id": part.order_id, "dispute_id": dispute_id, "photo": evidence.photo is not None},
            )
            seller_id, name = part.seller_id, part.seller.name
            code, order_id = template_language(part.seller.language), part.order_id
            language = language_words(code, part.seller.language)
            tracking, with_photo, reason = evidence.tracking_number, evidence.photo is not None, record.get("reason")
    except PAYMENT_TROUBLE as trouble:
        log.warning("The dispute on share %s could not be answered: %s", part_id, trouble)
        with session_scope() as session:
            part = session.get(OrderPart, part_id)
            if part is not None and part.dispute_json:
                part.dispute_json = {**part.dispute_json, "error": str(trouble)[:200]}
        return False
    fake = get_settings().OPENSTALL_MODE == "fake"

    def compose(used: str) -> str:
        words = PHRASES[used]
        answered = words.answered.format(
            order_id=order_id,
            reason=words.not_received if reason in ANSWERABLE else words.other_reason,
            tracking=tracking,
            receipt=words.receipt if with_photo else "",
        )
        return f"{answered}\n{words.simulated}" if fake else answered

    text = say(code, compose)
    send_to_seller(
        seller_id,
        text,
        f"{name} was told {{where}}, in {language}, that her proof answered the dispute on order {order_id}",
        messenger,
        payload={"part_id": part_id, "kind": "dispute_answered"},
    )
    return True


def tell_resolved(part_id: str, messenger: Callable[[], Messenger]) -> bool:
    """After the commit: tell her, in her language, that PayPal decided the dispute on her share."""
    with new_session() as session:
        part = session.get(OrderPart, part_id)
        if part is None or (part.dispute_json or {}).get("state") != RESOLVED:
            return False
        outcome = (part.dispute_json or {}).get("outcome")
        seller = part.seller
        code = template_language(seller.language)
        fake = get_settings().OPENSTALL_MODE == "fake"

        def compose(used: str) -> str:
            words = PHRASES[used]
            template = {"seller": words.resolved_mine, "buyer": words.resolved_buyer}.get(
                str(outcome), words.resolved_other
            )
            decided = template.format(order_id=part.order_id)
            return f"{decided}\n{words.simulated}" if fake else decided

        text = say(code, compose)
        summary = (
            f"{seller.name} was told {{where}}, in {language_words(code, seller.language)}, that PayPal decided the "
            f"dispute on order {part.order_id}: {OUTCOME_WORDS.get(outcome, 'closed')}"
        )
        seller_id = seller.id
    send_to_seller(seller_id, text, summary, messenger, payload={"part_id": part_id, "kind": "dispute_resolved"})
    return True


def dispute_words(record: Mapping[str, Any] | None) -> str | None:
    """The dispute on her share, in words for the buyer's receipt, /demo and the buyer's agent. None without one."""
    if not record or not record.get("dispute_id"):
        return None
    reason = reason_words(record.get("reason"))
    simulated = _simulated()
    state = record.get("state")
    if state == RESOLVED:
        outcome = record.get("outcome")
        if outcome == "seller":
            return f"PayPal dispute ({reason}): decided in her favour{simulated}"
        if outcome == "buyer":
            return f"PayPal dispute ({reason}): decided for the buyer{simulated}"
        return f"PayPal dispute ({reason}): closed{simulated}"
    if state == ANSWERED:
        evidence = record.get("evidence") or {}
        sent = f"{evidence.get('carrier')} {evidence.get('tracking_number')}"
        if evidence.get("photo"):
            sent += " and her courier receipt photo"
        return f"PayPal dispute: the buyer says {reason}. Answered with her proof of shipping: {sent}{simulated}"
    if state == NEEDS_PERSON:
        return f"PayPal dispute: the buyer says {reason}. Needs a person: {record.get('why')}"
    if state == WAITING:
        return f"PayPal dispute: the buyer says {reason}. Her proof goes to PayPal once it asks for it{simulated}"
    error = record.get("error")
    if error:
        return f"PayPal dispute: the buyer says {reason}. Her proof could not be sent yet: {error}"
    return f"PayPal dispute: the buyer says {reason}. Answering with her proof of shipping…"


def after_dispute_event(follow: FollowUp) -> None:
    """What a dispute event leaves for after its commit (webhooks.receive_paypal_webhook): answer it, or tell her.
    The event itself is handled whatever happens here, so PayPal never sends it again for this."""
    registry = get_registry()
    action, part_id = follow
    try:
        if action == "answer":
            answer_dispute(part_id, lambda: registry.payment_gateway, lambda: registry.messenger)
            from openstall_api.webhooks import deliver_fake_webhooks  # webhooks calls this module

            deliver_fake_webhooks()  # test mode: simulated PayPal's decision follows, as for real
        else:
            tell_resolved(part_id, lambda: registry.messenger)
    except Exception:
        log.exception("After a dispute event on share %s, %s did not finish", part_id, action)
