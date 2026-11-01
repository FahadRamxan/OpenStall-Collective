from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from itertools import combinations

import pytest
from hypothesis import assume, event, given, settings
from hypothesis import strategies as st

from openstall_allocator import (
    CENT,
    Clock,
    FixedClock,
    Listing,
    Offer,
    QuoteRequest,
    RejectionReason,
    SellerPolicy,
    SystemClock,
    capacity_available,
    is_valid_offer,
    lowest_allowed_price,
)

# Run dates that stress the calendar: month and year ends, a leap day, DST changes, judging week.
RUN_DATES = [
    date(2026, 10, 30),
    date(2026, 11, 10),
    date(2026, 12, 1),
    date(2026, 12, 15),
    date(2027, 2, 10),
    date(2027, 3, 14),
    date(2028, 2, 29),
]


def check(seller, offer, request, today, **kwargs):
    return is_valid_offer(offer, seller.policy, seller.listing, request, today, **kwargs)


def story_offer(seller, request, **changes) -> Offer:
    """A valid story offer for this seller (list price, all she can make, due on the deadline)."""
    offer = Offer(
        seller_id=seller.policy.seller_id,
        unit_price=seller.listing.price_usd,
        quantity=seller.can_supply_in_30_days,
        delivery_date=request.deadline,
    )
    return replace(offer, **changes)


# --- The seed table (spec section 2) ---------------------------------------------------------


@pytest.mark.parametrize(
    "seller_id, expected",
    [("s_amina", 12), ("s_priya", 11), ("s_lucia", 10), ("s_grace", 11)],
)
def test_seed_capacities_for_a_30_day_deadline(seed, run_date, seller_id, expected):
    seller = seed[seller_id]
    deadline = run_date + timedelta(days=30)
    assert capacity_available(seller.policy, seller.listing, run_date, deadline) == expected
    assert seller.can_supply_in_30_days == expected


@pytest.mark.parametrize("run_date", RUN_DATES)
def test_the_story_needs_all_four_sellers_whatever_the_run_date(seed, run_date):
    deadline = run_date + timedelta(days=30)
    capacities = {
        seller_id: capacity_available(seller.policy, seller.listing, run_date, deadline)
        for seller_id, seller in seed.items()
    }
    assert capacities == {"s_amina": 12, "s_priya": 11, "s_lucia": 10, "s_grace": 11}
    assert sum(capacities.values()) == 44
    assert all(sum(trio) < 40 for trio in combinations(capacities.values(), 3))


@pytest.mark.parametrize(
    "seller_id, lowest",
    [("s_amina", "15.30"), ("s_priya", "13.60"), ("s_lucia", "19.00"), ("s_grace", "27.20")],
)
def test_seed_lowest_allowed_prices_stay_under_the_buyers_cap(seed, story_request, seller_id, lowest):
    seller = seed[seller_id]
    price = lowest_allowed_price(seller.policy, seller.listing)
    assert price == Decimal(lowest)
    assert str(price) == lowest  # exactly 2 places
    assert price < story_request.max_unit_price


def test_graces_first_offer_is_over_the_cap_and_her_second_is_valid(seed, story_request, run_date):
    grace = seed["s_grace"]
    first = story_offer(grace, story_request)
    assert first.unit_price == Decimal("32.00")
    assert check(grace, first, story_request, run_date).reason == RejectionReason.OVER_BUYER_CAP
    assert check(grace, replace(first, unit_price="29.00"), story_request, run_date).valid


@pytest.mark.parametrize("seller_id", ["s_amina", "s_priya", "s_lucia"])
def test_the_other_story_offers_are_valid_at_list_price(seed, story_request, run_date, seller_id):
    seller = seed[seller_id]
    assert check(seller, story_offer(seller, story_request), story_request, run_date).valid


# --- capacity_available ------------------------------------------------------------------------


def test_capacity_is_zero_when_shipping_takes_all_the_time(seed, run_date):
    amina = seed["s_amina"]  # 9 ship days
    for days in (0, 5, 9):
        assert capacity_available(amina.policy, amina.listing, run_date, run_date + timedelta(days=days)) == 0
    assert capacity_available(amina.policy, amina.listing, run_date, run_date - timedelta(days=3)) == 0
    # 2 production days at 4 a week: 8 // 7 = 1 unit.
    assert capacity_available(amina.policy, amina.listing, run_date, run_date + timedelta(days=11)) == 1


