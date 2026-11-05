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
from openstall_api.wording import LOCALES, format_money

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

# One short question per field and limit, in each template language. Urdu and Hindi speak to her with the feminine
# forms, and Spanish with "tú", as every message to a maker does (notices.py).
QUESTIONS: dict[str, Mapping[str, str]] = {
    "en": IN_ENGLISH,
    "ur": {
        "photos": "براہِ کرم اس کی ایک تصویر بھیجیں۔",
        "title": "آپ کیا بناتی ہیں؟ چند لفظوں میں بتائیں۔",
        "description": "اس کے بارے میں تھوڑا اور بتائیں: یہ کس چیز سے بنا ہے، اس کا سائز کیا ہے، اور آپ اسے کیسے "
        "بناتی ہیں؟",
        "category": "یہ کس قسم کی چیز ہے؟",
        "variants": "آپ یہ کن رنگوں یا ڈیزائنوں میں بناتی ہیں؟",
        "price_usd": "ایک کی قیمت کتنے امریکی ڈالر ہے؟",
        "capacity_per_week": "آپ ایک ہفتے میں کتنے بنا سکتی ہیں؟",
        "ship_days": "آپ کا پارسل امریکہ میں خریدار تک کتنے دن میں پہنچتا ہے؟",
        "ship_from_city": "آپ کس شہر سے بھیجتی ہیں؟",
        "floor_price_usd": "بڑے آرڈر کے لیے آپ ایک کی کم سے کم کتنی قیمت لیں گی، امریکی ڈالر میں؟",
        "min_lead_days": "آرڈر تیار کرنے کے لیے آپ کو کم سے کم کتنے دن چاہئیں؟",
    },
    "hi": {
        "photos": "कृपया इसकी एक फ़ोटो भेजें।",
        "title": "आप क्या बनाती हैं? कुछ शब्दों में बताएँ।",
        "description": "इसके बारे में थोड़ा और बताएँ: यह किस चीज़ से बना है, इसका नाप क्या है, और आप इसे कैसे "
        "बनाती हैं?",
        "category": "यह किस तरह की चीज़ है?",
        "variants": "आप इसे किन रंगों या डिज़ाइनों में बनाती हैं?",
        "price_usd": "एक की कीमत कितने अमेरिकी डॉलर है?",
        "capacity_per_week": "आप एक हफ़्ते में कितने बना सकती हैं?",
        "ship_days": "आपका पार्सल अमेरिका में खरीदार तक कितने दिनों में पहुँचता है?",
        "ship_from_city": "आप किस शहर से भेजती हैं?",
        "floor_price_usd": "बड़े ऑर्डर के लिए आप एक की कम से कम कितनी कीमत लेंगी, अमेरिकी डॉलर में?",
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
    all_set: str
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
        all_set="That is everything your listing needs.",
        thanks="Thank you.",
    ),
    "ur": Parts(
        each="{price} فی عدد",
        week="ہفتے میں {n}",
        arrives="{n} دن میں پہنچتا ہے",
        ships_from="{city} سے",
        lowest="بڑے آرڈر پر کم سے کم {price}",
        lead="آرڈر تیار کرنے میں {n} دن",
        unnamed="آپ کی چیز، نام ابھی باقی ہے",
        joiner="، ",
        so_far="آپ کی لسٹنگ اب تک: {listing}۔",
        all_set="آپ کی لسٹنگ کے لیے سب کچھ مل گیا ہے۔",
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
        all_set="आपकी लिस्टिंग के लिए सब कुछ मिल गया है।",
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
        all_set="Ya tengo todo lo que necesita tu anuncio.",
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
    each, 4 a week, arrives in 9 days, from Lahore". The title stays in English: buyers' agents read it."""
    parts = PARTS[language]
    pieces = [str(draft.get("title") or parts.unnamed)]
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
    welcomed instead), her listing so far, then the one question open now (`asked`), or that nothing is left to ask."""
    parts = PARTS[language]
    asked = draft.get("asked")
    ending = QUESTIONS[language][asked] if asked else parts.all_set
    text = f"{parts.so_far.format(listing=described(draft, language))} {ending}"
    return f"{parts.thanks} {text}" if thanks else text
