"""The order heals itself (prompt 39): a maker who cannot make her share says so in her chat and confirms; her share is
released, never charged; OpenStall then asks the other makers' agents for her units and drafts a top-up order, which
the buyer approves like any other order.

1. Inside the chat handler's transaction, drop_turn answers a maker with a share waiting for proof of shipping
   (reserved at PayPal, no tracking yet) who says she cannot make it ("I can't make this order", in her language): she
   is asked, in her language, to confirm. Her yes marks the share dropped and records part.dropped; her no keeps it.
   Nothing moves on her first words alone, as nothing is paid on a receipt reading alone.
2. After that commit, heal_after releases her share (payments.release_share: PayPal voids the hold only when hers was
   its last open share) and re-plans her units: a quote request for her quantity, by the order's deadline, to the
   order's city, at most the buyer's price, asked of every matching maker but her (quotes.py: up to 3 rounds), split by
   the allocator, and drafted as a top-up order that points at the order it repairs (orders.parent_order_id).
3. The buyer approves the top-up on its own approval page, like any order: PayPal holds its total, its makers are told
   then, and each is paid on proof. Nothing is charged for it before a person approves it.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from openstall_agents.adapters import LLM
from openstall_api import quotes
from openstall_api.collective import DraftError, approval_url, draft_from_plan
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.models import OrderPart, PartStatus, Seller, utcnow
from openstall_api.models import QuoteRequest as QuoteRequestRow
from openstall_api.notices import ship_by
from openstall_api.payments import release_share
from openstall_api.proof import PAYMENT_TROUBLE, PENDING, awaiting_proof, is_no, is_yes, normalise
from openstall_api.quotes import QuoteError, create_quote_request, run_quote
from openstall_api.webhooks import deliver_fake_webhooks
from openstall_api.wording import LOCALES, format_day, format_money, say, template_language
from openstall_paypal import PaymentGateway

log = logging.getLogger(__name__)

ASKED = "asked"  # she said she cannot make it, and was asked to confirm
KEPT = "kept"  # asked, she said no: she keeps her share
DROPPED = "dropped"  # she confirmed: her share is released and her units re-planned


@dataclass(frozen=True)
class DropPhrases:
    """One language's words for dropping out. Dates and money are written by wording.py."""

    ask: str  # {order_id}, {quantity}, {item}, {amount}
    some_items: str  # in place of the item, when her listing is gone
    dropped: str  # {order_id}
    kept: str  # {order_id}
    ship_by: str  # added to `kept`: {day}