def test_committed_units_use_up_capacity_but_never_below_zero(seed, run_date):
    amina = seed["s_amina"]
    deadline = run_date + timedelta(days=30)
    assert capacity_available(amina.policy, amina.listing, run_date, deadline, committed_units=5) == 7
    assert capacity_available(amina.policy, amina.listing, run_date, deadline, committed_units=12) == 0
    assert capacity_available(amina.policy, amina.listing, run_date, deadline, committed_units=50) == 0
    with pytest.raises(ValueError):
        capacity_available(amina.policy, amina.listing, run_date, deadline, committed_units=-1)


def test_capacity_refuses_datetimes_which_would_lose_part_of_a_day(seed, run_date):
    amina = seed["s_amina"]
    now = datetime(2026, 11, 10, 15, 0)
    with pytest.raises(TypeError):
        capacity_available(amina.policy, amina.listing, now, datetime(2026, 12, 10))
    with pytest.raises(TypeError):
        capacity_available(amina.policy, amina.listing, run_date, datetime(2026, 12, 10))


# --- lowest_allowed_price ------------------------------------------------------------------------


def policy_and_listing(floor, pct, price):
    policy = SellerPolicy(
        seller_id="s_test", floor_price_usd=floor, max_discount_pct=pct, capacity_per_week=4, min_lead_days=5
    )
    return policy, Listing(seller_id="s_test", price_usd=price, ship_days=3)


@pytest.mark.parametrize(
    "floor, pct, price, expected",
    [
        ("15.00", 15, "18.00", "15.30"),  # the discount limit is higher than the floor
        ("19.00", 15, "22.00", "19.00"),  # the floor is higher than the discount limit
        ("0.00", 15, "19.99", "17.00"),  # 16.9915 rounds up, never down
        ("0.00", "12.5", "10.01", "8.76"),  # 8.75875 rounds up
        ("15.00", 0, "18.00", "18.00"),  # no discount at all
        ("15.00", 100, "18.00", "15.00"),  # any discount, so only the floor counts
        ("0.00", 100, "18.00", "0.00"),
    ],
)
def test_lowest_allowed_price(floor, pct, price, expected):
    assert lowest_allowed_price(*policy_and_listing(floor, pct, price)) == Decimal(expected)


# --- is_valid_offer: each reason and its boundary ---------------------------------------------------


def test_exactly_the_lowest_allowed_price_is_valid_and_one_cent_below_is_not(seed, story_request, run_date):
    amina = seed["s_amina"]
    at_lowest = story_offer(amina, story_request, unit_price="15.30")
    assert check(amina, at_lowest, story_request, run_date).valid
    below = replace(at_lowest, unit_price="15.29")
    assert tuple(check(amina, below, story_request, run_date)) == (False, RejectionReason.BELOW_FLOOR)


def test_the_floor_itself_is_too_low_when_the_discount_limit_is_higher(seed, story_request, run_date):
    amina = seed["s_amina"]  # floor $15, but 15% off $18 is $15.30
    offer = story_offer(amina, story_request, unit_price="15.00")
    assert check(amina, offer, story_request, run_date).reason == RejectionReason.BELOW_FLOOR


def test_exactly_the_buyers_cap_is_valid_and_one_cent_over_is_not(seed, story_request, run_date):
    grace = seed["s_grace"]
    at_cap = story_offer(grace, story_request, unit_price="30.00")
    assert check(grace, at_cap, story_request, run_date).valid
    over = replace(at_cap, unit_price="30.01")
    assert check(grace, over, story_request, run_date).reason == RejectionReason.OVER_BUYER_CAP


def test_all_the_capacity_is_valid_and_one_more_unit_is_not(seed, story_request, run_date):
    lucia = seed["s_lucia"]
    full = story_offer(lucia, story_request, quantity=10)
    assert check(lucia, full, story_request, run_date).valid
    one_more = replace(full, quantity=11)
    assert check(lucia, one_more, story_request, run_date).reason == RejectionReason.OVER_CAPACITY


def test_committed_units_count_against_an_offer(seed, story_request, run_date):
    lucia = seed["s_lucia"]
    offer = story_offer(lucia, story_request, quantity=8)
    assert check(lucia, offer, story_request, run_date, committed_units=2).valid
    result = check(lucia, offer, story_request, run_date, committed_units=3)
    assert result.reason == RejectionReason.OVER_CAPACITY


