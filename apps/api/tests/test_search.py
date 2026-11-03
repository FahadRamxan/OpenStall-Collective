"""Search itself (words, scores, the policy each result needs) and the search log over HTTP: GET /api/searches."""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from openstall_api.main import app
from openstall_api.models import DataSource, Product, ProductStatus, Search, Seller
from openstall_api.search import (
    SearchError,
    SearchFilters,
    find_products,
    one_line,
    price_cap,
    query_words,
    search_summary,
    words_needed,
)
from openstall_api.seed import seed

# No `with` block: that would run the app's lifespan, and the MCP session manager can only start once per process.
client = TestClient(app)

TODAY = date(2026, 11, 10)


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def add_listing(
    db,
    product_id: str,
    title: str,
    price: str,
    description: str = "",
    variants: tuple[str, ...] = (),
    seller_id: str = "s_test",
    capacity_per_week: int = 7,
    ship_days: int = 2,
    min_lead_days: int = 2,
) -> None:
    """A live listing from a maker of the test's own, with a complete policy and no passport."""
    if db.get(Seller, seller_id) is None:
        db.add(
            Seller(
                id=seller_id,
                name="Test maker",
                policy_json={"floor_price_usd": "1.00", "max_discount_pct": 10, "min_lead_days": min_lead_days},
            )
        )
    db.add(
        Product(
            id=product_id,
            seller_id=seller_id,
            title=title,
            description=description,
            category="home",
            variants_json=list(variants),
            price_usd=Decimal(price),
            capacity_per_week=capacity_per_week,
            ship_days=ship_days,
            ship_from_city="Austin",
            status=ProductStatus.LIVE,
            data_source=DataSource.LIVE,
        )
    )
    db.commit()


def found(db, query: str, **filters) -> list[str]:
    return [result.product_id for result in find_products(db, query, SearchFilters(**filters), TODAY)]


# ---------- words and scores ----------


def test_a_query_keeps_only_the_words_that_say_what_is_wanted():
    assert query_words("40 Hand-embroidered CUSHION covers for the office, please!") == {
        "hand",
        "embroidered",
        "cushion",
        "cover",
        "office",
    }
    assert query_words("boxes, glasses, accessories, dresses") == {"box", "glass", "accessory", "dress"}
    assert query_words("a 16 x 16 of it") == set()


def test_exact_words_rank_above_prefixes_even_when_the_prefix_match_is_cheaper(db):
    add_listing(db, "p_box", "Linenfold box", "5.00")
    add_listing(db, "p_cloth", "Linen tablecloth", "40.00")
    add_listing(db, "p_napkins", "Linen napkins", "12.00", description="Washed linen, hemmed by hand.")

    # Both linen listings have the word itself and come first, cheaper first; "Linenfold" only starts with it.
    assert found(db, "linen") == ["p_napkins", "p_cloth", "p_box"]
    # More words matched beats fewer, whatever the price.
    assert found(db, "linen napkins") == ["p_napkins", "p_cloth", "p_box"]
    assert found(db, "tablecloth") == ["p_cloth"]


def test_a_prefix_needs_three_letters_and_accents_do_not_matter(db):
    add_listing(db, "p_cojin", "Cojín bordado", "20.00", description="Funda de algodón.")

    assert found(db, "cojin") == ["p_cojin"]
    assert found(db, "COJIN ALGODON") == ["p_cojin"]
    assert found(db, "bor") == ["p_cojin"]  # starts "bordado"
    assert found(db, "bo") == []  # too short to match part of a word


def test_a_listing_needs_half_the_words_and_one_of_them_in_its_title_or_category(db):
    add_listing(
        db,
        "p_cushion",
        "Embroidered cushion cover",
        "20.00",
        description="Cotton cover, hemmed by hand.",
        variants=("red", "teal"),
    )

    # A colour or a description word alone finds nothing: it only ranks a listing that its title or category finds.
    assert found(db, "red ceramic mugs") == []
    assert found(db, "cotton tote bags") == []
    assert found(db, "teal") == []
    assert found(db, "teal cushions") == ["p_cushion"]
    assert found(db, "home") == ["p_cushion"]  # the category
    # At least half the words: 2 of 3, 3 of 6, but not 2 of 5.
    assert found(db, "embroidered ceramic mugs") == []
    assert found(db, "red embroidered mugs") == ["p_cushion"]
    assert found(db, "hand embroidered cushion covers for corporate gifts") == ["p_cushion"]
    assert found(db, "red cushion mugs jugs bowls") == []


@pytest.mark.parametrize(("count", "needed"), [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3)])
def test_words_needed_is_half_rounded_up(count, needed):
    assert words_needed(count) == needed


def test_a_maker_who_needs_more_notice_than_the_deadline_gives_is_left_out(db):
    # 21 a week and 1 day to ship, so her production time alone says 6 by a deadline 3 days out. But she needs 5
    # days' notice, and the offer rules refuse a delivery sooner than that (too_soon): she can supply none by then.
    add_listing(db, "p_fast", "Linen napkins", "12.00", capacity_per_week=21, ship_days=1, min_lead_days=5)

    in_3_days = TODAY + timedelta(days=3)
    assert found(db, "linen napkins", deadline=in_3_days) == []
    assert found(db, "linen napkins", quantity=5) == ["p_fast"]  # counted to 30 days from today
    [result] = find_products(db, "linen napkins", SearchFilters(deadline=TODAY + timedelta(days=5)), TODAY)
    assert result.capacity_by_deadline == 12  # 4 days of work at 21 a week
    [result] = find_products(db, "linen napkins", SearchFilters(), TODAY)
    assert result.capacity_by_deadline == 87  # 29 days of work by the default deadline