PHRASES: dict[str, DropPhrases] = {
    "en": DropPhrases(
        ask="I'm sorry to hear that. Do you want to give up your share of order {order_id} ({quantity} × {item}, "
        "{amount})? OpenStall will ask other makers to make it, and you will not be paid for it. Reply YES to give it "
        "up, or NO to keep it.",
        some_items="your items",
        dropped="Done: your share of order {order_id} goes back to the buyer, and nothing is charged for it. Thank you "
        "for telling us in time. OpenStall is asking other makers to make it.",
        kept="Good: you keep your share of order {order_id}.",
        ship_by=" Please ship it by {day}.",
    ),
    "ur": DropPhrases(
        ask="یہ سن کر افسوس ہوا۔ کیا آرڈر {order_id} ({quantity} × {item}، {amount}) میں سے آپ کا حصہ چھوڑ دیا جائے؟ "
        "OpenStall یہ دوسرے کاریگروں سے بنوائے گا، اور اس کی ادائیگی آپ کو نہیں ہوگی۔ چھوڑنے کے لیے \"ہاں\" "
        "لکھیں، یا رکھنے کے لیے \"نہیں\"۔",
        some_items="آپ کا سامان",
        dropped="ہو گیا: آرڈر {order_id} میں سے آپ کا حصہ خریدار کو واپس چلا گیا ہے، اور اس کی کوئی رقم نہیں لی گئی۔ "
        "بروقت بتانے کا شکریہ۔ OpenStall دوسرے کاریگروں سے بات کر رہا ہے۔",
        kept="ٹھیک ہے: آرڈر {order_id} میں سے آپ کا حصہ آپ کے پاس ہی رہے گا۔",
        ship_by=" براہ کرم اسے {day} تک بھیج دیں۔",
    ),
    "hi": DropPhrases(
        ask="यह सुनकर दुख हुआ। क्या ऑर्डर {order_id} ({quantity} × {item}, {amount}) में से आपका हिस्सा छोड़ दिया "
        "जाए? OpenStall इसे दूसरे कारीगरों से बनवाएगा, और इसका भुगतान आपको नहीं होगा। छोड़ने के लिए \"हाँ\" "
        "लिखें, या रखने के लिए \"नहीं\"।",
        some_items="आपका सामान",
        dropped="हो गया: ऑर्डर {order_id} में से आपका हिस्सा खरीदार को वापस चला गया है, और इसके लिए कोई पैसा नहीं लिया "
        "गया। समय पर बताने के लिए धन्यवाद। OpenStall दूसरे कारीगरों से बात कर रहा है।",
        kept="ठीक है: ऑर्डर {order_id} में से आपका हिस्सा आपके पास ही रहेगा।",
        ship_by=" कृपया इसे {day} तक भेज दें।",
    ),
    "es": DropPhrases(
        ask="Lamento oírlo. ¿Quieres dejar tu parte del pedido {order_id} ({quantity} × {item}, {amount})? OpenStall "
        "pedirá a otras artesanas que la hagan, y no se te pagará por ella. Responde SÍ para dejarla, o NO para "
        "conservarla.",
        some_items="tus artículos",
        dropped="Listo: tu parte del pedido {order_id} vuelve al comprador, y no se cobra nada por ella. Gracias por "
        "avisarnos a tiempo. OpenStall está pidiendo a otras artesanas que la hagan.",
        kept="Muy bien: conservas tu parte del pedido {order_id}.",
        ship_by=" Por favor, envíala antes del {day}.",
    ),
}
assert PHRASES.keys() == LOCALES.keys(), "every template language has the drop-out words too"

# "I cannot make it", as makers write it, compared after proof.normalise (lower case, punctuation gone). Saying one only
# asks her to confirm, so a phrase caught by mistake costs one question, never her share.
CANT_MAKE_IT: tuple[str, ...] = tuple(
    normalise(phrase)
    for phrase in (
        # English
        "can't make it", "cannot make it", "can not make it", "cant make it", "can't make this order",
        "cannot make this order", "can't make the order", "can't make my order", "can't do this order",
        "can't do the order", "cannot do the order", "can't deliver", "cannot deliver", "can't finish",
        "cannot finish", "won't be able to make", "will not be able to make", "unable to make", "unable to deliver",
        "drop out", "give up my share",
        # Urdu, as a woman and as a man says it
        "نہیں بنا سکتی", "نہیں بنا سکتا", "نہیں بنا سکوں گی", "نہیں بنا سکوں گا", "نہیں بنا پاؤں گی",
        "نہیں بنا پاؤں گا", "نہیں کر سکتی", "نہیں کر سکتا", "نہیں کر سکوں گی", "نہیں کر سکوں گا", "نہیں بھیج سکتی",
        "نہیں بھیج سکتا", "نہیں بھیج سکوں گی", "نہیں بھیج سکوں گا",
        # Urdu and Hindi in Latin letters
        "nahi bana sakti", "nahin bana sakti", "nahi bana sakta", "nahin bana sakta", "nahi bana paungi",
        "nahi bana paunga", "nahi kar sakti", "nahin kar sakti", "nahi kar sakta", "nahin kar sakta",
        "nahi bhej sakti", "nahi bhej sakta",
        # Hindi, as a woman and as a man says it
        "नहीं बना सकती", "नहीं बना सकता", "नहीं बना पाऊँगी", "नहीं बना पाऊंगी", "नहीं बना पाऊँगा", "नहीं बना पाऊंगा",
        "नहीं कर सकती", "नहीं कर सकता", "नहीं कर पाऊँगी", "नहीं कर पाऊंगी", "नहीं कर पाऊँगा", "नहीं कर पाऊंगा",
        "नहीं भेज सकती", "नहीं भेज सकता", "नहीं भेज पाऊँगी", "नहीं भेज पाऊँगा",
        # Spanish
        "no puedo hacerlo", "no lo puedo hacer", "no puedo hacer el pedido", "no puedo hacer este pedido",
        "no puedo cumplir", "no voy a poder", "no puedo entregar", "no podré hacerlo",
    )
)  # fmt: skip


