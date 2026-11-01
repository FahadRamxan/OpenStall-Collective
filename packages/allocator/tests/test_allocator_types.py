import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from openstall_allocator import (
    Listing,
    Offer,
    OfferCheck,
    Plan,
    PlanLine,
    QuoteRequest,
    RejectionReason,
    SellerPolicy,
    usd,
)

# The policy JSON from spec 3.3, as a seller confirms it in chat.
SPEC_POLICY_JSON = """{
  "seller_id": "s_amina",
  "floor_price_usd": 15.00,
  "max_discount_pct": 15,
  "capacity_per_week": 4,
  "min_lead_days": 5,
  "free_shipping_min_qty": 3
}"""

DAY = date(2026, 12, 10)


@pytest.mark.parametrize(
    "value, expected",
    [
        (Decimal("18"), "18.00"),
        (Decimal("15.300"), "15.30"),
        (18, "18.00"),
        ("29.99", "29.99"),
        (" 7.5 ", "7.50"),
        (29.99, "29.99"),
        (0.1, "0.10"),
        (0, "0.00"),
        (-0.0, "0.00"),
        ("-0", "0.00"),
    ],
)
def test_usd_returns_exactly_two_places(value, expected):
    amount = usd(value)
    assert isinstance(amount, Decimal)
    assert str(amount) == expected


@pytest.mark.parametrize(
    "value",
    ["-0.01", -1, "15.305", 0.1 + 0.2, Decimal("NaN"), float("inf"), "Infinity", "fifteen", "", "1e40"],
)
def test_usd_refuses_amounts_it_would_have_to_change(value):
    with pytest.raises(ValueError):
        usd(value)


@pytest.mark.parametrize("value", [True, None, [15], object()])
def test_usd_refuses_things_that_are_not_numbers(value):
    with pytest.raises(TypeError):
        usd(value)


def test_the_spec_policy_json_maps_onto_seller_policy():
    exact = SellerPolicy(**json.loads(SPEC_POLICY_JSON, parse_float=Decimal))
    from_floats = SellerPolicy(**json.loads(SPEC_POLICY_JSON))
    assert exact == from_floats
    assert exact.floor_price_usd == Decimal("15.00")
    assert str(exact.floor_price_usd) == "15.00"
    assert exact.max_discount_pct == 15
    assert exact.free_shipping_min_qty == 3


def amina_policy(**changes) -> SellerPolicy:
    values = {
        "seller_id": "s_amina",
        "floor_price_usd": 15,
        "max_discount_pct": 15,
        "capacity_per_week": 4,
        "min_lead_days": 5,
    }
    return SellerPolicy(**(values | changes))


@pytest.mark.parametrize("pct", [-1, "100.01", "12.345", Decimal("NaN")])
def test_max_discount_must_be_a_percentage_with_at_most_two_places(pct):
    with pytest.raises(ValueError):
        amina_policy(max_discount_pct=pct)


@pytest.mark.parametrize("pct", [0, 100, "12.5", Decimal("33.33"), 15.0])
def test_max_discount_accepts_percentages_with_up_to_two_places(pct):
    assert amina_policy(max_discount_pct=pct).max_discount_pct == Decimal(str(pct))


@pytest.mark.parametrize(
    "build",
    [
        lambda: Offer(seller_id="s_amina", unit_price="18", quantity=0, delivery_date=DAY),
        lambda: Offer(seller_id="", unit_price="18", quantity=1, delivery_date=DAY),
        lambda: Offer(seller_id="s_amina", unit_price="18", quantity=1, delivery_date=DAY, offer_id=" "),
        lambda: QuoteRequest(quantity=0, max_unit_price="30", deadline=DAY),
        lambda: Listing(seller_id="s_amina", price_usd="18", ship_days=-1),
        lambda: amina_policy(floor_price_usd="-1"),
        lambda: amina_policy(capacity_per_week=-1),
        lambda: amina_policy(min_lead_days=-5),
        lambda: amina_policy(free_shipping_min_qty=-1),
    ],
)
def test_impossible_values_are_refused(build):
    with pytest.raises(ValueError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: Offer(seller_id="s_amina", unit_price="18", quantity=2.0, delivery_date=DAY),
        lambda: Offer(seller_id="s_amina", unit_price="18", quantity=True, delivery_date=DAY),
        lambda: Offer(seller_id="s_amina", unit_price="18", quantity=1, delivery_date=datetime(2026, 12, 10)),
        lambda: Offer(seller_id="s_amina", unit_price="18", quantity=1, delivery_date="2026-12-10"),
        lambda: QuoteRequest(quantity=40, max_unit_price="30", deadline=datetime(2026, 12, 10, 23, 59)),
    ],
)
def test_wrong_types_are_refused(build):
    with pytest.raises(TypeError):
        build()


