"""The trust score formula (spec 3.7)."""

import math
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from openstall_trust import trust_score


def test_spec_example_passport():
    # 0.4 x 0.95 + 0.3 x 0.98 + 0.3 x 0.91 = 0.947
    assert trust_score(0.95, 0.02, 0.91) == Decimal("0.95")


@pytest.mark.parametrize(
    ("on_time", "dispute", "photo", "expected"),
    [
        (1, 0, 1, "1.00"),
        (0, 1, 0, "0.00"),
        (1, 1, 0, "0.40"),
        (0, 0, 0, "0.30"),
        (0, 1, 1, "0.30"),
        (0.5, 0.5, 0.5, "0.50"),
        (0.8, 0.1, 0.6, "0.77"),
    ],
)
def test_known_values(on_time, dispute, photo, expected):
    assert str(trust_score(on_time, dispute, photo)) == expected


def test_rounds_half_up_on_the_rates_as_written():
    # Exactly 0.895, 0.865, 0.925 and 0.005. Scoring the binary floats instead (0.82 is really
    # 0.8199...) gives 0.89 and 0.86 for the first two; banker's rounding gives 0.86, 0.92, 0.00.
    assert trust_score(0.82, 0.02, 0.91) == Decimal("0.90")
    assert trust_score(0.82, 0.01, 0.8) == Decimal("0.87")
    assert trust_score(1.0, 0.05, 0.8) == Decimal("0.93")
    assert trust_score(0.0125, 1, 0) == Decimal("0.01")


def test_rounds_once_however_many_places_a_rate_has():
    # Exactly 0.4 x 0.012499...: just under half a cent, so 0.00. Rounded to 28 digits on the way
    # (the default decimal precision), it would become 0.005 and then 0.01.
    assert trust_score(Decimal("0.01249999999999999999999999999999"), 1, 0) == Decimal("0.00")
    assert trust_score(Decimal("0.0124" + "9" * 300), 1, 0) == Decimal("0.00")
    # Exactly 0.345 - 3e-301, so 0.34: 1 - 1e-300 must not be rounded to 1 on the way.
    assert trust_score(0.1125, 1e-300, 0) == Decimal("0.34")


@pytest.mark.parametrize(
    "callers_settings",
    [
        {"prec": 2},  # the spec example would score 0.94, and 1.00 would not fit at all
        {"rounding": ROUND_UP},
        {"traps": [Inexact, Rounded]},  # often set in money code; rounding a score would raise
    ],
)
def test_the_callers_decimal_context_is_not_used(callers_settings):
    with localcontext(**callers_settings) as callers_context:
        assert trust_score(0.95, 0.02, 0.91) == Decimal("0.95")
        assert trust_score(1, 0, 1) == Decimal("1.00")
        assert trust_score(Decimal("0.0124" + "9" * 30), 1, 0) == Decimal("0.00")
        assert not any(callers_context.flags.values()), "the caller's context was changed"


def test_accepts_decimals():
    assert trust_score(Decimal("0.95"), Decimal("0.02"), Decimal("0.91")) == Decimal("0.95")


def test_always_two_places():
    assert trust_score(1, 0, 1).as_tuple().exponent == -2
    assert trust_score(0, 1, 0).as_tuple().exponent == -2


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1, 2, float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_rates_outside_0_to_1_are_rejected(bad, position):
    rates = [0.5, 0.5, 0.5]
    rates[position] = bad
    name = ["on_time_rate", "dispute_rate", "photo_originality"][position]
    with pytest.raises(ValueError, match=name):
        trust_score(*rates)


@pytest.mark.parametrize("bad", ["0.9", None, True, [0.9]])
def test_non_numbers_are_rejected(bad):
    with pytest.raises(TypeError, match="on_time_rate"):
        trust_score(bad, 0.0, 0.5)


rates = st.floats(min_value=0, max_value=1)


@given(rates, rates, rates, rates)
def test_score_stays_in_range_and_rises_with_on_time_delivery(on_time, better, dispute, photo):
    score = trust_score(on_time, dispute, photo)
    assert Decimal("0.00") <= score <= Decimal("1.00")
    if better >= on_time:
        assert trust_score(better, dispute, photo) >= score


def exact_score(on_time, dispute, photo) -> Decimal:
    """The formula worked out in fractions, rates read through str(), then rounded half-up once."""
    on_time, dispute, photo = (Fraction(str(rate)) for rate in (on_time, dispute, photo))
    score = Fraction(4, 10) * on_time + Fraction(3, 10) * (1 - dispute) + Fraction(3, 10) * photo
    return Decimal(math.floor(score * 100 + Fraction(1, 2))) / 100


# Any float, and Decimals with up to 399 places: every rate trust_score promises to score exactly.
exact_rates = rates | st.integers(min_value=0, max_value=399).flatmap(
    lambda places: st.decimals(min_value=0, max_value=1, places=places)
)


@given(exact_rates, exact_rates, exact_rates)
def test_score_is_the_exact_formula_rounded_half_up_once(on_time, dispute, photo):
    assert trust_score(on_time, dispute, photo) == exact_score(on_time, dispute, photo)