def cant_make_it(words: str) -> bool:
    """Whether she says she cannot make her order, in any of the demo's languages."""
    said = f" {normalise(words)} "
    return any(f" {phrase} " in said for phrase in CANT_MAKE_IT)


@dataclass(frozen=True)
class DropTurn:
    """The drop-out flow's replies, and the shares to release and re-plan once the message is committed."""

    replies: list[str]
    heal_after: list[str] = field(default_factory=list)


def drop_turn(session: Session, seller: Seller, words: str, message_id: str) -> DropTurn | None:
    """The drop-out flow's answer to her message (her words, typed and heard), or None when the message is not part of
    it. Only a share waiting for her proof of shipping can be dropped. The caller commits."""
    code = template_language(seller.language)
    waiting = [part for part in awaiting_proof(session, seller.id) if not _proving(part)]
    asked = next((part for part in waiting if state_of(part) == ASKED), None)
    if asked is not None and (is_yes(words) or is_no(words)):
        part = _locked(session, asked.id)
        if part is not None and _droppable(part) and state_of(part) == ASKED:
            return _drop(session, part, code) if is_yes(words) else _keep(session, part, code)
    if waiting and cant_make_it(words):
        part = _locked(session, waiting[0].id)
        if part is not None and _droppable(part):
            return _ask(session, part, code, words, message_id)
    return None


def state_of(part: OrderPart) -> str | None:
    return (part.drop_json or {}).get("state")


def _proving(part: OrderPart) -> bool:
    """Her courier receipt for it is in hand, waiting on her: that share is being shipped, not dropped."""
    return (part.proof_json or {}).get("state") in PENDING


def _droppable(part: OrderPart) -> bool:
    return part.status == PartStatus.AUTHORIZED and part.tracking_number is None and not _proving(part)


def _locked(session: Session, part_id: str) -> OrderPart | None:
    # Locked on Postgres, so two messages at once cannot both drop (or keep) the same share.
    return session.get(OrderPart, part_id, with_for_update=True, populate_existing=True)


def _item(part: OrderPart, code: str) -> str:
    return part.product.title if part.product else PHRASES[code].some_items


def _ask(session: Session, part: OrderPart, code: str, words: str, message_id: str) -> DropTurn:
    part.drop_json = {"state": ASKED, "asked_at": utcnow().isoformat(), "said": words.strip()[:300]}
    record_event(
        session,
        EventType.PART_DROP_ASKED,
        f"{part.seller.name} said she cannot make her share of order {part.order_id}: OpenStall asked her to confirm "
        "before releasing it",
        entity_id=part.id,
        payload={"order_id": part.order_id, "seller_id": part.seller_id, "message_id": message_id},
    )
    def compose(used: str) -> str:
        return PHRASES[used].ask.format(
            order_id=part.order_id,
            quantity=part.quantity,
            item=_item(part, used),
            amount=format_money(used, part.amount_usd),
        )

    return DropTurn([say(code, compose)])


