"""Messages to makers in their own language: which language a maker gets, and dates and money as it writes them.

Code writes every message to a maker from templates (notices.py, proof.py), never a model, because they carry
numbers she acts on. The demo's languages have templates: English, Urdu, Hindi and Spanish. Any other language gets
English, and the feed says so. Numbers stay in Western digits, as most WhatsApp users in Pakistan and India type them.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Locale:
    """How one language writes dates and money."""

    name: str  # in English, for the feed: "Urdu"
    months: tuple[str, ...]
    day: str  # {day}, {month}, {year}
    money: str = "${value}"


LOCALES: dict[str, Locale] = {
    "en": Locale(
        name="English",
        months=(
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ),
        day="{month} {day}, {year}",
    ),
    "ur": Locale(
        name="Urdu",
        months=(
            "جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون",
            "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر",
        ),
        day="{day} {month} {year}",
        money="{value} ڈالر",  # as Urdu writes it; a "$" in right-to-left text lands after the number
    ),
    "hi": Locale(
        name="Hindi",
        months=(
            "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
            "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
        ),
        day="{day} {month} {year}",
    ),
    "es": Locale(
        name="Spanish",
        months=(
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ),
        day="{day} de {month} de {year}",
        money="US${value}",  # "$" alone reads as pesos in Mexico
    ),
}
LANGUAGE_NAMES = {code: locale.name for code, locale in LOCALES.items()}
DEFAULT_LANGUAGE = "en"


def template_language(language: str | None) -> str:
    """The template for her language (ISO 639-1, region ignored), or English when there is none."""
    code = (language or "").split("-", 1)[0].strip().lower()
    return code if code in LOCALES else DEFAULT_LANGUAGE


def format_money(code: str, value: Decimal) -> str:
    """"$216.00", "216.00 ڈالر" or "US$216.00", for a template language."""
    return LOCALES[code].money.format(value=f"{value:,.2f}")


def format_day(code: str, value: date) -> str:
    """"December 5, 2026", "5 دسمبر 2026" or "5 de diciembre de 2026", for a template language."""
    locale = LOCALES[code]
    return locale.day.format(day=value.day, month=locale.months[value.month - 1], year=value.year)


def language_words(used: str, requested: str | None) -> str:
    """The language she was written to in, for the feed: "Urdu", or "English (no template for 'bn' yet)"."""
    asked = (requested or "").split("-", 1)[0].strip().lower()
    if asked and asked != used:
        return f"{LANGUAGE_NAMES[used]} (no template for {requested!r} yet)"
    return LANGUAGE_NAMES[used]