def test_delivery_on_the_last_lead_day_is_valid_and_a_day_sooner_is_not(seed, run_date):
    grace = seed["s_grace"]  # 5 lead days, 3 ship days, 3 a week
    request = QuoteRequest(quantity=1, max_unit_price="30", deadline=run_date + timedelta(days=10))
    on_the_day = run_date + timedelta(days=5)
    offer = Offer(seller_id="s_grace", unit_price="29", quantity=1, delivery_date=on_the_day)
    assert check(grace, offer, request, run_date).valid
    sooner = replace(offer, delivery_date=run_date + timedelta(days=4))
    assert check(grace, sooner, request, run_date).reason == RejectionReason.TOO_SOON


def test_delivery_on_the_deadline_is_valid_and_a_day_later_is_not(seed, story_request, run_date):
    priya = seed["s_priya"]
    on_time = story_offer(priya, story_request)
    assert check(priya, on_time, story_request, run_date).valid
    late = replace(on_time, delivery_date=story_request.deadline + timedelta(days=1))
    assert check(priya, late, story_request, run_date).reason == RejectionReason.AFTER_DEADLINE


def test_a_deadline_inside_the_lead_time_leaves_no_valid_delivery_date(seed, run_date):
    grace = seed["s_grace"]
    policy = replace(grace.policy, min_lead_days=10)
    request = QuoteRequest(quantity=1, max_unit_price="30", deadline=run_date + timedelta(days=8))
    # She has capacity, so the delivery date alone decides.
    assert capacity_available(policy, grace.listing, run_date, request.deadline) == 2
    for days in range(0, 15):
        delivery = run_date + timedelta(days=days)
        offer = Offer(seller_id="s_grace", unit_price="29", quantity=1, delivery_date=delivery)
        result = is_valid_offer(offer, policy, grace.listing, request, run_date)
        # too_soon is checked first, so day 9 (after the deadline, inside the lead time) is too soon.
        expected = RejectionReason.TOO_SOON if days < 10 else RejectionReason.AFTER_DEADLINE
        assert tuple(result) == (False, expected)


def test_the_first_failing_rule_is_the_reason(seed, story_request, run_date):
    amina = seed["s_amina"]
    everything_wrong = story_offer(
        amina, story_request, unit_price="1.00", quantity=99, delivery_date=run_date + timedelta(days=1)
    )
    late = story_request.deadline + timedelta(days=1)
    fixes_in_order = [
        ({}, RejectionReason.BELOW_FLOOR),
        ({"unit_price": "99.00"}, RejectionReason.OVER_BUYER_CAP),
        ({"unit_price": "18.00"}, RejectionReason.OVER_CAPACITY),
        ({"unit_price": "18.00", "quantity": 12}, RejectionReason.TOO_SOON),
        ({"unit_price": "18.00", "quantity": 12, "delivery_date": late}, RejectionReason.AFTER_DEADLINE),
        ({"unit_price": "18.00", "quantity": 12, "delivery_date": story_request.deadline}, None),
    ]
    for changes, reason in fixes_in_order:
        assert check(amina, replace(everything_wrong, **changes), story_request, run_date).reason == reason


def test_an_offer_must_be_checked_against_its_own_sellers_limits(seed, story_request, run_date):
    grace_offer = story_offer(seed["s_grace"], story_request, unit_price="29.00")
    with pytest.raises(ValueError):
        check(seed["s_amina"], grace_offer, story_request, run_date)
    with pytest.raises(ValueError):
        is_valid_offer(grace_offer, seed["s_grace"].policy, seed["s_amina"].listing, story_request, run_date)


# --- Clocks -----------------------------------------------------------------------------------------


def test_a_fixed_clock_always_gives_its_day():
    clock = FixedClock(date(2026, 11, 10))
    assert clock.today() == clock.today() == date(2026, 11, 10)
    assert isinstance(clock, Clock)
    with pytest.raises(TypeError):
        FixedClock(datetime(2026, 11, 10, 9, 30))


def test_the_system_clock_gives_todays_date_in_utc():
    clock = SystemClock()
    before = datetime.now(timezone.utc).date()
    today = clock.today()
    after = datetime.now(timezone.utc).date()
    assert isinstance(clock, Clock)
    assert type(today) is date
    assert before <= today <= after


class FrozenDatetime(datetime):
    """A datetime whose now() is 2026-11-10 22:00 UTC, when it is already November 11 in Lahore."""

    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc)
        if tz is None:  # local time, as datetime.now() gives it
            return instant.astimezone().replace(tzinfo=None)
        return instant.astimezone(tz)


