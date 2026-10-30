import math
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import product

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from openstall_allocator import Offer, Plan, allocate, is_valid_offer

DEADLINE = date(2026, 12, 10)


def offer(
    seller_id: str, price: str, quantity: int, delivery: date = DEADLINE, offer_id: str | None = None
) -> Offer:
    return Offer(
        seller_id=seller_id, unit_price=price, quantity=quantity, delivery_date=delivery, offer_id=offer_id
    )


def three_big_offers() -> list[Offer]:
    return [offer("s_a", "10.00", 40), offer("s_b", "11.00", 40), offer("s_c", "12.00", 40)]


def story() -> list[Offer]:
    """The four valid offers of the story, with the most each seller can supply in 30 days."""
    return [
        offer("s_amina", "18.00", 12, offer_id="off_amina"),
        offer("s_priya", "16.00", 11, offer_id="off_priya"),
        offer("s_lucia", "22.00", 10, offer_id="off_lucia"),
        offer("s_grace", "29.00", 11, offer_id="off_grace"),
    ]


# --- The story (spec section 2, step 7) ---------------------------------------------------------


def test_the_story_splits_12_11_10_7_cheapest_first():
    plan = allocate(story(), 40, DEADLINE)
    assert plan.complete
    assert plan.shortfall == 0
    assert plan.reason is None
    assert plan.total_quantity == 40
    assert plan.quantities() == {"s_amina": 12, "s_priya": 11, "s_lucia": 10, "s_grace": 7}
    assert [line.seller_id for line in plan.lines] == ["s_priya", "s_amina", "s_lucia", "s_grace"]
    assert [line.line_total for line in plan.lines] == [
        Decimal("176.00"),
        Decimal("216.00"),
        Decimal("220.00"),
        Decimal("203.00"),
    ]
    assert plan.total_cost == Decimal("815.00")
    assert str(plan.total_cost) == "815.00"
    assert [line.offer_id for line in plan.lines] == ["off_priya", "off_amina", "off_lucia", "off_grace"]
    assert all(line.delivery_date == DEADLINE for line in plan.lines)


@pytest.mark.parametrize("run_date", [date(2026, 11, 10), date(2026, 12, 15), date(2028, 2, 29)])
def test_the_story_from_limits_to_plan_whatever_the_run_date(seed, story_request, story_offers, run_date):
    """Offers built and checked by the rules, then split: needs all four sellers on any run date."""
    for made in story_offers:
        seller = seed[made.seller_id]
        assert is_valid_offer(made, seller.policy, seller.listing, story_request, run_date)
    plan = allocate(story_offers, story_request.quantity, story_request.deadline)
    assert plan.complete
    assert plan.quantities() == {"s_priya": 11, "s_amina": 12, "s_lucia": 10, "s_grace": 7}
    assert plan.total_cost == Decimal("815.00")
    # No three sellers are enough on their own.
    for left_out in story_offers:
        others = [o for o in story_offers if o is not left_out]
        assert not allocate(others, story_request.quantity, story_request.deadline).complete


def test_fair_share_is_off_by_default():
    assert allocate(story(), 40, DEADLINE) == allocate(story(), 40, DEADLINE, fair_share=None)


# --- Shortfalls -------------------------------------------------------------------------------------


def test_a_shortfall_gives_a_partial_plan_with_a_plain_reason():
    plan = allocate(story(), 50, DEADLINE)
    assert not plan.complete
    assert plan.total_quantity == 44
    assert plan.shortfall == 6
    assert plan.requested_quantity == 50
    assert plan.quantities() == {"s_priya": 11, "s_amina": 12, "s_lucia": 10, "s_grace": 11}
    assert plan.total_cost == Decimal("931.00")
    assert plan.reason == "Only 44 of 50 units can be supplied by 2026-12-10."


def test_no_offers_at_all():
    plan = allocate([], 40, DEADLINE)
    assert not plan.complete
    assert plan.lines == ()
    assert plan.total_quantity == 0
    assert plan.shortfall == 40
    assert plan.total_cost == Decimal("0.00")
    assert plan.reason == "Only 0 of 40 units can be supplied by 2026-12-10. No seller made an offer."


