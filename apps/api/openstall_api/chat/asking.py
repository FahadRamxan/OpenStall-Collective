"""Asking her for what her listing is missing, and for her limits (spec 3.1 step 4, and the seller policy in 3.3), in
her language.

While her listing is drafted, each answer ends with one short question: the first thing still missing, in ASK_ORDER
(a photo first, since one photo fills in most of a listing; then the spec's fields in its order), then her limits once
the listing is whole: the lowest price she would take for one, and the fewest days she needs to make an order. Her
seller agent keeps to those (spec 3.3); her weekly capacity comes from the listing, and her largest discount follows
from her price and her lowest price (prompt 19).

Code writes every message to a maker from templates, never a model (wording.py): these carry the numbers she is paid
on. The question asked is kept on her draft (`asked`), and each message she sends while it is open is kept as its
answer (`answers`), so the reader is told what each of her words answers: a bare "9" means nothing without its
question.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openstall_agents.listing_reader import QUESTIONS as IN_ENGLISH
from openstall_api.wording import LOCALES, format_money, say

# The listing's fields in the spec's order (3.1, "Required listing fields"), then her limits (3.3).
LISTING_FIELDS = (
    "title",
    "description",
    "category",
    "variants",
    "price_usd",
    "capacity_per_week",
    "ship_days",
    "ship_from_city",
    "photos",
)
LIMITS = ("floor_price_usd", "min_lead_days")
# The order she is asked in: a photo first, then the spec's order, then her limits (the reader's QUESTIONS).
ASK_ORDER = tuple(IN_ENGLISH)

# One short question per field and limit, in each template language. Urdu and Hindi verbs carry the speaker's gender,
# and a maker may be a man, so each question is put so that it fits anyone: the verb agrees with the item or the
# parcel, never with the maker (test_wording_fits checks every template). Spanish speaks to her with "tú".
QUESTIONS: dict[str, Mapping[str, str]] = {
    "en": IN_ENGLISH,
    "ur": {
        "photos": "براہِ کرم اس کی ایک تصویر بھیجیں۔",
        "title": "آپ کی بنائی ہوئی چیز کیا ہے؟ چند لفظوں میں بتائیں۔",
        "description": "اس کے بارے میں تھوڑا اور بتائیں: یہ کس چیز سے بنا ہے، اس کا سائز کیا ہے، اور یہ کیسے بنایا "
        "جاتا ہے؟",
        "category": "یہ کس قسم کی چیز ہے؟",
        "variants": "یہ کن رنگوں یا ڈیزائنوں میں بن سکتا ہے؟",
        "price_usd": "ایک عدد کی قیمت کتنے امریکی ڈالر ہے؟",
        "capacity_per_week": "ایک ہفتے میں کتنے تیار ہو سکتے ہیں؟",
        "ship_days": "آپ کا پارسل امریکہ میں خریدار تک کتنے دن میں پہنچتا ہے؟",
        "ship_from_city": "پارسل کس شہر سے بھیجا جائے گا؟",
        "floor_price_usd": "بڑے آرڈر میں ایک عدد کی کم سے کم قیمت کتنی ہو سکتی ہے، امریکی ڈالر میں؟",
        "min_lead_days": "آرڈر تیار کرنے کے لیے آپ کو کم سے کم کتنے دن چاہئیں؟",
    },
    "hi": {
        "photos": "कृपया इसकी एक फ़ोटो भेजें।",
        "title": "आपकी बनाई हुई चीज़ क्या है? कुछ शब्दों में बताएँ।",
        "description": "इसके बारे में थोड़ा और बताएँ: यह किस चीज़ से बना है, इसका नाप क्या है, और यह कैसे बनाया "
        "जाता है?",
        "category": "यह किस तरह की चीज़ है?",
        "variants": "यह किन रंगों या डिज़ाइनों में बन सकता है?",
        "price_usd": "एक पीस की कीमत कितने अमेरिकी डॉलर है?",
        "capacity_per_week": "एक हफ़्ते में कितने तैयार हो सकते हैं?",
        "ship_days": "आपका पार्सल अमेरिका में खरीदार तक कितने दिनों में पहुँचता है?",
        "ship_from_city": "पार्सल किस शहर से भेजा जाएगा?",
        "floor_price_usd": "बड़े ऑर्डर में एक पीस की कम से कम कीमत कितनी हो सकती है, अमेरिकी डॉलर में?",
        "min_lead_days": "ऑर्डर तैयार करने के लिए आपको कम से कम कितने दिन चाहिए?",
    },
    "es": {
        "photos": "Por favor, mándame una foto.",
        "title": "¿Qué haces? Dímelo en pocas palabras.",
        "description": "Cuéntame un poco más: de qué material es, qué tamaño tiene y cómo lo haces.",
        "category": "¿Qué tipo de artículo es?",
        "variants": "¿En qué colores o estilos lo haces?",
        "price_usd": "¿Cuál es tu precio por cada uno, en dólares estadounidenses?",
        "capacity_per_week": "¿Cuántos puedes hacer en una semana?",
        "ship_days": "¿Cuántos días tarda tu paquete en llegar a un comprador en Estados Unidos?",
        "ship_from_city": "¿Desde qué ciudad lo envías?",
        "floor_price_usd": "Para un pedido grande, ¿cuál es el precio más bajo que aceptarías por cada uno, en dólares "
        "estadounidenses?",
        "min_lead_days": "¿Cuántos días necesitas como mínimo para preparar un pedido?",
    },
}


@dataclass(frozen=True)
class Parts:
    """How one language tells her listing back to her. Each part takes its facts by name."""

    each: str  # {price}
    week: str  # {n}
    arrives: str  # {n}
    ships_from: str  # {city}
    lowest: str  # {price}
    lead: str  # {n}
    unnamed: str  # the title, before there is one
    joiner: str
    so_far: str  # {listing}
    summary: str  # {listing}: everything, once nothing is left to ask
    confirm: str  # her yes, asked for
    live: str  # {link}: her stall, once her yes published it
    still_live: str  # {link}: her answer once she is live
    thanks: str


PARTS: dict[str, Parts] = {
    "en": Parts(
        each="{price} each",
        week="{n} a week",
        arrives="arrives in {n} days",
        ships_from="from {city}",
        lowest="lowest {price} for a big order",
        lead="{n} days to make an order",
        unnamed="your item, not named yet",
        joiner=", ",
        so_far="Your listing so far: {listing}.",
        summary="Here is your listing: {listing}.",
        confirm="Reply YES to publish it, or tell me what to change.",
        live="Your listing is live! AI shopping agents can find it now. Your stall: {link}",
        still_live="Your listing is live: {link}",
        thanks="Thank you.",
    ),
    "ur": Parts(
        each="{price} فی عدد",
        week="ہفتے میں {n}",
        arrives="{n} دن میں پہنچتا ہے",
        ships_from="{city} سے",
        lowest="بڑے آرڈر پر کم سے کم {price}",
        lead="آرڈر تیار کرنے میں {n} دن",
        unnamed="آپ کی چیز، جس کا نام ابھی باقی ہے",
        joiner="، ",
        # "اشتہار", the everyday word for an online ad, not "لسٹنگ": the voice read that English word as "listening".
        so_far="اب تک آپ کا اشتہار: {listing}۔",
        summary="یہ رہا آپ کا اشتہار: {listing}۔",
        confirm='اشتہار لگانے کے لیے "ہاں" لکھیں، یا بتائیں کہ کیا بدلنا ہے۔',
        live="آپ کا اشتہار لگ گیا ہے! اب اے آئی شاپنگ ایجنٹ اسے ڈھونڈ سکتے ہیں۔ آپ کی دکان: {link}",
        still_live="آپ کا اشتہار لگا ہوا ہے: {link}",
        thanks="شکریہ۔",
    ),
    "hi": Parts(
        each="{price} प्रति पीस",
        week="हफ़्ते में {n}",
        arrives="{n} दिन में पहुँचता है",
        ships_from="{city} से",
        lowest="बड़े ऑर्डर पर कम से कम {price}",
        lead="ऑर्डर तैयार करने में {n} दिन",
        unnamed="आपकी चीज़, नाम अभी बाकी है",
        joiner=", ",
        so_far="आपकी लिस्टिंग अब तक: {listing}।",
        summary="यह आपकी लिस्टिंग है: {listing}।",
        confirm='इसे प्रकाशित करने के लिए "हाँ" लिखें, या बताएँ क्या बदलना है।',
        live="आपकी लिस्टिंग अब लाइव है! AI शॉपिंग एजेंट अब इसे ढूँढ सकते हैं। आपकी दुकान: {link}",
        still_live="आपकी लिस्टिंग लाइव है: {link}",
        thanks="धन्यवाद।",
    ),
    "es": Parts(
        each="{price} cada uno",
        week="{n} por semana",
        arrives="llega en {n} días",
        ships_from="desde {city}",
        lowest="mínimo {price} en un pedido grande",
        lead="{n} días para preparar un pedido",
        unnamed="tu artículo, aún sin nombre",
        joiner=", ",
        so_far="Tu anuncio hasta ahora: {listing}.",
        summary="Este es tu anuncio: {listing}.",
        confirm="Responde SÍ para publicarlo, o dime qué cambiar.",
        live="¡Tu anuncio ya está publicado! Los agentes de compra con IA ya pueden encontrarlo. Tu puesto: {link}",
        still_live="Tu anuncio está publicado: {link}",
        thanks="¡Gracias!",
    ),
}
assert QUESTIONS.keys() == PARTS.keys() == LOCALES.keys(), "every template language asks in its own words"
assert all(tuple(asked) == ASK_ORDER for asked in QUESTIONS.values()), "every language asks every question, in order"


def given(value: object) -> bool:
    """Whether a draft field has a value: any number is one; an empty text or list is not."""
    return value is not None and value != "" and value != []


def still_to_ask(draft: Mapping[str, Any]) -> list[str]:
    """What is left to ask her, in the order she is asked."""
    missing = set(draft.get("missing", ()))
    return [name for name in ASK_ORDER if name in missing]


def described(draft: Mapping[str, Any], language: str = "en") -> str:
    """Her listing and limits so far in a few words, in a template language: "Hand-embroidered cushion cover, $18.00
    each, 4 a week, arrives in 9 days, from Lahore". In her language the item is named in it too (`title_local`, which
    the listing reader writes beside the English title), so an Urdu message, and its spoken copy, carries no English
    title; the listing's own title stays in English, as buyers' agents read it."""
    parts = PARTS[language]
    local = draft.get("title_local") if language != "en" else None
    pieces = [str(local or draft.get("title") or parts.unnamed)]
    if given(draft.get("price_usd")):
        pieces.append(parts.each.format(price=format_money(language, Decimal(str(draft["price_usd"])))))
    if given(draft.get("capacity_per_week")):
        pieces.append(parts.week.format(n=draft["capacity_per_week"]))
    if given(draft.get("ship_days")):
        pieces.append(parts.arrives.format(n=draft["ship_days"]))
    if given(draft.get("ship_from_city")):
        pieces.append(parts.ships_from.format(city=draft["ship_from_city"]))
    if given(draft.get("floor_price_usd")):
        pieces.append(parts.lowest.format(price=format_money(language, Decimal(str(draft["floor_price_usd"])))))
    if given(draft.get("min_lead_days")):
        pieces.append(parts.lead.format(n=draft["min_lead_days"]))
    return parts.joiner.join(pieces)


def asking_reply(draft: Mapping[str, Any], language: str, *, thanks: bool) -> str:
    """Her answer while her listing is drafted, in a template language: thanks (not for her first message, which is
    welcomed instead), then her listing so far and the one question open now (`asked`); or, once nothing is left to
    ask, all of it and a request for her yes (spec 3.1 step 5). It carries its English line (wording.say)."""
    asked = draft.get("asked")

    def compose(code: str) -> str:
        parts = PARTS[code]
        listing = described(draft, code)
        if asked:
            text = f"{parts.so_far.format(listing=listing)} {QUESTIONS[code][asked]}"
        else:
            text = f"{parts.summary.format(listing=listing)} {parts.confirm}"
        return f"{parts.thanks} {text}" if thanks else text

    return say(language, compose)


def live_reply(language: str, link: str, *, again: bool = False) -> str:
    """In a template language: her listing is live, with her stall's link; `again`, for a message once it is."""

    def compose(code: str) -> str:
        parts = PARTS[code]
        return f"{parts.thanks} {parts.still_live.format(link=link)}" if again else parts.live.format(link=link)

    return say(language, compose)