def test_the_system_clock_uses_utc_unless_given_another_zone(monkeypatch):
    monkeypatch.setattr("openstall_allocator.rules.datetime", FrozenDatetime)
    assert SystemClock().today() == date(2026, 11, 10)
    assert SystemClock(timezone(timedelta(hours=5))).today() == date(2026, 11, 11)  # Lahore


def test_the_system_clock_follows_its_time_zone():
    # These zones are 26 hours apart, so they are on different dates at every moment.
    ahead = SystemClock(timezone(timedelta(hours=14))).today()
    behind = SystemClock(timezone(timedelta(hours=-12))).today()
    assert 1 <= (ahead - behind).days <= 2


def test_a_clock_drives_the_story_dates(seed):
    clock = FixedClock(date(2026, 12, 15))
    today = clock.today()
    request = QuoteRequest(quantity=40, max_unit_price="30", deadline=today + timedelta(days=30))
    amina = seed["s_amina"]
    assert capacity_available(amina.policy, amina.listing, today, request.deadline) == 12
    offer = Offer(seller_id="s_amina", unit_price="18", quantity=12, delivery_date=request.deadline)
    assert is_valid_offer(offer, amina.policy, amina.listing, request, today)


# --- Properties (spec 3.3 "Done when": no valid offer below the floor, whatever the pressure) --------

ONE_DAY = timedelta(days=1)


def from_cents(count: int) -> Decimal:
    return Decimal(count).scaleb(-2)


def to_cents(amount: Decimal) -> int:
    return int(amount.scaleb(2))


# Strategies are built once here: building new ones inside every draw made generation slow.
cents = st.integers(min_value=0, max_value=100_000).map(from_cents)  # $0.00 to $1,000.00
percents = st.integers(min_value=0, max_value=10_000).map(from_cents)  # 0.00% to 100.00%
days_2026_to_2030 = st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31))
coin = st.booleans()
spread = st.integers(min_value=0, max_value=1_000_000)  # picks a point in a range; shrinks to its start


def pick(draw, choices: list):
    return choices[draw(spread) % len(choices)]


def around(*amounts: Decimal) -> list[Decimal]:
    """Each amount and the cent either side of it, never negative."""
    return [amount + step for amount in amounts for step in (-CENT, 0, CENT) if amount + step >= 0]


@dataclass(frozen=True)
class Scenario:
    offer: Offer
    policy: SellerPolicy
    listing: Listing
    request: QuoteRequest
    today: date
    committed: int


@st.composite
def policies_and_listings(draw):
    policy = SellerPolicy(
        seller_id="s_test",
        floor_price_usd=draw(cents),
        max_discount_pct=draw(percents),
        capacity_per_week=draw(spread) % 51,
        min_lead_days=draw(spread) % 31,
    )
    listing = Listing(seller_id="s_test", price_usd=draw(cents), ship_days=draw(spread) % 61)
    return policy, listing


@st.composite
def scenarios(draw):
    """An offer and everything it is checked against.

    Half the time the offer aims inside every limit; otherwise each value is anywhere, or a step
    either side of a limit. So valid offers, every rejection reason and the exact edges all turn up.
    """
    policy, listing = draw(policies_and_listings())
    today = draw(days_2026_to_2030)
    lowest = lowest_allowed_price(policy, listing)
    lead = policy.min_lead_days
    # Requests usually leave room for a valid offer, but not always.
    max_price = draw(cents) if draw(coin) else lowest + from_cents(draw(spread) % 2_001)
    days = draw(spread) % 131 - 10 if draw(coin) else lead + listing.ship_days + draw(spread) % 31
    deadline = today + timedelta(days=days)
    request = QuoteRequest(quantity=1 + draw(spread) % 200, max_unit_price=max_price, deadline=deadline)
    committed = 0 if draw(coin) else draw(spread) % 41
    capacity = capacity_available(policy, listing, today, deadline, committed)
    earliest = today + timedelta(days=lead)

    aim = draw(coin)
    if aim and lowest <= max_price:
        price = lowest + from_cents(draw(spread) % (to_cents(max_price) - to_cents(lowest) + 1))
    else:
        price = draw(cents) if draw(coin) else pick(draw, around(lowest, max_price))
    if aim and capacity >= 1:
        quantity = 1 + draw(spread) % capacity
    else:
        quantity = 1 + draw(spread) % 300 if draw(coin) else pick(draw, [max(1, capacity), capacity + 1])
    if aim and earliest <= deadline:
        delivery = earliest + timedelta(days=draw(spread) % ((deadline - earliest).days + 1))
    elif draw(coin):
        delivery = today + timedelta(days=draw(spread) % 161 - 10)
    else:
        delivery = pick(draw, [earliest - ONE_DAY, earliest, deadline, deadline + ONE_DAY])
    offer = Offer(seller_id="s_test", unit_price=price, quantity=quantity, delivery_date=delivery)
    return Scenario(offer, policy, listing, request, today, committed)


