"""Demand Radar (spec 3.8, prompt 44): searches that found nothing, grouped, counted for the week, and matched to a
maker who could make them, with a tip she is sent in her language.

1. Every search with no results is already logged (search.py).
2. They are grouped by their words: lower case, without words that say nothing about the item ("handmade", "set of"),
   plural and singular alike ("mugs" is "mug"). Two searches share a group when at least half their words are the same.
   Searches this short need no embeddings, and the grouping can be checked by hand; test and sandbox mode group alike.
3. Each group is counted over the last 7 days. Seeded demo searches (seed_radar_searches) count too, and are marked.
4. A group is matched to the live maker whose listings share the most of its describing words (her craft:
   "embroidered"), not counting the item itself ("runner" in "table runners"); the most trusted first on a tie. A group
   no maker shares a word with has no one to tip.
5. The dashboard shows every group; a group's tip goes to its maker, on her chat, in her language, once a week.
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_api.chat.outbox import send_to_seller
from openstall_api.db import new_session, session_scope
from openstall_api.events import EventType, record_event
from openstall_api.messaging import Messenger
from openstall_api.models import DataSource, Event, Passport, Product, ProductStatus, Search, Seller, utcnow
from openstall_api.wording import LOCALES, language_words, say, template_language
from openstall_trust import trust_score

WEEK = timedelta(days=7)
SEEDED = DataSource.SEEDED_DEMO.value

# Words that say nothing about the item an agent wants.
FILLER = frozenset(
    {
        "a", "an", "the", "for", "of", "and", "or", "with", "in", "to", "from", "by", "on", "my", "some", "set",
        "pack", "piece", "handmade", "hand", "made", "custom", "cheap", "best", "buy", "new", "unique", "bulk",
    }
)  # fmt: skip


def singular(word: str) -> str:
    """"mugs" is "mug", "runners" "runner", "boxes" "box", "doilies" "doily"; "glass" stays."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def item_words(text: str) -> list[str]:
    """The words of a search that describe the item, in order, each once."""
    found = [singular(word) for word in re.findall(r"[^\W\d_]+", text.lower()) if word not in FILLER and len(word) > 1]
    return list(dict.fromkeys(found))


def same_item(a: frozenset[str], b: frozenset[str]) -> bool:
    """At least half of the two searches' words are shared."""
    return bool(a and b) and len(a & b) * 2 >= len(a | b)


class RadarMaker(BaseModel):
    """The maker a group's tip goes to: her listing shares its describing words."""

    seller_id: str
    name: str
    product_title: str
    shared: list[str]  # the words her listing shares with the group


class RadarGroup(BaseModel):
    """One group of searches that found nothing, this week."""

    key: str  # its words, sorted and joined: stable from week to week
    label: str  # the search as agents typed it most often
    searches: int
    seeded: int  # how many of them are seeded demo searches
    queries: list[str]  # what agents typed, most often first
    last_searched_at: datetime
    maker: RadarMaker | None
    tip: str  # the dashboard's words
    tipped_at: datetime | None  # when its maker was sent the tip this week


@dataclass
class _Group:
    words: frozenset[str]
    rows: list[Search]


def radar(session: Session, now: datetime | None = None) -> list[RadarGroup]:
    """This week's groups of searches that found nothing, the most searched first."""
    now = now or utcnow()
    rows = session.scalars(
        select(Search)
        .where(Search.result_count == 0, Search.created_at >= now - WEEK)
        .order_by(Search.created_at, Search.id)
    ).all()
    groups: list[_Group] = []
    for row in rows:
        words = frozenset(item_words(row.query))
        if not words:
            continue
        group = next((group for group in groups if same_item(group.words, words)), None)
        if group is None:
            groups.append(_Group(words, [row]))
        else:
            group.rows.append(row)
    makers = _makers(session)
    tipped = _tipped(session, now)
    out = [_group_out(group, makers, tipped) for group in groups]
    return sorted(out, key=lambda group: (-group.searches, group.label))


@dataclass(frozen=True)
class _Maker:
    seller_id: str
    name: str
    product_title: str
    words: frozenset[str]
    score: float


def _makers(session: Session) -> list[_Maker]:
    """Every live listing's maker, with its words and her trust score."""
    makers = []
    for product in session.scalars(select(Product).where(Product.status == ProductStatus.LIVE).order_by(Product.id)):
        passport = session.get(Passport, product.seller_id)
        metrics = passport.metrics_json if passport else None
        score = (
            trust_score(metrics["on_time_rate"], metrics["dispute_rate"], metrics["photo_originality"])
            if metrics
            else 0
        )
        words = frozenset(item_words(f"{product.title} {product.category or ''}"))
        makers.append(_Maker(product.seller_id, product.seller.name, product.title, words, float(score)))
    return makers


def _tipped(session: Session, now: datetime) -> dict[str, datetime]:
    """When each group's tip was sent this week, by its key."""
    events = session.scalars(
        select(Event).where(Event.type == EventType.RADAR_TIP_SENT.value, Event.created_at >= now - WEEK)
    )
    return {event.entity_id: event.created_at for event in events if event.entity_id}


