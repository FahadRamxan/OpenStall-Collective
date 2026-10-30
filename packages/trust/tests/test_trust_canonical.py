"""Canonical JSON: the bytes a passport signature covers (spec 3.7)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from openstall_trust import canonical_json
from openstall_trust.canonical import MAX_DEPTH

# The example passport from spec 3.7, before signing.
PASSPORT = {
    "seller_id": "s_amina",
    "issued_at": "2026-11-08T10:00:00Z",
    "orders_delivered": 42,
    "on_time_rate": 0.95,
    "dispute_rate": 0.02,
    "photo_originality": 0.91,
    "paypal_account_verified": True,
    "data_source": "seeded_demo",
}


def test_spec_passport_bytes():
    # Issued passports must keep verifying, so these bytes may never change.
    assert canonical_json(PASSPORT) == (
        b'{"data_source":"seeded_demo","dispute_rate":0.02,"issued_at":"2026-11-08T10:00:00Z",'
        b'"on_time_rate":0.95,"orders_delivered":42,"paypal_account_verified":true,'
        b'"photo_originality":0.91,"seller_id":"s_amina"}'
    )


def test_keys_are_sorted_at_every_level_without_whitespace():
    passport = {"b": 1, "a": {"d": [3, {"f": 4, "e": 5}], "c": None}}
    assert canonical_json(passport) == b'{"a":{"c":null,"d":[3,{"e":5,"f":4}]},"b":1}'


def test_key_order_does_not_change_the_bytes():
    reordered = dict(reversed(list(PASSPORT.items())))
    assert canonical_json(reordered) == canonical_json(PASSPORT)


def test_only_the_top_level_signature_is_left_out():
    passport = {"signature": "ed25519:abc", "evidence": {"signature": "kept"}}
    assert canonical_json(passport) == b'{"evidence":{"signature":"kept"}}'


def test_text_is_utf8_not_escaped():
    passport = {"seller": "Lucía", "city": "لاہور", "note": 'line\nbreak "quoted"'}
    assert canonical_json(passport) == (
        '{"city":"لاہور","note":"line\\nbreak \\"quoted\\"","seller":"Lucía"}'.encode()
    )


def test_whole_number_floats_are_written_as_integers():
    # A browser turns 1.0 into 1; the bytes must not care which one arrives.
    passport = {"a": 1.0, "b": 0.0, "c": -0.0, "d": 0.95, "e": True, "f": 1e300, "g": [2.0]}
    assert canonical_json(passport) == b'{"a":1,"b":0,"c":0,"d":0.95,"e":true,"f":1e+300,"g":[2]}'
    assert canonical_json({"rate": 1.0}) == canonical_json({"rate": 1})


def test_whole_floats_become_integers_only_up_to_2_53():
    # Signed bytes must never change. Above 2**53 a float keeps Python's spelling; such numbers do
    # not survive a browser round trip (docs/decisions.md).
    assert canonical_json({"n": 2.0**53}) == b'{"n":9007199254740992}'
    assert canonical_json({"n": -(2.0**53)}) == b'{"n":-9007199254740992}'
    assert canonical_json({"n": 2.0**53 + 2}) == b'{"n":9007199254740994.0}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_are_rejected(bad):
    with pytest.raises(ValueError):
        canonical_json({"on_time_rate": bad})
    with pytest.raises(ValueError):
        canonical_json({"history": [{"rate": bad}]})


@pytest.mark.parametrize(
    "passport",
    [
        {1: "number key"},
        {"nested": {2: "number key"}},
        {"photos": {"a.jpg", "b.jpg"}},
        {"raw": b"bytes"},
        {"score": Decimal("0.95")},
        {"issued_at": datetime(2026, 11, 8, tzinfo=UTC)},
    ],
)
def test_values_that_are_not_plain_json_are_rejected(passport):
    with pytest.raises(TypeError):
        canonical_json(passport)


@pytest.mark.parametrize("not_an_object", [[1, 2], "text", None, 42])
def test_only_json_objects_are_passports(not_an_object):
    with pytest.raises(TypeError):
        canonical_json(not_an_object)


def test_lone_surrogates_are_rejected():
    with pytest.raises(ValueError):
        canonical_json({"name": "\ud800"})


def _nested(levels: int) -> dict:
    """A passport with this many objects and arrays nested inside each other, itself included."""
    value: list = []
    for _ in range(levels - 2):
        value = [value]
    return {"deep": value}


def test_deep_nesting_is_rejected():
    assert canonical_json(_nested(MAX_DEPTH))
    with pytest.raises(ValueError):
        canonical_json(_nested(MAX_DEPTH + 1))


def test_input_is_left_unchanged():
    passport = {"signature": "ed25519:abc", "on_time_rate": 1.0, "history": [2.0]}
    canonical_json(passport)
    assert passport == {"signature": "ed25519:abc", "on_time_rate": 1.0, "history": [2.0]}
    assert isinstance(passport["on_time_rate"], float)