def test_quantity_zero_needs_nobody():
    plan = allocate(story(), 0, DEADLINE)
    assert plan.complete
    assert plan.lines == ()
    assert plan.total_cost == Decimal("0.00")
    assert plan.shortfall == 0
    assert plan.reason is None
    assert allocate([], 0, DEADLINE) == plan


# --- The deadline -----------------------------------------------------------------------------------


def test_offers_delivered_after_the_deadline_are_left_out_even_when_cheapest():
    late = offer("s_cheap", "5.00", 40, delivery=DEADLINE + timedelta(days=1))
    plan = allocate([*story(), late], 40, DEADLINE)
    assert "s_cheap" not in plan.quantities()
    assert plan.quantities() == {"s_priya": 11, "s_amina": 12, "s_lucia": 10, "s_grace": 7}


def test_delivery_on_the_deadline_counts():
    plan = allocate([offer("s_amina", "18.00", 12, delivery=DEADLINE)], 12, DEADLINE)
    assert plan.complete


def test_the_reason_says_when_late_offers_were_left_out():
    late = [
        offer("s_late_a", "5.00", 40, delivery=DEADLINE + timedelta(days=1)),
        offer("s_late_b", "6.00", 40, delivery=DEADLINE + timedelta(days=9)),
    ]
    plan = allocate([*story()[:2], *late], 40, DEADLINE)
    assert plan.total_quantity == 23
    assert plan.reason == (
        "Only 23 of 40 units can be supplied by 2026-12-10. "
        "2 offers deliver after the deadline and were left out."
    )
    one_late = allocate([late[0]], 40, DEADLINE)
    assert one_late.reason == (
        "Only 0 of 40 units can be supplied by 2026-12-10. "
        "1 offer delivers after the deadline and was left out."
    )


# --- Fair share ---------------------------------------------------------------------------------------


def test_fair_share_spreads_the_order():
    plan = allocate(story(), 40, DEADLINE, fair_share=Decimal("0.25"))
    assert plan.complete
    assert plan.quantities() == {"s_priya": 10, "s_amina": 10, "s_lucia": 10, "s_grace": 10}
    assert plan.total_cost == Decimal("850.00")


@pytest.mark.parametrize("share", [0.3, "0.3", Decimal("0.3")])
def test_fair_share_of_30_percent_caps_each_seller_at_12_of_40(share):
    plan = allocate(three_big_offers(), 40, DEADLINE, fair_share=share)
    assert plan.quantities() == {"s_a": 12, "s_b": 12, "s_c": 12}
    assert not plan.complete
    assert plan.reason == (
        "Only 36 of 40 units can be supplied by 2026-12-10. Fair share caps each seller at 12 units."
    )


@pytest.mark.parametrize(
    "share, quantity",
    [(0.07, 100), ("0.07", 100), (Decimal("0.07"), 100), (0.14, 50), (0.28, 25)],
)
def test_fair_share_is_exact_where_floats_would_allow_one_more_unit(share, quantity):
    # The premise: in floats each product is 7.000000000000001, which rounds up to 8.
    assert math.ceil(float(share) * quantity) == 8
    plan = allocate(three_big_offers(), quantity, DEADLINE, fair_share=share)
    assert plan.quantities() == {"s_a": 7, "s_b": 7, "s_c": 7}
    assert plan.reason == (
        f"Only 21 of {quantity} units can be supplied by 2026-12-10. Fair share caps each seller at 7 units."
    )


def test_the_reason_mentions_fair_share_only_when_it_held_a_seller_back():
    # Half of 50 is 25, more than any seller can supply, so the cap changes nothing.
    plan = allocate(story(), 50, DEADLINE, fair_share=0.5)
    assert plan == allocate(story(), 50, DEADLINE)
    assert plan.reason == "Only 44 of 50 units can be supplied by 2026-12-10."
    # A late offer over the cap is left out anyway, so the cap still held nobody back.
    late = offer("s_late", "5.00", 40, delivery=DEADLINE + timedelta(days=1))
    assert allocate([*story(), late], 50, DEADLINE, fair_share=0.5).reason == (
        "Only 44 of 50 units can be supplied by 2026-12-10. "
        "1 offer delivers after the deadline and was left out."
    )