def test_inputs_are_frozen_and_keyword_only():
    offer = Offer(seller_id="s_amina", unit_price="18", quantity=12, delivery_date=DAY)
    with pytest.raises(FrozenInstanceError):
        offer.unit_price = Decimal("1.00")
    with pytest.raises(TypeError):
        Offer("s_amina", "18", 12, DAY)


def test_replace_checks_the_new_values_too():
    offer = Offer(seller_id="s_amina", unit_price="18", quantity=12, delivery_date=DAY)
    assert replace(offer, unit_price="17.99").unit_price == Decimal("17.99")
    with pytest.raises(ValueError):
        replace(offer, unit_price="17.999")


def test_offer_check_is_falsy_when_invalid_and_unpacks_as_a_pair():
    rejected = OfferCheck(valid=False, reason="below_floor")
    assert not rejected
    assert rejected.reason is RejectionReason.BELOW_FLOOR
    valid, reason = rejected
    assert (valid, reason) == (False, "below_floor")
    assert OfferCheck(valid=True)
    assert tuple(OfferCheck(valid=True)) == (True, None)


def test_offer_check_needs_a_reason_exactly_when_invalid():
    with pytest.raises(ValueError):
        OfferCheck(valid=False)
    with pytest.raises(ValueError):
        OfferCheck(valid=True, reason=RejectionReason.TOO_SOON)
    with pytest.raises(ValueError):
        OfferCheck(valid=False, reason="too_cheap")


def test_rejection_reasons_are_the_stored_strings():
    assert [reason.value for reason in RejectionReason] == [
        "below_floor",
        "over_buyer_cap",
        "over_capacity",
        "too_soon",
        "after_deadline",
    ]
    assert json.dumps({"reason": RejectionReason.OVER_BUYER_CAP}) == '{"reason": "over_buyer_cap"}'


def line(seller_id: str, quantity: int, price: str) -> PlanLine:
    return PlanLine(
        seller_id=seller_id,
        quantity=quantity,
        unit_price=price,
        line_total=Decimal(price) * quantity,
        delivery_date=DAY,
    )


def test_a_plan_line_total_must_be_quantity_times_price():
    assert line("s_amina", 12, "18.00").line_total == Decimal("216.00")
    with pytest.raises(ValueError):
        PlanLine(seller_id="s_amina", quantity=12, unit_price="18.00", line_total="200.00", delivery_date=DAY)


def test_a_plan_refuses_totals_that_do_not_match_its_lines():
    lines = (line("s_priya", 11, "16.00"), line("s_amina", 12, "18.00"))
    plan = Plan(lines=lines, total_quantity=23, total_cost="392.00", complete=True, shortfall=0)
    assert plan.total_cost == Decimal("392.00")
    assert plan.quantities() == {"s_priya": 11, "s_amina": 12}
    with pytest.raises(ValueError):
        replace(plan, total_cost="1.00")
    with pytest.raises(ValueError):
        replace(plan, total_quantity=40)
    with pytest.raises(ValueError):
        replace(plan, complete=False, shortfall=0, reason="short")
    with pytest.raises(ValueError):
        replace(plan, complete=False, shortfall=17)


def test_a_plan_keeps_its_lines_as_a_tuple_and_knows_what_was_asked():
    plan = Plan(
        lines=[line("s_lucia", 10, "22.00")],
        total_quantity=10,
        total_cost="220.00",
        complete=False,
        shortfall=30,
        reason="Only 10 of 40 units can be supplied by 2026-12-10.",
    )
    assert isinstance(plan.lines, tuple)
    assert plan.requested_quantity == 40
    assert hash(plan) == hash(replace(plan))
