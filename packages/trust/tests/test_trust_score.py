"""The trust score formula (spec 3.7)."""

from decimal import Decimal

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