def test_fair_share_rounds_up_to_a_whole_unit():
    offers = three_big_offers()
    assert allocate(offers, 41, DEADLINE, fair_share=0.3).quantities() == {"s_a": 13, "s_b": 13, "s_c": 13}
    one = allocate(offers, 1, DEADLINE, fair_share=0.3)
    assert one.complete
    assert one.quantities() == {"s_a": 1}


def test_fair_share_of_the_whole_order_changes_nothing():
    assert allocate(story(), 40, DEADLINE, fair_share=1) == allocate(story(), 40, DEADLINE)


@pytest.mark.parametrize("share", [0, -0.1, 1.01, 30, "NaN", "Infinity"])
def test_fair_share_must_be_a_share_of_the_order(share):
    with pytest.raises(ValueError):
        allocate(story(), 40, DEADLINE, fair_share=share)


def test_fair_share_must_be_a_number():
    with pytest.raises(TypeError):
        allocate(story(), 40, DEADLINE, fair_share=True)


# --- Ties ------------------------------------------------------------------------------------------------


def test_a_price_tie_goes_to_the_earlier_delivery():
    offers = [
        offer("s_a", "20.00", 10, delivery=DEADLINE),
        offer("s_b", "20.00", 10, delivery=DEADLINE - timedelta(days=3)),
    ]
    plan = allocate(offers, 10, DEADLINE)
    assert plan.quantities() == {"s_b": 10}


def test_a_full_tie_goes_to_the_lower_seller_id():
    offers = [offer("s_lucia", "20.00", 10), offer("s_amina", "20.00", 10), offer("s_grace", "20.00", 10)]
    plan = allocate(offers, 15, DEADLINE)
    assert [(line.seller_id, line.quantity) for line in plan.lines] == [("s_amina", 10), ("s_grace", 5)]


def test_the_same_offers_in_any_order_give_the_same_plan():
    offers = story()
    expected = allocate(offers, 40, DEADLINE)
    assert allocate(reversed(offers), 40, DEADLINE) == expected
    assert allocate(offers[2:] + offers[:2], 40, DEADLINE) == expected


# --- Inputs ----------------------------------------------------------------------------------------------


def test_an_offer_bigger_than_the_order_is_used_only_as_far_as_needed():
    plan = allocate([offer("s_amina", "18.00", 100)], 40, DEADLINE)
    assert plan.quantities() == {"s_amina": 40}
    assert plan.total_cost == Decimal("720.00")


def test_cents_add_up_exactly():
    plan = allocate([offer("s_a", "0.10", 3), offer("s_b", "19.99", 3)], 6, DEADLINE)
    assert plan.total_cost == Decimal("60.27")
    assert str(plan.total_cost) == "60.27"


def test_any_iterable_of_offers_works():
    assert allocate((o for o in story()), 40, DEADLINE) == allocate(story(), 40, DEADLINE)


def test_each_seller_may_make_only_one_offer():
    with pytest.raises(ValueError):
        allocate([*story(), offer("s_amina", "17.00", 5)], 40, DEADLINE)


def test_a_negative_quantity_is_refused():
    with pytest.raises(ValueError):
        allocate(story(), -1, DEADLINE)


@pytest.mark.parametrize(
    "offers, quantity, deadline",
    [
        (story(), 40.0, DEADLINE),
        (story(), True, DEADLINE),
        (story(), 40, "2026-12-10"),
        ([{"seller_id": "s_amina"}], 40, DEADLINE),
    ],
)
def test_wrong_input_types_are_refused(offers, quantity, deadline):
    with pytest.raises(TypeError):
        allocate(offers, quantity, deadline)


# --- Properties (spec 3.4 "Done when": the plan meets the quantity and deadline, or says it cannot) -----

SELLER_IDS = ["s_amina", "s_priya", "s_lucia", "s_grace", "s_a", "s_b", "s_z", "s_aa", "s_Z", "s_ñ"]
BASE = date(2026, 11, 10)

# Strategies are built once here: building new ones inside every draw made generation slow.
prices = st.one_of(
    st.sampled_from(["9.99", "10.00", "15.30", "16.00", "29.00"]).map(Decimal),  # so ties are common
    st.integers(1, 5000).map(lambda c: Decimal(c).scaleb(-2)),
)
sellers_in_any_order = st.permutations(SELLER_IDS)
spread = st.integers(min_value=0, max_value=1_000_000)  # picks a point in a range; shrinks to its start


