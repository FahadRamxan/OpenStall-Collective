"""Search over the live listings for buyer agents (spec 3.2, search_products), and the search log (spec 3.8 step 1).

Words are matched in each listing's title, description, category and colours. A listing is found when it has at
least half of the query's words and one of them is in its title or category, so a colour or a description word alone
("red" in "red ceramic mugs") finds nothing. A word the listing has scores above one it only starts with ("cush" in
"cushion"), and ties go to the lower price. Plain Python is plenty at this catalog's size, and keeps SQLite and
Postgres alike. Every search is logged with its filters and how many results it found, so the searches that find
nothing show demand no maker meets yet.
"""

import json
import logging
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from openstall_allocator import CENT, Clock, SystemClock
from openstall_api.catalog import ProductListing, live_products
from openstall_api.events import EventType, jsonable, record_event
from openstall_api.models import Passport, Product, Search
from openstall_api.offer_rules import PolicyError, capacity_by_deadline, committed_units, default_deadline

log = logging.getLogger(__name__)

# Where "today" comes from: UTC, like the offer rules. Tests fix it with a FixedClock.
clock: Clock = SystemClock()

EXACT = 2  # points for a query word the listing has
PREFIX = 1  # points for a query word that only starts one of the listing's words
MIN_PREFIX = 3  # a shorter query word must match a whole word
MAX_RESULTS = 50

# Words too common to say what a buyer wants: without them, "mugs with handles" would match every description.
STOP_WORDS = frozenset(
    "a an and any are as at be by can each for from have i in into is it its me my need needs of on or our per "
    "please some than that the their them these they this those to up us want wants we with you your".split()
)


class SearchError(ValueError):
    """A search that cannot run, said so the agent can fix it."""


@dataclass(frozen=True)
class SearchFilters:
    """What the buyer agent asked for besides the words. None means not given."""

    max_price: Decimal | None = None
    quantity: int | None = None
    deadline: date | None = None
    ship_to: str | None = None

    def given(self) -> dict[str, Any]:
        """The filters the agent gave, for the search log: the price as an exact string, the date as YYYY-MM-DD."""
        return {name: jsonable(value) for name, value in asdict(self).items() if value is not None}


class SearchResult(ProductListing):
    """A listing that search_products found, with how many its maker can still supply by the deadline."""

    capacity_by_deadline: int = Field(
        description="Units she can still make and ship by `deadline`: her production time and the ship days, less "
        "the units of orders she already has reserved. 0 when `deadline` is sooner than the notice she needs (her "
        "minimum lead days)."
    )
    deadline: date = Field(
        description="The date capacity_by_deadline counts to: the deadline searched for, or 30 days from today (UTC)."
    )


def _tokens(text: str) -> list[str]:
    """Lower-case words without accents ("Cojín" becomes "cojin"). Other marks stay inside their word."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    kept = "".join(char for char in folded if not unicodedata.combining(char))
    return "".join(char if char.isalnum() or unicodedata.category(char)[0] == "M" else " " for char in kept).split()


def _singular(word: str) -> str:
    """'covers' to 'cover', 'boxes' to 'box', 'accessories' to 'accessory'; 'glass' and 'dress' stay as they are."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def query_words(query: str) -> set[str]:
    """The words of a query that say what is wanted: no stop words, single letters or bare numbers ("40")."""
    tokens = _tokens(query)
    return {_singular(token) for token in tokens if len(token) > 1 and token not in STOP_WORDS and not token.isdigit()}


@dataclass(frozen=True)
class ListingWords:
    """A listing's words: its title and category name what it is; its description and colours say more about it."""

    names: frozenset[str]
    details: frozenset[str]


def _words(text: str) -> frozenset[str]:
    return frozenset(_singular(token) for token in _tokens(text))


def listing_words(product: Product) -> ListingWords:
    """Every word of a listing's title and category, and of its description and colours."""
    return ListingWords(
        names=_words(f"{product.title} {product.category}"),
        details=_words(" ".join([product.description, *product.variants_json])),
    )


def words_needed(count: int) -> int:
    """How many of a query's words a listing must have: at least half of them.

    Half rather than all, so a whole request such as "40 hand-embroidered cushion covers for corporate gifts" (6
    words) still finds a cover that has 3 of them.
    """
    return (count + 1) // 2


def _points(word: str, words: frozenset[str]) -> int:
    """EXACT if the word is one of `words`, PREFIX if it only starts one of them (from MIN_PREFIX letters), else 0."""
    if word in words:
        return EXACT
    if len(word) >= MIN_PREFIX and any(other.startswith(word) for other in words):
        return PREFIX
    return 0


def match_score(wanted: set[str], listing: ListingWords) -> int:
    """The listing's score for the query's words, or 0 when it does not match.

    It matches when it has at least words_needed of them and one of those is in its title or category: a colour or a
    description word alone ("red" in "red ceramic mugs", "cotton" in "cotton tote bags") never finds a listing, it
    only ranks one. Each word scores EXACT where the listing has it, or PREFIX where it only starts one of its words.
    """
    score = matched = 0
    named = False
    for word in wanted:
        in_name = _points(word, listing.names)
        points = max(in_name, _points(word, listing.details))
        if points:
            matched += 1
            score += points
            named = named or in_name > 0
    return score if named and matched >= words_needed(len(wanted)) else 0


