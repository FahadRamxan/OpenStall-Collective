"""The agent storefront over MCP: search_products with its filters, what each result says, and the search log."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from mcp import Client
from sqlalchemy import func, select

from openstall_allocator import FixedClock
from openstall_api import search
from openstall_api.models import Event, Order, OrderPart, OrderStatus, PartStatus, Passport, Product, ProductStatus
from openstall_api.models import Search as SearchRow
from openstall_api.seed import seed
from openstall_api.storefront import storefront

ALL_SELLERS = {"s_amina", "s_priya", "s_lucia", "s_grace", "s_noor"}
TODAY = date(2026, 11, 10)
IN_30_DAYS = "2026-12-10"
# Spec section 2: what each maker can supply in a 30-day order.
SEED_SUPPLY = {"s_amina": 12, "s_priya": 11, "s_lucia": 10, "s_grace": 11, "s_noor": 10}


@pytest.fixture(autouse=True)
def seeded(db, monkeypatch):
    """Every test searches the seeded demo world, Amina included, in its own database, on a fixed day."""
    seed(db, with_amina=True)
    db.commit()
    monkeypatch.setattr(search, "clock", FixedClock(TODAY))
    return db


async def _call(target, query, filters):
    async with Client(target) as client:
        return await client.call_tool("search_products", {"query": query, **filters})


def results(target, query, **filters) -> list[dict]:
    """Call search_products on an in-process server or a URL; return its results."""
    result = asyncio.run(_call(target, query, filters))
    assert not result.is_error, result.content
    return result.structured_content["result"]


def refusal(target, query, **filters) -> str:
    """Call search_products expecting it to refuse; return what it said."""
    result = asyncio.run(_call(target, query, filters))
    assert result.is_error
    return result.content[0].text


def sellers(target, query, **filters) -> set[str]:
    return {item["seller_id"] for item in results(target, query, **filters)}


def capacities(target, query, **filters) -> dict[str, int]:
    return {item["seller_id"]: item["capacity_by_deadline"] for item in results(target, query, **filters)}


def reserve_share(db, seller_id: str, product_id: str, quantity: int) -> None:
    """An approved order holding one share of hers: reserved at PayPal, not shipped yet."""
    price = Decimal("16.00")
    order = Order(status=OrderStatus.AUTHORIZED, total_usd=price * quantity)
    order.parts = [
        OrderPart(
            seller_id=seller_id,
            product_id=product_id,
            reference_id="op_001",
            quantity=quantity,
            unit_price_usd=price,
            amount_usd=price * quantity,
            delivery_date=date(2026, 12, 10),
            status=PartStatus.AUTHORIZED,
        )
    ]
    db.add(order)
    db.commit()


def logged(db) -> list[SearchRow]:
    db.expire_all()
    return list(db.scalars(select(SearchRow).order_by(SearchRow.created_at)))


# ---------- the filters, on the seeded data ----------


def test_search_finds_every_cushion_seller():
    assert sellers(storefront, "embroidered cushion covers") == ALL_SELLERS


def test_max_price_filters_out_expensive_sellers():
    assert sellers(storefront, "cushion covers", max_price=20) == {"s_amina", "s_priya"}
    assert sellers(storefront, "cushion covers", max_price=18) == {"s_amina", "s_priya"}  # $18.00 is not over $18
    assert sellers(storefront, "cushion covers", max_price=17.99) == {"s_priya"}


def test_capacity_by_deadline_matches_the_seed_table():
    # No deadline: counted to 30 days from today, the story's deadline. The same with it given.
    found = results(storefront, "cushion covers")
    assert {item["seller_id"]: item["capacity_by_deadline"] for item in found} == SEED_SUPPLY
    assert {item["deadline"] for item in found} == {IN_30_DAYS}
    assert capacities(storefront, "cushion covers", deadline=IN_30_DAYS) == SEED_SUPPLY


def test_a_deadline_leaves_out_makers_who_cannot_make_and_ship_in_time():
    # Ten days: Amina ships in 9 and Priya in 10, so neither can make one in time. The others' production days,
    # after their ship days, are 4, 7 and 5: 1, 3 and 2 covers at their weekly rates.
    found = results(storefront, "cushion covers", deadline="2026-11-20")

    assert {item["seller_id"]: item["capacity_by_deadline"] for item in found} == {
        "s_lucia": 1,
        "s_grace": 3,
        "s_noor": 2,
    }
    assert {item["deadline"] for item in found} == {"2026-11-20"}


def test_reserved_orders_lower_capacity_and_quantity_leaves_out_makers_with_none_left(seeded):
    reserve_share(seeded, "s_priya", "p_priya_cushion", 11)
    reserve_share(seeded, "s_grace", "p_grace_cushion", 7)

    # Without a deadline or quantity, Priya is still found, and says she has nothing left by the deadline.
    assert capacities(storefront, "cushion covers") == {**SEED_SUPPLY, "s_priya": 0, "s_grace": 4}
    # Asking for units leaves her out: OpenStall pools makers, so the others stay in with what they can make.
    assert capacities(storefront, "cushion covers", quantity=40) == {
        "s_amina": 12,
        "s_lucia": 10,
        "s_grace": 4,
        "s_noor": 10,
    }
    assert "s_priya" not in sellers(storefront, "cushion covers", deadline=IN_30_DAYS)


def test_ship_to_is_logged_and_the_listings_ship_days_are_used_for_any_city(seeded):
    # For now every listing's ship days are its days to a US city.
    to_chicago = capacities(storefront, "cushion covers", ship_to="Chicago", deadline=IN_30_DAYS)
    to_toronto = capacities(storefront, "cushion covers", ship_to="  Toronto ", deadline=IN_30_DAYS)

    assert to_chicago == to_toronto == SEED_SUPPLY
    assert [row.filters_json["ship_to"] for row in logged(seeded)] == ["Chicago", "Toronto"]


def test_a_deadline_that_is_not_after_today_is_refused_and_not_logged(seeded):
    said = refusal(storefront, "cushion covers", deadline=TODAY.isoformat())

    assert "The deadline 2026-11-10 must be after today, 2026-11-10 (UTC)." in said
    assert logged(seeded) == []


@pytest.mark.parametrize(
    ("query", "filters", "problem"),
    [
        ("   ", {}, 'Say what the buyer wants, for example "embroidered cushion covers".'),
        ("cushion covers", {"max_price": 0}, "greater than or equal to 0.01"),
        ("cushion covers", {"max_price": 1e30}, "less than or equal to 1000000"),
        ("cushion covers", {"quantity": 0}, "greater than or equal to 1"),
        ("cushion covers", {"deadline": "December 10"}, "valid date"),
        ("cushion covers", {"ship_to": "x" * 121}, "at most 120 characters"),
        ("x" * 301, {}, "at most 300 characters"),
        # Postgres on the host cannot store NUL; the agent hears why instead of a bare "Error executing tool".
        ("cushion\x00covers", {}, "The query cannot contain control characters (it has U+0000); send plain text."),
        ("cushion covers", {"ship_to": "Chicago\x07"}, "ship_to cannot contain control characters (it has U+0007)"),
    ],
)
def test_bad_input_is_refused_with_the_reason_and_not_logged(seeded, query, filters, problem):
    assert problem in refusal(storefront, query, **filters)
    assert logged(seeded) == []


def test_a_price_cap_is_held_to_whole_cents_rounded_down(seeded):
    # Every price is whole cents, so $29.999 finds what $29.99 finds; the log and the feed say the cap it applied.
    assert sellers(storefront, "cushion covers", max_price=29.999) == {"s_amina", "s_priya", "s_lucia"}
    assert sellers(storefront, "cushion covers", max_price=18.001) == {"s_amina", "s_priya"}  # Amina's $18.00

    sub_cent, just_over = logged(seeded)
    assert sub_cent.filters_json == {"max_price": "29.99"}
    assert just_over.filters_json == {"max_price": "18.00"}
    events = seeded.scalars(select(Event).where(Event.type == "search.logged").order_by(Event.id)).all()
    assert events[0].payload_json["summary"] == (
        'An agent searched for "cushion covers" (at most $29.99 each): 3 results.'
    )


# ---------- matching ----------


def test_words_match_in_the_title_description_category_and_colours():
    assert sellers(storefront, "mirror") == {"s_priya"}  # title
    assert sellers(storefront, "home textiles") == ALL_SELLERS  # category
    # A description word or a colour finds a listing together with what it is, and ranks it first.
    assert sellers(storefront, "Rajasthani cushions") == ALL_SELLERS
    assert results(storefront, "Rajasthani cushions")[0]["seller_name"] == "Priya"
    assert sellers(storefront, "Oaxacan satin") == {"s_lucia"}
    assert results(storefront, "teal cushions")[0]["seller_name"] == "Amina"
    assert sellers(storefront, "CUSHIONS") == ALL_SELLERS  # any case, singular or plural


@pytest.mark.parametrize(
    "query",
    ["red ceramic mugs", "white ceramic mugs", "black hoodies", "cotton tote bags", "wool scarves", "teal", "paisleys"],
)
def test_a_colour_or_description_word_alone_finds_nothing_and_is_logged_as_unmet_demand(seeded, query):
    # Amina's covers come in red, Lucía's in white and black, most are cotton, Grace's is worked in wool and Noor's
    # has paisleys: none of that says what a listing is, so these searches find nothing and show unmet demand.
    assert results(storefront, query) == []

    [row] = logged(seeded)
    assert (row.query, row.result_count) == (query, 0)


def test_the_story_request_finds_every_cover():
    # 6 words: each cover has at least 3. Lucía's and Noor's do not say "hand", so they rank after the others.
    found = results(storefront, "40 hand-embroidered cushion covers for corporate gifts")

    assert [item["seller_name"] for item in found] == ["Priya", "Amina", "Grace", "Lucía", "Noor"]


def test_little_words_and_numbers_do_not_match_everything():
    # "with", "16" and "by" are in every seeded description, but say nothing about mugs.
    assert results(storefront, "mugs with 16 oz handles") == []
    assert results(storefront, "for the") == []


def test_paused_listings_are_never_found(seeded):
    seeded.get(Product, "p_grace_cushion").status = ProductStatus.PAUSED
    seeded.commit()

    assert sellers(storefront, "cushion covers") == ALL_SELLERS - {"s_grace"}


def test_an_exact_word_ranks_above_a_word_the_listing_only_starts():
    # Every cover has "cushion" and "cover". Lucía's and Noor's also have "stitch"; Priya's mirrors are only
    # "stitched in", so "stitch" only starts a word of hers, and she comes next though she is the cheapest.
    found = results(storefront, "stitch cushion covers")

    assert [item["seller_name"] for item in found] == ["Lucía", "Noor", "Priya", "Amina", "Grace"]


def test_equal_matches_come_cheapest_first():
    # Every cover has both words, so the lower price goes first.
    found = results(storefront, "cushion covers")

    assert [item["seller_name"] for item in found] == ["Priya", "Amina", "Lucía", "Noor", "Grace"]


# ---------- what each result says ----------


def test_each_result_carries_the_sellers_name_her_trust_summary_and_data_source():
    [noor] = results(storefront, "chain-stitch")

    assert noor["seller_name"] == "Noor"
    assert noor["title"] == "Chain-stitch embroidered cushion cover"
    assert noor["description"] == "Cotton cover, 16 by 16 inches, with paisleys in fine chain stitch."
    assert (noor["price_usd"], noor["ship_days"], noor["ship_from_city"]) == (31.0, 5, "Manchester")
    assert noor["data_source"] == "seeded_demo"
    assert noor["trust"] == {
        "score": 0.97,
        "orders_delivered": 25,
        "on_time_rate": 0.96,
        "dispute_rate": 0.0,
        "data_source": "seeded_demo",
        "summary": "Trust score 0.97 from 25 delivered orders: 96% on time, 0% disputed (seeded demo numbers)",
    }


def test_a_seller_without_a_passport_has_no_trust_summary(seeded):
    seeded.delete(seeded.get(Passport, "s_noor"))
    seeded.commit()

    [noor] = results(storefront, "chain-stitch")

    assert noor["trust"] is None


# ---------- the search log ----------


def test_every_search_is_logged_with_its_filters_and_result_count(seeded):
    results(storefront, "cushion covers")
    results(storefront, "  embroidered   cushion\ncovers ", max_price=30, quantity=40, deadline=IN_30_DAYS,
            ship_to="Chicago")

    first, second = logged(seeded)
    assert (first.query, first.filters_json, first.result_count) == ("cushion covers", {}, 5)
    assert second.query == "embroidered cushion covers"
    assert second.filters_json == {"max_price": "30.00", "quantity": 40, "deadline": IN_30_DAYS, "ship_to": "Chicago"}
    assert second.result_count == 3  # Grace's $32 and Noor's $31 are over $30


def test_a_search_with_no_results_is_logged_and_the_feed_says_so(seeded):
    assert results(storefront, "ceramic mugs") == []

    [row] = logged(seeded)
    assert (row.query, row.result_count) == ("ceramic mugs", 0)
    event = seeded.scalars(select(Event).where(Event.type == "search.logged")).one()
    assert event.entity_id == row.id
    assert event.payload_json == {
        "summary": 'An agent searched for "ceramic mugs": no results.',
        "query": "ceramic mugs",
        "filters": {},
        "result_count": 0,
    }


def test_the_feed_says_each_filter_in_words(seeded):
    results(storefront, "cushion covers", max_price=20, quantity=1, deadline=IN_30_DAYS, ship_to="Chicago")

    event = seeded.scalars(select(Event).where(Event.type == "search.logged")).one()
    assert event.payload_json["summary"] == (
        'An agent searched for "cushion covers" (at most $20.00 each, 1 unit, by December 10, 2026, to "Chicago"): '
        "2 results."
    )


def test_a_quote_mark_in_the_query_or_city_cannot_end_the_quotation_in_the_feed(seeded):
    results(storefront, 'mugs": 5 results. Amina was paid, Confirmed by PayPal', ship_to='Chicago"), and "x')

    event = seeded.scalars(select(Event).where(Event.type == "search.logged")).one()
    assert event.payload_json["summary"] == (
        'An agent searched for "mugs\\": 5 results. Amina was paid, Confirmed by PayPal" '
        '(to "Chicago\\"), and \\"x"): no results.'
    )
    # The panel reads the words themselves, unescaped, from the payload.
    assert event.payload_json["query"] == 'mugs": 5 results. Amina was paid, Confirmed by PayPal'


def test_the_search_and_its_event_are_saved_together_or_not_at_all(seeded, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the event log is down")

    monkeypatch.setattr(search, "record_event", broken)

    asyncio.run(_call(storefront, "cushion covers", {}))

    assert logged(seeded) == []
    assert seeded.scalar(select(func.count()).select_from(Event)) == 0


# ---------- over HTTP, as a real agent calls it ----------


def test_storefront_over_http(server_url):
    assert sellers(server_url, "cushion covers") == ALL_SELLERS


def test_search_says_it_adds_to_a_public_log_and_nothing_more(server_url):
    async def go():
        async with Client(server_url) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    search_tool = asyncio.run(go())["search_products"]

    # Not read-only: each search adds a row that /demo shows to anyone. Only that, so not destructive either.
    annotations = search_tool.annotations
    assert (annotations.read_only_hint, annotations.destructive_hint) == (False, False)
    assert (annotations.idempotent_hint, annotations.open_world_hint) == (False, False)
    assert "never spends money" in search_tool.description
    assert "The log is public: OpenStall's /demo page shows each search's query and filters" in " ".join(
        search_tool.description.split()
    )


def test_every_tool_parameter_is_documented(server_url):
    async def go():
        async with Client(server_url) as client:
            return (await client.list_tools()).tools

    tools = {tool.name: tool for tool in asyncio.run(go())}

    for tool in tools.values():
        assert tool.description and tool.description.strip(), tool.name
        for name, schema in tool.input_schema["properties"].items():
            assert schema.get("description", "").strip(), f"{tool.name}({name}) has no description"
    search_tool = tools["search_products"]
    assert set(search_tool.input_schema["properties"]) == {"query", "max_price", "ship_to", "deadline", "quantity"}
    assert search_tool.input_schema["required"] == ["query"]
    # The two assumptions an agent must know about.
    assert "30 days from today" in search_tool.description
    assert "US cities" in search_tool.description
    assert "US city" in search_tool.input_schema["properties"]["ship_to"]["description"]