def exact_lowest(policy: SellerPolicy, listing: Listing) -> Fraction:
    """The spec's lowest allowed price, in exact fractions with no rounding."""
    discounted = Fraction(listing.price_usd) * (1 - Fraction(policy.max_discount_pct) / 100)
    return max(Fraction(policy.floor_price_usd), discounted)


def spec_is_valid_offer(s: Scenario) -> bool:
    """Spec 3.3's validation code, word for word apart from exact fractions for the money."""
    offer, policy, listing, request, today = s.offer, s.policy, s.listing, s.request, s.today
    production_days = (request.deadline - today).days - listing.ship_days
    capacity = max(0, policy.capacity_per_week * production_days // 7 - s.committed)
    return (
        exact_lowest(policy, listing) <= Fraction(offer.unit_price) <= Fraction(request.max_unit_price)
        and offer.quantity <= capacity
        and today + timedelta(days=policy.min_lead_days) <= offer.delivery_date <= request.deadline
    )


@settings(max_examples=2000, deadline=None)
@given(scenarios())
def test_no_valid_offer_is_ever_below_the_lowest_price_or_over_capacity(s):
    result = is_valid_offer(s.offer, s.policy, s.listing, s.request, s.today, committed_units=s.committed)
    event("valid" if result.valid else f"invalid: {result.reason}")
    if result.valid:
        assert s.offer.unit_price >= lowest_allowed_price(s.policy, s.listing)
        assert s.offer.unit_price >= s.policy.floor_price_usd
        assert Fraction(s.offer.unit_price) >= exact_lowest(s.policy, s.listing)
        assert s.offer.unit_price <= s.request.max_unit_price
        capacity = capacity_available(s.policy, s.listing, s.today, s.request.deadline, s.committed)
        assert s.offer.quantity <= capacity
        assert s.today + timedelta(days=s.policy.min_lead_days) <= s.offer.delivery_date <= s.request.deadline


@settings(max_examples=1000, deadline=None)
@given(scenarios())
def test_the_verdict_matches_the_spec_code(s):
    result = is_valid_offer(s.offer, s.policy, s.listing, s.request, s.today, committed_units=s.committed)
    assert result.valid == spec_is_valid_offer(s)


@settings(max_examples=500, deadline=None)
@given(scenarios(), spread)
def test_every_price_below_the_lowest_allowed_is_rejected_as_below_floor(s, below):
    """However hard a buyer pushes, a price under the limit never passes, whatever else is true."""
    lowest = lowest_allowed_price(s.policy, s.listing)
    assume(lowest > 0)
    pressured = replace(s.offer, unit_price=from_cents(below % to_cents(lowest)))
    result = is_valid_offer(pressured, s.policy, s.listing, s.request, s.today, committed_units=s.committed)
    assert tuple(result) == (False, RejectionReason.BELOW_FLOOR)


@settings(max_examples=500, deadline=None)
@given(policies_and_listings())
def test_the_lowest_price_is_the_smallest_whole_cent_within_both_limits(pair):
    policy, listing = pair
    lowest = lowest_allowed_price(policy, listing)
    exact = exact_lowest(policy, listing)
    assert lowest.as_tuple().exponent == -2
    assert Fraction(lowest) >= exact
    assert Fraction(lowest) - Fraction(1, 100) < exact


@settings(max_examples=500, deadline=None)
@given(
    policies_and_listings(),
    days_2026_to_2030,
    st.integers(-30, 200),
    st.integers(0, 30),
    st.integers(0, 40),
)
def test_capacity_grows_with_time_and_shrinks_with_commitments(pair, today, days, extra_days, committed):
    policy, listing = pair
    deadline = today + timedelta(days=days)
    later = deadline + timedelta(days=extra_days)
    capacity = capacity_available(policy, listing, today, deadline, committed)
    assert capacity >= 0
    assert capacity_available(policy, listing, today, later, committed) >= capacity
    assert capacity_available(policy, listing, today, deadline, committed + 1) <= capacity
    assert capacity_available(policy, listing, today, deadline) >= capacity
