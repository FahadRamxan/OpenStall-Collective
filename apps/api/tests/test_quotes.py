"""Quote requests and negotiation rounds (prompt 24): every matching maker's agent asked side by side within a time
limit, up to 3 rounds with the buyer's limits as feedback, and the request, rounds and offers on /demo."""

import threading
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from openstall_agents.adapters import FakeLLM
from openstall_agents.fake_answers import fake_answer
from openstall_allocator import FixedClock
from openstall_api import quotes
from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.models import Event, Offer
from openstall_api.quotes import MAX_ROUNDS, QuoteError, create_quote_request, round_feedback, run_quote
from openstall_api.seed import DEMO_REQUEST, seed

client = TestClient(app)

TODAY = date(2026, 11, 10)
DEADLINE = TODAY + timedelta(days=30)
# Spec section 2: what each maker can supply in 30 days. Noor is the backup: her valid offer is above Grace's, so
# the allocator (prompt 25) leaves her out at first.
SEED_SUPPLY = {"s_amina": 12, "s_priya": 11, "s_lucia": 10, "s_grace": 11, "s_noor": 10}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(quotes, "clock", FixedClock(TODAY))


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def story(db, quantity: int = 40, deadline: date = DEADLINE):
    return create_quote_request(db, [DEMO_REQUEST], quantity, Decimal("30.00"), deadline, "Chicago", TODAY)


def event_types(db) -> list[str]:
    return [event.type for event in db.scalars(select(Event).where(Event.type.like("quote.%")).order_by(Event.id))]


class ScriptedSellers(FakeLLM):
    """Each maker's agent answers from her own script; a maker without one answers as fake mode does."""

    def __init__(self, scripts: dict[str, list[dict]], delay: dict[str, float] | None = None) -> None:
        super().__init__(responder=fake_answer)
        self.scripts = {name: list(replies) for name, replies in scripts.items()}
        self.delay = delay or {}
        self.lock = threading.Lock()

    def generate_json(self, prompt, *, schema, system=None, images=()):
        name = next((name for name in self.scripts | self.delay if f'"maker": "{name}"' in prompt), None)
        if name in self.delay:
            time.sleep(self.delay[name])
        with self.lock:
            if name in self.scripts and self.scripts[name]:
                return dict(self.scripts[name].pop(0))
        return super().generate_json(prompt, schema=schema, system=system, images=images)


def test_the_story_request_gets_a_valid_offer_from_every_matching_maker_in_one_round(seeded, fakes):
    request, products = story(seeded)

    result = run_quote(seeded, request, products, fakes.llm, TODAY)

    assert result.rounds == 1
    assert set(result.asked) == set(SEED_SUPPLY)
    assert {seller: offer.quantity for seller, offer in result.offers.items()} == SEED_SUPPLY
    assert {seller: str(offer.unit_price) for seller, offer in result.offers.items()} == {
        "s_amina": "18.00",
        "s_priya": "16.00",
        "s_lucia": "22.00",
        "s_grace": "29.00",
        "s_noor": "29.50",
    }
    assert (result.total_capacity, result.short_by) == (54, 0)
    assert event_types(seeded) == ["quote.requested", "quote.round_finished", "quote.completed"]
    assert request.rounds == 1 and request.asked == 5 and request.completed_at is not None


def test_makers_without_a_valid_offer_get_more_rounds_with_the_buyers_limits_and_none_goes_past_three(seeded):
    # Grace's agent keeps asking $35 for two rounds, then fits; Lucía's never goes below $12.
    llm = ScriptedSellers(
        {
            "Grace": [{"unit_price_usd": 35, "message": ""}] * 6 + [{"unit_price_usd": 29, "message": "OK."}],
            "Lucía": [{"unit_price_usd": 12, "message": ""}] * 20,
        }
    )
    request, products = story(seeded)

    result = run_quote(seeded, request, products, llm, TODAY)

    assert result.rounds == MAX_ROUNDS == 3
    assert "s_lucia" not in result.offers
    assert result.offers["s_grace"].round == 3
    rounds = {
        seller: sorted({o.round for o in seeded.scalars(select(Offer).where(Offer.seller_id == seller))})
        for seller in ("s_grace", "s_lucia", "s_amina")
    }
    assert rounds == {"s_grace": [1, 2, 3], "s_lucia": [1, 2, 3], "s_amina": [1]}
    assert max(o.attempt for o in seeded.scalars(select(Offer))) == 3
    assert event_types(seeded) == ["quote.requested"] + ["quote.round_finished"] * 3 + ["quote.completed"]


def test_the_feedback_between_rounds_is_the_buyers_limits():
    class Request:
        max_unit_price = Decimal("30.00")
        quantity = 40
        deadline = date(2026, 12, 10)

    assert round_feedback(Request()) == (
        "The buyer's maximum is $30.00 a unit, for 40 units by December 10. Your earlier prices were refused: offer "
        "one within your limits and theirs."
    )