def find_products(session: Session, query: str, filters: SearchFilters, today: date) -> list[SearchResult]:
    """Live listings that match the query and pass the filters, best match first, then the lower price.

    Capacity comes from the offer rules (offer_rules.py), counted to the deadline asked for or to today + 30 days.
    With a deadline or a quantity, makers who can make none in time are left out, including those who need more
    notice than the deadline gives. Ship days are used as they are, whatever ship_to says: for now they are days to a
    US city. This only reads.
    """
    if filters.deadline is not None and filters.deadline <= today:
        raise SearchError(f"The deadline {filters.deadline.isoformat()} must be after today, {today.isoformat()} (UTC).")
    wanted = query_words(query)
    if not wanted:
        return []
    matches: list[tuple[int, Product]] = []
    for product in live_products(session):
        if filters.max_price is not None and product.price_usd > filters.max_price:
            continue
        score = match_score(wanted, listing_words(product))
        if score:
            matches.append((score, product))
    matches.sort(key=lambda match: (-match[0], match[1].price_usd, match[1].id))

    deadline = filters.deadline or default_deadline(today)
    committed = committed_units(session, (product.seller_id for _, product in matches))
    passports = {
        passport.seller_id: passport
        for passport in session.scalars(select(Passport).where(Passport.seller_id.in_(list(committed))))
    }
    in_time_only = filters.deadline is not None or filters.quantity is not None
    results: list[SearchResult] = []
    for _, product in matches:
        try:
            capacity = capacity_by_deadline(product, today, deadline, committed[product.seller_id])
        except PolicyError as error:
            # She cannot be quoted either; published listings always have a policy (prompt 19), so this is a bug.
            log.warning("listing %s is left out of search: %s", product.id, error)
            continue
        if in_time_only and capacity == 0:
            continue
        results.append(
            SearchResult.of(
                product, passports.get(product.seller_id), capacity_by_deadline=capacity, deadline=deadline
            )
        )
    return results[:MAX_RESULTS]


def log_search(session: Session, query: str, filters: SearchFilters, result_count: int) -> Search:
    """Add the search to the searches table and the event log, in the caller's transaction (spec 3.8 step 1)."""
    given = filters.given()
    search = Search(query=query, filters_json=given, result_count=result_count)
    session.add(search)
    session.flush()
    record_event(
        session,
        EventType.SEARCH_LOGGED,
        search_summary(query, filters, result_count),
        entity_id=search.id,
        payload={"query": query, "filters": given, "result_count": result_count},
    )
    return search


def search_summary(query: str, filters: SearchFilters, result_count: int) -> str:
    """For the live feed: 'An agent searched for "ceramic mugs": no results.', with any filters in words.

    The buyer's own words (the query and the city) are quoted with any quote mark in them escaped, so they cannot
    end the quotation and pass for OpenStall's own words in the public feed.
    """
    asked = []
    if filters.max_price is not None:
        asked.append(f"at most ${filters.max_price:,.2f} each")
    if filters.quantity is not None:
        asked.append("1 unit" if filters.quantity == 1 else f"{filters.quantity:,} units")
    if filters.deadline is not None:
        asked.append(f"by {filters.deadline:%B} {filters.deadline.day}, {filters.deadline.year}")
    if filters.ship_to:
        asked.append(f"to {_quoted(filters.ship_to)}")
    found = {0: "no results", 1: "1 result"}.get(result_count, f"{result_count} results")
    details = f" ({', '.join(asked)})" if asked else ""
    return f"An agent searched for {_quoted(query)}{details}: {found}."


def _quoted(words: str) -> str:
    """'"ceramic mugs"'. A quote mark or backslash inside is escaped (\\"), as in JSON."""
    return json.dumps(words, ensure_ascii=False)


def one_line(text: str, name: str) -> str:
    """The text on one line: each run of spaces, tabs and line breaks becomes one space, and the ends are trimmed.

    Any other control character (NUL, backspace, escape...) is refused with the reason: Postgres cannot store NUL,
    and the log and the public /demo page show the words as they are.
    """
    for char in text:
        if not char.isspace() and unicodedata.category(char) in {"Cc", "Cs"}:
            raise SearchError(f"{name} cannot contain control characters (it has U+{ord(char):04X}); send plain text.")
    return " ".join(text.split())


def price_cap(max_price: float | Decimal) -> Decimal:
    """The buyer's price cap in whole cents, rounded down: 29.999 becomes 29.99, and 30 becomes 30.00.

    Every price is whole cents, so the rounded cap finds exactly what the exact one would, and the log, the feed and
    the /demo panel show the cap that the filter applies.
    """
    return Decimal(str(max_price)).quantize(CENT, rounding=ROUND_FLOOR)