def _keep(session: Session, part: OrderPart, code: str) -> DropTurn:
    part.drop_json = {**(part.drop_json or {}), "state": KEPT, "kept_at": utcnow().isoformat()}
    record_event(
        session,
        EventType.PART_KEPT,
        f"{part.seller.name} keeps her share of order {part.order_id} after all",
        entity_id=part.id,
        payload={"order_id": part.order_id, "seller_id": part.seller_id},
    )
    day = ship_by(part)

    def compose(used: str) -> str:
        words = PHRASES[used]
        kept = words.kept.format(order_id=part.order_id)
        return kept + (words.ship_by.format(day=format_day(used, day)) if day else "")

    return DropTurn([say(code, compose)])


def _drop(session: Session, part: OrderPart, code: str) -> DropTurn:
    part.drop_json = {**(part.drop_json or {}), "state": DROPPED, "dropped_at": utcnow().isoformat()}
    record_event(
        session,
        EventType.PART_DROPPED,
        f"{part.seller.name} dropped out of order {part.order_id}: she cannot make her {part.quantity} × "
        f"{_item(part, 'en')}. Her ${part.amount_usd:,.2f} share goes back to the buyer, and OpenStall asks the other "
        "makers for her units",
        entity_id=part.id,
        payload={
            "order_id": part.order_id,
            "seller_id": part.seller_id,
            "quantity": part.quantity,
            "amount_usd": part.amount_usd,
        },
    )
    return DropTurn([say(code, lambda used: PHRASES[used].dropped.format(order_id=part.order_id))], [part.id])


def heal_after(part_id: str, gateway: Callable[[], PaymentGateway], llm: Callable[[], LLM]) -> str | None:
    """After her yes is committed: release her share, then re-plan her units as a top-up order. Returns the top-up's id,
    or None when there is none (no other maker can make them, or her share could not be released yet). Calling it again
    changes nothing."""
    with new_session() as session:
        part = session.get(OrderPart, part_id)
        if part is None or state_of(part) != DROPPED:
            return None
        released = part.status == PartStatus.RELEASED
    if not released:
        try:
            with session_scope() as session:
                release_share(session, part_id, gateway())
        except PAYMENT_TROUBLE as trouble:
            log.warning("The dropped share %s could not be released: %s", part_id, trouble)
            return None
        deliver_fake_webhooks()  # fake mode: simulated PayPal's VOIDED confirmation follows if the hold closed
    return replan(part_id, llm)


def replan(part_id: str, llm: Callable[[], LLM], today: date | None = None) -> str | None:
    """Ask every other matching maker's agent for a dropped share's units, and draft what they offer as a top-up order
    for the order she left. Once per share: called again, it gives back the top-up already drafted."""
    today = today or quotes.clock.today()
    with new_session() as session:
        part = session.get(OrderPart, part_id, with_for_update=True, populate_existing=True)
        if part is None or state_of(part) != DROPPED or part.status != PartStatus.RELEASED:
            return None
        drop = dict(part.drop_json or {})
        order, name = part.order, part.seller.name
        if drop.get("request_id"):  # re-planned already, or stopped before its draft
            if drop.get("top_up_order_id") or drop.get("replan_failed"):
                return drop.get("top_up_order_id")
            asked_again = session.get(QuoteRequestRow, drop["request_id"])
            if asked_again is None or asked_again.completed_at is None:
                return None  # still being quoted
            return _top_up(session, part, asked_again)
        request = order.request
        why = _cannot_ask_again(request, today)
        if why is None:
            assert request is not None
            items = [item for item in request.items_json if isinstance(item, dict) and item.get("query")]
            queries = [str(item["query"]) for item in items]
            try:
                asked_again, products = create_quote_request(
                    session,
                    queries,
                    part.quantity,
                    request.max_unit_price,
                    request.deadline,
                    request.ship_to,
                    today,
                    exclude={part.seller_id},
                    asker=f"OpenStall, replacing {name} in order {order.id},",
                )
            except QuoteError as error:
                why = str(error)
        if why is not None:
            part.drop_json = {**drop, "replan_failed": why[:300]}
            record_event(
                session,
                EventType.ORDER_REPLANNED,
                f"Order {order.id} could not be re-planned without {name}: {why}",
                entity_id=order.id,
                payload={"dropped_part_id": part.id, "top_up_order_id": None, "units": 0, "needed": part.quantity},
            )
            session.commit()
            return None
        part.drop_json = {**drop, "request_id": asked_again.id}
        session.commit()  # the request is linked to her share: a second call cannot start another
        run_quote(session, asked_again, products, llm(), today)  # commits after each round
        part = session.get(OrderPart, part_id, populate_existing=True)
        assert part is not None
        return _top_up(session, part, asked_again)