def test_the_quote_stops_as_soon_as_every_maker_has_a_valid_offer(seeded):
    llm = ScriptedSellers({"Priya": [{"unit_price_usd": 5, "message": ""}] * 3})
    request, products = story(seeded)

    result = run_quote(seeded, request, products, llm, TODAY)

    # Priya's agent goes below her floor three times in round 1, then the fake answers well in round 2.
    assert result.rounds == 2
    assert set(result.offers) == set(SEED_SUPPLY)


def test_a_slow_agent_is_cut_off_and_makes_no_offer_that_round(seeded):
    llm = ScriptedSellers({}, delay={"Noor": 1.0})
    request, products = story(seeded)

    started = time.monotonic()
    result = run_quote(seeded, request, products, llm, TODAY, time_limit=0.3, max_rounds=1)

    assert time.monotonic() - started < 0.9
    assert "s_noor" not in result.offers
    assert set(result.offers) == set(SEED_SUPPLY) - {"s_noor"}
    summaries = [e.payload_json["summary"] for e in seeded.scalars(select(Event).where(Event.type == "offer.rejected"))]
    assert "Noor's agent ran out of time in round 1: no offer this round" in summaries


def test_total_capacity_below_the_quantity_is_reported(seeded, fakes):
    request, products = story(seeded, quantity=60)

    result = run_quote(seeded, request, products, fakes.llm, TODAY)

    assert (result.total_capacity, result.short_by) == (54, 6)
    completed = seeded.scalars(select(Event).where(Event.type == EventType.QUOTE_COMPLETED.value)).one()
    assert completed.payload_json["summary"] == "The quote is done: 5 valid offers for 54 units, 6 short of the 60 asked for"


@pytest.mark.parametrize(
    ("queries", "quantity", "price", "deadline", "ship_to", "words"),
    [
        ([" "], 40, "30.00", DEADLINE, "Chicago", "Say what you want"),
        ([DEMO_REQUEST], 0, "30.00", DEADLINE, "Chicago", "The quantity must be at least 1, not 0."),
        ([DEMO_REQUEST], 40, "0.00", DEADLINE, "Chicago", "more than $0 and in whole cents, not 0.00"),
        ([DEMO_REQUEST], 40, "29.999", DEADLINE, "Chicago", "in whole cents, not 29.999"),
        ([DEMO_REQUEST], 40, "30.00", TODAY, "Chicago", "must be after today, 2026-11-10 (UTC)"),
        ([DEMO_REQUEST], 40, "30.00", DEADLINE, " ", "Say which city"),
    ],
)
def test_a_request_that_cannot_be_quoted_says_why(seeded, queries, quantity, price, deadline, ship_to, words):
    with pytest.raises(QuoteError, match=words.replace("$", r"\$").replace("(", r"\(").replace(")", r"\)")):
        create_quote_request(seeded, queries, quantity, Decimal(price), deadline, ship_to, TODAY)


def test_a_request_nobody_makes_asks_nobody_and_is_done_at_once(seeded, fakes):
    request, products = create_quote_request(
        seeded, ["ceramic mugs"], 40, Decimal("30.00"), DEADLINE, "Chicago", TODAY
    )

    result = run_quote(seeded, request, products, fakes.llm, TODAY)

    assert (products, result.rounds, result.offers) == ([], 0, {})
    assert event_types(seeded) == ["quote.requested", "quote.completed"]


def test_the_dev_quote_runs_the_story_and_the_latest_quote_says_how_it_went(seeded):
    response = client.post("/api/dev/quote")

    assert response.status_code == 201
    body = response.json()
    assert {o["seller_id"]: o["quantity"] for o in body["valid_offers"]} == SEED_SUPPLY
    latest = client.get("/api/quotes", params={"limit": 1}).json()
    assert len(latest) == 1
    quote = latest[0]
    assert quote["id"] == body["quote"]["id"]
    assert {key: quote[key] for key in ("queries", "quantity", "max_unit_price", "ship_to", "rounds", "asked")} == {
        "queries": [DEMO_REQUEST],
        "quantity": 40,
        "max_unit_price": "30.00",
        "ship_to": "Chicago",
        "rounds": 1,
        "asked": 5,
    }
    assert (quote["valid_offers"], quote["total_capacity"], quote["deadline"]) == (5, 54, "2026-12-10")
    assert quote["completed_at"] is not None
    assert client.get(f"/api/quotes/{quote['id']}").json() == quote


def test_an_unknown_quote_says_so(seeded):
    response = client.get("/api/quotes/q_nobody")

    assert response.status_code == 404
    assert response.json()["detail"] == "There is no quote request called 'q_nobody'."


def test_the_dev_quote_does_not_exist_outside_fake_mode(use_settings, db):
    use_settings(OPENSTALL_MODE="sandbox")

    assert client.post("/api/dev/quote").status_code == 404
