"""Demand Radar (spec 3.8, prompt 44) and the dashboard's API: searches that found nothing are grouped by their words,
counted for the week, and matched to a maker who could make them; her tip goes to her once a week, in her language.
"Done when: seeded searches produce one correct tip": 23 agents searched for ceramic mugs this week, and nobody sells
them."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import ChatMessage, ChatSession, Direction, Event, Search, utcnow
from openstall_api.radar import item_words, same_item, singular
from openstall_api.seed import reset_demo_world

client = TestClient(app)
TODAY = date(2026, 11, 10)
RUNNER = "embroidered-runner-table"


@pytest.fixture
def world(db):
    """The demo world as seeded: five makers, the story's draft order, and Demand Radar's seeded searches."""
    reset_demo_world(db, TODAY)
    db.commit()
    return db


def radar_groups() -> dict[str, dict]:
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    return {group["key"]: group for group in response.json()["radar"]}


def search(db, query: str, results: int = 0, days_ago: float = 0) -> None:
    db.add(Search(query=query, filters_json={}, result_count=results, created_at=utcnow() - timedelta(days=days_ago)))
    db.commit()


# Words


@pytest.mark.parametrize(
    ("word", "one"),
    [("mugs", "mug"), ("runners", "runner"), ("boxes", "box"), ("doilies", "doily"), ("glass", "glass"),
     ("dress", "dress"), ("covers", "cover"), ("candles", "candle"), ("dishes", "dish")],
)  # fmt: skip
def test_plural_and_singular_are_one_word(word, one):
    assert singular(word) == one


def test_a_search_keeps_only_the_words_about_the_item():
    assert item_words("Set of 6 HANDMADE ceramic mugs!") == ["ceramic", "mug"]
    assert item_words("hand-embroidered table runners") == ["embroidered", "table", "runner"]
    assert item_words("for the") == []


def test_searches_share_a_group_when_half_their_words_are_the_same():
    assert same_item(frozenset({"ceramic", "mug"}), frozenset({"ceramic", "coffee", "mug"}))
    assert same_item(frozenset({"cushion", "cover"}), frozenset({"velvet", "cushion", "cover"}))
    assert not same_item(frozenset({"ceramic", "mug"}), frozenset({"embroidered", "table", "runner"}))
    assert not same_item(frozenset({"ceramic", "mug"}), frozenset({"ceramic", "tile", "coaster", "set"}))


# The seeded searches make one correct tip


def test_the_seeded_searches_make_one_correct_tip(world):
    groups = radar_groups()

    mugs = next(iter(groups.values()))  # the most searched first
    assert mugs["label"] == "ceramic mugs"
    assert (mugs["searches"], mugs["seeded"]) == (23, 23)
    assert mugs["maker"] is None
    assert mugs["tip"] == "23 agents searched for ceramic mugs this week. Nobody sells them."
    assert mugs["queries"][0] == "ceramic mugs" and "set of ceramic mugs" in mugs["queries"]

    runners = groups[RUNNER]
    assert (runners["label"], runners["searches"]) == ("embroidered table runner", 9)
    # Every maker embroiders: the most trusted is tipped.
    assert runners["maker"] == {
        "seller_id": "s_noor",
        "name": "Noor",
        "product_title": "Chain-stitch embroidered cushion cover",
        "shared": ["embroidered"],
    }
    assert runners["tip"] == (
        "9 agents searched for embroidered table runner this week. Nobody sells them. Noor makes chain-stitch "
        "embroidered cushion cover: she could."
    )
    assert runners["tipped_at"] is None
    assert [group["label"] for group in groups.values()][2:] == ["block print napkins", "beeswax candles"]


def test_live_searches_count_too_but_not_old_ones_or_ones_that_found_something(world):
    search(world, "Ceramic mug")
    search(world, "ceramic mugs", days_ago=8)  # last week
    search(world, "ceramic mugs", results=3)  # found something

    mugs = next(iter(radar_groups().values()))

    assert (mugs["searches"], mugs["seeded"]) == (24, 23)


def test_agents_searches_leave_out_the_seeded_ones(world):
    search(world, "beeswax candles")

    assert [row["query"] for row in client.get("/api/searches").json()] == ["beeswax candles"]


# Sending a tip


def test_a_tip_goes_to_its_maker_once_in_her_language(world, fakes):
    response = client.post(f"/api/radar/{RUNNER}/tip")

    assert response.status_code == 200, response.text
    assert response.json()["tipped_at"] is not None
    world.expire_all()
    chat = select(ChatMessage).join(ChatSession, ChatSession.id == ChatMessage.session_id)
    sent = world.scalars(
        chat.where(ChatSession.seller_id == "s_noor", ChatMessage.direction == Direction.OUTBOUND)
    ).all()
    [tip] = [message.text for message in sent if "OpenStall" in (message.text or "") and "“" in (message.text or "")]
    assert tip.startswith(
        "OpenStall ڈیمانڈ ریڈار: اس ہفتے 9 خریداروں کے ایجنٹوں نے “embroidered table runner” تلاش کیا"
    )
    [event] = world.scalars(select(Event).where(Event.type == EventType.RADAR_TIP_SENT.value)).all()
    assert event.entity_id == RUNNER
    assert event.payload_json["summary"] == (
        "Demand Radar: Noor was tipped that 9 agents searched for embroidered table runner this week"
    )

    again = client.post(f"/api/radar/{RUNNER}/tip")

    assert again.status_code == 200
    assert len(world.scalars(select(Event).where(Event.type == EventType.RADAR_TIP_SENT.value)).all()) == 1
    assert radar_groups()[RUNNER]["tipped_at"] is not None


def test_a_group_no_maker_could_make_has_no_one_to_tip(world):
    mugs = next(iter(radar_groups().values()))

    response = client.post(f"/api/radar/{mugs['key']}/tip")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "No maker on OpenStall makes anything like “ceramic mugs” yet, so there is no one to tip."
    )
    assert client.post("/api/radar/flying-carpet/tip").json()["detail"] == (
        "No searches for 'flying-carpet' found nothing this week."
    )


def test_in_sandbox_mode_a_tip_needs_the_demo_token(world, use_settings):
    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-token")

    assert client.post(f"/api/radar/{RUNNER}/tip").status_code == 401


# The dashboard's other tables


def test_the_dashboard_lists_orders_shares_and_passports(world):
    dashboard = client.get("/api/dashboard").json()

    assert dashboard["simulated"] is True
    [order] = [row for row in dashboard["orders"] if row["id"] == "ord_demo"]
    assert (order["status"], order["total_usd"], order["units"], order["makers"]) == ("draft", "815.00", 40, 4)
    assert order["paid_usd"] == "0.00" and order["top_up_of"] is None
    shares = [row for row in dashboard["shares"] if row["order_id"] == "ord_demo"]
    assert [(row["maker"], row["quantity"], row["amount_usd"]) for row in shares] == [
        ("Amina", 12, "216.00"),
        ("Priya", 11, "176.00"),
        ("Lucía", 10, "220.00"),
        ("Grace", 7, "203.00"),
    ]
    assert all(row["status"] == "pending" and not row["paid"] and row["tracking_number"] is None for row in shares)
    passports = dashboard["passports"]
    assert [row["name"] for row in passports] == ["Amina", "Grace", "Lucía", "Noor", "Priya"]
    assert all(row["signature_valid"] is True and row["data_source"] == "seeded_demo" for row in passports)
    priya = next(row for row in passports if row["name"] == "Priya")
    assert (priya["orders_delivered"], priya["on_time_rate"], priya["score"]) == (67, 0.97, 0.96)