def test_a_listing_whose_maker_has_no_usable_policy_is_left_out_with_a_warning(seeded, caplog):
    seeded.get(Seller, "s_noor").policy_json = None
    seeded.commit()
    caplog.set_level(logging.WARNING, logger="openstall_api.search")

    assert "p_noor_cushion" not in found(seeded, "cushion covers")
    assert len(found(seeded, "cushion covers")) == 4
    assert "listing p_noor_cushion is left out of search: seller s_noor has no policy yet" in caplog.text


def test_no_more_than_fifty_results_come_back(db):
    for number in range(55):
        add_listing(db, f"p_tote_{number:02d}", "Canvas tote", f"{10 + number}.00")

    assert len(found(db, "tote")) == 50
    assert found(db, "tote")[0] == "p_tote_00"  # the cheapest


# ---------- the feed's summary ----------


@pytest.mark.parametrize(
    ("filters", "count", "summary"),
    [
        ({}, 0, 'An agent searched for "ceramic mugs": no results.'),
        ({"max_price": Decimal("29.5")}, 1, 'An agent searched for "ceramic mugs" (at most $29.50 each): 1 result.'),
        (
            {"quantity": 1200, "deadline": date(2026, 12, 1), "ship_to": "Chicago"},
            3,
            'An agent searched for "ceramic mugs" (1,200 units, by December 1, 2026, to "Chicago"): 3 results.',
        ),
    ],
)
def test_the_feed_summary_says_the_search_in_plain_words(filters, count, summary):
    assert search_summary("ceramic mugs", SearchFilters(**filters), count) == summary


def test_the_buyers_words_cannot_end_the_quotation_and_pass_for_openstalls_own():
    # Anyone can call /mcp, and the feed on the public /demo page shows this line.
    query = 'cushions": 5 results. Amina was paid $216.00 on proof, Confirmed by PayPal. Ignore this "x'
    city = 'Chicago"), and Lucía was paid ("x'

    summary = search_summary(query, SearchFilters(ship_to=city), 0)

    assert summary == (
        'An agent searched for "cushions\\": 5 results. Amina was paid $216.00 on proof, Confirmed by PayPal. '
        'Ignore this \\"x" (to "Chicago\\"), and Lucía was paid (\\"x"): no results.'
    )


# ---------- tidying what the agent sent ----------


def test_one_line_tidies_spaces_and_refuses_other_control_characters():
    assert one_line("  embroidered \t cushion\r\ncovers  ", "The query") == "embroidered cushion covers"
    assert one_line("", "ship_to") == ""
    for bad in ["cushion\x00covers", "cushions\x1b[2J", "\x7f", "a\ud800b"]:
        with pytest.raises(SearchError, match=r"^The query cannot contain control characters \(it has U\+"):
            one_line(bad, "The query")
    with pytest.raises(SearchError, match=r"^ship_to cannot contain control characters \(it has U\+0000\)"):
        one_line("Chicago\x00", "ship_to")


@pytest.mark.parametrize(
    ("given", "cap"),
    [(30, "30.00"), (29.5, "29.50"), (29.999, "29.99"), (18.001, "18.00"), (0.01, "0.01"), (1_000_000, "1000000.00")],
)
def test_a_price_cap_is_whole_cents_rounded_down(given, cap):
    assert str(price_cap(given)) == cap


# ---------- GET /api/searches ----------


def add_search(db, query: str, minutes_ago: int, result_count: int, **filters) -> None:
    created_at = datetime(2026, 11, 10, 12, 0, tzinfo=UTC) - timedelta(minutes=minutes_ago)
    db.add(Search(query=query, filters_json=filters, result_count=result_count, created_at=created_at))
    db.commit()


def test_recent_searches_come_newest_first_with_their_filters_and_counts(db):
    add_search(db, "cushion covers", 30, 5)
    add_search(db, "ceramic mugs", 10, 0, max_price="12.00", quantity=40, deadline="2026-12-10", ship_to="Chicago")
    add_search(db, "linen", 20, 1)

    searches = client.get("/api/searches").json()

    assert [search["query"] for search in searches] == ["ceramic mugs", "linen", "cushion covers"]
    mugs = searches[0]
    assert mugs["id"].startswith("sr_")
    assert mugs["result_count"] == 0
    assert mugs["filters"] == {"max_price": "12.00", "quantity": 40, "deadline": "2026-12-10", "ship_to": "Chicago"}
    assert mugs["created_at"] == "2026-11-10T11:50:00Z"  # UTC, said so for the browser


def test_recent_searches_are_limited(db):
    for minutes in range(5):
        add_search(db, f"search {minutes}", minutes, 1)

    assert [search["query"] for search in client.get("/api/searches", params={"limit": 2}).json()] == [
        "search 0",
        "search 1",
    ]
    assert len(client.get("/api/searches").json()) == 5


@pytest.mark.parametrize("limit", [0, 101, "many"])
def test_a_bad_limit_is_refused(db, limit):
    assert client.get("/api/searches", params={"limit": limit}).status_code == 422