def _group_out(group: _Group, makers: Sequence[_Maker], tipped: dict[str, datetime]) -> RadarGroup:
    typed = Counter(" ".join(row.query.lower().split()) for row in group.rows)
    label = min(typed, key=lambda query: (-typed[query], len(query), query))
    ordered = item_words(label) or sorted(group.words)
    key = "-".join(sorted(ordered))[:64]
    describing = frozenset(ordered[:-1])  # the item itself ("mug", "runner") is the last word
    best = max(
        (maker for maker in makers if maker.words & describing),
        key=lambda maker: (len(maker.words & describing), maker.score, maker.name),
        default=None,
    )
    count = len(group.rows)
    words = f"{count} {'agent' if count == 1 else 'agents'} searched for {label} this week. Nobody sells them."
    maker = None
    if best is not None:
        shared = sorted(best.words & describing)
        maker = RadarMaker(
            seller_id=best.seller_id, name=best.name, product_title=best.product_title, shared=shared
        )
        words += f" {best.name} makes {best.product_title.lower()}: she could."
    return RadarGroup(
        key=key,
        label=label,
        searches=count,
        seeded=sum(1 for row in group.rows if (row.filters_json or {}).get("data_source") == SEEDED),
        queries=[query for query, _ in typed.most_common(5)],
        last_searched_at=max(row.created_at for row in group.rows),
        maker=maker,
        tip=words,
        tipped_at=tipped.get(key),
    )


@dataclass(frozen=True)
class TipPhrases:
    tip: str  # {count}, {label}, {item}


PHRASES: dict[str, TipPhrases] = {
    "en": TipPhrases(
        "OpenStall Demand Radar: {count} buyers' agents looked for “{label}” this week, and nobody on OpenStall sells "
        "it. You make {item}: could you make this too? Reply and tell us."
    ),
    "ur": TipPhrases(
        "OpenStall ڈیمانڈ ریڈار: اس ہفتے {count} خریداروں کے ایجنٹوں نے “{label}” تلاش کیا، اور OpenStall پر کوئی اسے "
        "نہیں بیچتا۔ آپ {item} بناتی ہیں: کیا آپ یہ بھی بنا سکتی ہیں؟ جواب دے کر ہمیں بتائیں۔"
    ),
    "hi": TipPhrases(
        "OpenStall डिमांड रडार: इस हफ़्ते {count} खरीदारों के एजेंटों ने “{label}” खोजा, और OpenStall पर इसे कोई नहीं "
        "बेचता। आप {item} बनाती हैं: क्या आप यह भी बना सकती हैं? जवाब देकर हमें बताएँ।"
    ),
    "es": TipPhrases(
        "Radar de demanda de OpenStall: esta semana {count} agentes de compradores buscaron “{label}”, y nadie en "
        "OpenStall lo vende. Tú haces {item}: ¿podrías hacer esto también? Responde y cuéntanos."
    ),
}
assert PHRASES.keys() == LOCALES.keys(), "every template language has the Radar tip too"


class TipError(ValueError):
    """The tip cannot be sent. The message says why."""


def send_tip(key: str, messenger: Callable[[], Messenger], now: datetime | None = None) -> RadarGroup:
    """Send a group's tip to its maker, in her language, where she chats with OpenStall: once a week per group. Raises
    TipError when there is no such group this week, no maker to tip, or she could not be reached."""
    with new_session() as session:
        group = next((group for group in radar(session, now) if group.key == key), None)
        if group is None:
            raise TipError(f"No searches for {key!r} found nothing this week.")
        if group.tipped_at is not None:
            return group
        if group.maker is None:
            raise TipError(f"No maker on OpenStall makes anything like “{group.label}” yet, so there is no one to tip.")
        seller = group.maker
        maker = session.get(Seller, seller.seller_id)
        assert maker is not None
        code = template_language(maker.language)
        said_in = language_words(code, maker.language)
    item = seller.product_title.lower()
    text = say(code, lambda used: PHRASES[used].tip.format(count=group.searches, label=group.label, item=item))
    summary = f"{seller.name} was tipped {{where}}, in {said_in}, that {group.searches} agents looked for {group.label}"
    if not send_to_seller(seller.seller_id, text, summary, messenger, payload={"kind": "radar_tip", "group": key}):
        raise TipError(f"{seller.name} could not be reached, so the tip was not sent.")
    with session_scope() as session:
        record_event(
            session,
            EventType.RADAR_TIP_SENT,
            f"Demand Radar: {seller.name} was tipped that {group.searches} agents searched for {group.label} this week",
            entity_id=key,
            payload={"seller_id": seller.seller_id, "searches": group.searches, "label": group.label},
        )
    with new_session() as session:
        return next(group for group in radar(session, now) if group.key == key)


# The seeded demo world's searches that found nothing this week (spec section 2, step 13: "23 agents searched for
# ceramic mugs this week. Nobody sells them."), with how many times each was typed. Marked seeded_demo.
SEEDED_SEARCHES: tuple[tuple[str, int], ...] = (
    ("ceramic mugs", 10),
    ("handmade ceramic mug", 6),
    ("ceramic coffee mugs", 4),
    ("set of ceramic mugs", 3),
    ("embroidered table runner", 5),
    ("hand embroidered table runners", 4),
    ("block print napkins", 3),
    ("beeswax candles", 2),
)


def seed_radar_searches(session: Session, now: datetime | None = None) -> int:
    """The seeded searches, spread over the last six days. The caller commits. Returns how many were added."""
    now = now or utcnow()
    added = 0
    for query, times in SEEDED_SEARCHES:
        for index in range(times):
            moment = now - timedelta(hours=6 + (added * 7) % 140, minutes=index)
            session.add(
                Search(query=query, filters_json={"data_source": SEEDED}, result_count=0, created_at=moment)
            )
            added += 1
    return added