@st.composite
def books(draw, max_offers=8, max_units=30, max_quantity=150):
    """Offers from different sellers, a quantity and a deadline."""
    sellers = draw(sellers_in_any_order)[: draw(spread) % (max_offers + 1)]
    offers = [
        Offer(
            seller_id=seller_id,
            unit_price=draw(prices),
            quantity=1 + draw(spread) % max_units,
            delivery_date=BASE + timedelta(days=draw(spread) % 61),
        )
        for seller_id in sellers
    ]
    quantity = draw(spread) % (max_quantity + 1)
    deadline = BASE + timedelta(days=draw(spread) % 61)
    return offers, quantity, deadline


def assert_sound(
    plan: Plan, offers: list[Offer], quantity: int, deadline: date, cap: int | None = None
) -> None:
    """Checks every plan must pass, whatever the offers."""
    by_seller = {o.seller_id: o for o in offers}
    eligible = [o for o in offers if o.delivery_date <= deadline]
    available = sum(o.quantity if cap is None else min(o.quantity, cap) for o in eligible)
    for line in plan.lines:
        made = by_seller[line.seller_id]
        assert 1 <= line.quantity <= made.quantity
        assert cap is None or line.quantity <= cap
        assert made.delivery_date <= deadline
        assert (line.unit_price, line.delivery_date) == (made.unit_price, made.delivery_date)
        assert line.line_total == made.unit_price * line.quantity
    assert len({line.seller_id for line in plan.lines}) == len(plan.lines)
    assert plan.total_quantity == sum(line.quantity for line in plan.lines) <= quantity
    assert plan.total_quantity == min(quantity, available)
    assert plan.complete == (available >= quantity)
    assert plan.shortfall == quantity - plan.total_quantity
    assert plan.total_cost == sum((line.line_total for line in plan.lines), Decimal("0"))
    assert plan.total_cost.as_tuple().exponent == -2
    assert plan.complete or plan.reason.startswith(f"Only {plan.total_quantity} of {quantity} units")
    order = [(line.unit_price, line.delivery_date, line.seller_id) for line in plan.lines]
    assert order == sorted(order)


@settings(max_examples=1000, deadline=None)
@given(books())
def test_a_plan_never_exceeds_an_offer_or_the_request_and_is_complete_when_it_can_be(book):
    offers, quantity, deadline = book
    assert_sound(allocate(offers, quantity, deadline), offers, quantity, deadline)


@settings(max_examples=500, deadline=None)
@given(books(), st.integers(1, 100).map(lambda p: Decimal(p).scaleb(-2)))
@example((three_big_offers(), 100, DEADLINE), Decimal("0.07"))  # a cap of 8 in floats, 7 exactly
def test_fair_share_never_lets_a_seller_take_more_than_the_cap(book, share):
    offers, quantity, deadline = book
    cap = math.ceil(Fraction(share) * quantity)
    assert_sound(allocate(offers, quantity, deadline, fair_share=share), offers, quantity, deadline, cap)


@settings(max_examples=500, deadline=None)
@given(books(), st.data())
def test_the_order_of_the_offers_never_changes_the_plan(book, data):
    offers, quantity, deadline = book
    shuffled = data.draw(st.permutations(offers))
    assert allocate(shuffled, quantity, deadline) == allocate(offers, quantity, deadline)


@settings(max_examples=300, deadline=None)
@given(books(max_offers=4, max_units=5, max_quantity=15))
def test_no_other_split_is_cheaper(book):
    """Brute force over every split: the plan's cost is the minimum the spec asks for."""
    offers, quantity, deadline = book
    plan = allocate(offers, quantity, deadline)
    eligible = [o for o in offers if o.delivery_date <= deadline]
    target = min(quantity, sum(o.quantity for o in eligible))
    cheapest = min(
        sum((o.unit_price * x for o, x in zip(eligible, split)), Decimal("0"))
        for split in product(*(range(o.quantity + 1) for o in eligible))
        if sum(split) == target
    )
    assert plan.total_quantity == target
    assert plan.total_cost == cheapest