def _cannot_ask_again(request: QuoteRequestRow | None, today: date) -> str | None:
    """Why her units cannot be asked for again, or None when they can."""
    if request is None:
        return "it was not drafted from a quote request, so there is no request to ask again"
    if request.deadline <= today:
        return f"its deadline, {request.deadline:%B} {request.deadline.day}, has passed"
    return None


def _top_up(session: Session, part: OrderPart, asked_again: QuoteRequestRow) -> str | None:
    """The re-plan's top-up order for the order she left, drafted from its quote, with what the feed says about it."""
    order_id, name, needed = part.order_id, part.seller.name, part.quantity
    by = f"{asked_again.deadline:%B} {asked_again.deadline.day}"
    try:
        top_up = draft_from_plan(
            session, asked_again.id, accept_partial=True, source="replan", parent_order_id=order_id
        )
    except DraftError:
        part.drop_json = {**(part.drop_json or {}), "replan_failed": "no other maker can make her units"}
        record_event(
            session,
            EventType.ORDER_REPLANNED,
            f"Order {order_id} re-planned without {name}: no other maker can make her {needed} units by {by}, so the "
            "buyer gets the rest of the order without them",
            entity_id=order_id,
            payload={"dropped_part_id": part.id, "request_id": asked_again.id, "top_up_order_id": None, "units": 0,
                     "needed": needed},
        )  # fmt: skip
        session.commit()
        return None
    units = sum(line.quantity for line in top_up.parts)
    makers = _names([line.seller.name for line in top_up.parts])
    part.drop_json = {**(part.drop_json or {}), "top_up_order_id": top_up.id}
    record_event(
        session,
        EventType.TOPUP_CREATED,
        f"Top-up order {top_up.id} for order {order_id}: {units} units from {makers}, ${top_up.total_usd:,.2f}, "
        "waiting for the buyer's approval",
        entity_id=top_up.id,
        payload={
            "parent_order_id": order_id,
            "replaces_part_id": part.id,
            "units": units,
            "total_usd": top_up.total_usd,
            "approval_url": approval_url(top_up.id),
        },
    )
    covered = f"all {needed} units" if units >= needed else f"{units} of the {needed} units"
    short = "" if units >= needed else f"; no one else can make the rest by {by}"
    record_event(
        session,
        EventType.ORDER_REPLANNED,
        f"Order {order_id} re-planned without {name}: {makers} can make {covered} she dropped, in top-up order "
        f"{top_up.id}{short}",
        entity_id=order_id,
        payload={
            "dropped_part_id": part.id,
            "request_id": asked_again.id,
            "top_up_order_id": top_up.id,
            "units": units,
            "needed": needed,
        },
    )
    session.commit()
    return top_up.id


def _names(names: list[str]) -> str:
    """"Noor", "Noor and Priya", "Amina, Noor and Priya"."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def drop_out(drop: dict[str, Any] | None) -> dict[str, Any] | None:
    """Her drop-out as the order pages show it: asked, kept or dropped, when, and the top-up that replaced her."""
    if not drop or drop.get("state") not in (ASKED, KEPT, DROPPED):
        return None
    return {
        "state": drop["state"],
        "asked_at": drop.get("asked_at"),
        "dropped_at": drop.get("dropped_at"),
        "top_up_order_id": drop.get("top_up_order_id"),
        "replan_failed": drop.get("replan_failed"),
    }
