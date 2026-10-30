"""Signing and verifying trust passports (spec 3.7)."""

import base64
import json
import re

import pytest

from openstall_trust import (
    SIGNATURE_PREFIX,
    generate_keypair,
    load_private_key,
    load_public_key,
    public_key_b64,
    sign_passport,
    verify_passport,
)

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

PRIVATE_B64, PUBLIC_B64 = generate_keypair()
PRIVATE_KEY = load_private_key(PRIVATE_B64)
PUBLIC_KEY = load_public_key(PUBLIC_B64)

# A fixed, obviously fake key (bytes 0..31), so signatures in these tests are the same every run.
FIXED_KEY = load_private_key(base64.b64encode(bytes(range(32))).decode())
FIXED_PUBLIC_KEY = FIXED_KEY.public_key()
FIXED_SIGNATURE = (
    "ed25519:G09tUOPmxZiOhQpPKJIQsunrGMjAvWAf5biWiM09b0Vu_5n6EnxurBNY9IzMnAHGmB05i7zFWFwmvoJ76C-tAQ"
)
BODY = FIXED_SIGNATURE.removeprefix(SIGNATURE_PREFIX)

# Two other spellings of the same 64 bytes, which a lax decoder would accept. The final "Q" holds
# 2 signature bits and 4 spare bits; "R" differs only in a spare bit.
SPARE_BIT_SET = FIXED_SIGNATURE[:-1] + "R"
STANDARD_ALPHABET = SIGNATURE_PREFIX + BODY.replace("-", "+").replace("_", "/")


@pytest.fixture
def signed() -> dict:
    return sign_passport(PASSPORT, PRIVATE_KEY)


def test_sign_then_verify(signed):
    assert verify_passport(signed, PUBLIC_KEY) is True


def test_signature_is_ed25519_prefix_and_unpadded_base64url(signed):
    assert re.fullmatch(r"ed25519:[A-Za-z0-9_-]{86}", signed["signature"])
    assert signed["signature"].startswith(SIGNATURE_PREFIX)


def test_signature_for_a_fixed_key_never_changes():
    # Ed25519 is deterministic. If this changes, every passport already issued stops verifying.
    assert sign_passport(PASSPORT, FIXED_KEY)["signature"] == FIXED_SIGNATURE


def test_signing_returns_a_deep_copy():
    passport = {**PASSPORT, "seeded_history": {"orders_delivered": 40}}
    signed = sign_passport(passport, PRIVATE_KEY)
    assert "signature" not in passport
    passport["seeded_history"]["orders_delivered"] = 99
    assert signed["seeded_history"]["orders_delivered"] == 40
    assert verify_passport(signed, PUBLIC_KEY)


def test_signing_replaces_an_old_signature():
    placeholder = {**PASSPORT, "signature": "ed25519:..."}  # as written in the spec
    first = sign_passport(placeholder, PRIVATE_KEY)
    second = sign_passport(first, FIXED_KEY)
    assert second["signature"] == FIXED_SIGNATURE
    assert verify_passport(second, FIXED_PUBLIC_KEY)
    assert not verify_passport(second, PUBLIC_KEY)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("orders_delivered", 43),
        ("orders_delivered", "42"),
        ("on_time_rate", 1.0),  # the "Change on-time rate to 1.00" button in the demo
        ("on_time_rate", 0.951),
        ("dispute_rate", 0.0),
        ("photo_originality", 0.92),
        ("paypal_account_verified", False),
        ("data_source", "live"),
        ("seller_id", "s_priya"),
        ("issued_at", "2026-11-09T10:00:00Z"),
        ("extra_field", "added after signing"),
    ],
)
def test_changing_any_field_fails(signed, field, value):
    signed[field] = value
    assert verify_passport(signed, PUBLIC_KEY) is False


def test_removing_a_field_fails(signed):
    del signed["data_source"]
    assert verify_passport(signed, PUBLIC_KEY) is False


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p["seeded_history"].update(orders_delivered=41),
        lambda p: p["live_orders"].update(on_time_rate=0.5),
        lambda p: p["photo_checks"].append("web_detection"),
        lambda p: p["photo_checks"].clear(),
    ],
)
def test_changing_a_nested_value_fails(tamper):
    passport = {
        **PASSPORT,
        "seeded_history": {"orders_delivered": 40, "on_time_rate": 0.95},
        "live_orders": {"orders_delivered": 2, "on_time_rate": 1.0},
        "photo_checks": ["hash_only"],
    }
    signed = sign_passport(passport, PRIVATE_KEY)
    tamper(signed)
    assert verify_passport(signed, PUBLIC_KEY) is False


def test_key_order_whitespace_and_number_spelling_do_not_matter(signed):
    text = (
        '{\n  "signature" : "%s",\n'
        '\t"data_source":"seeded_demo",   "paypal_account_verified" : true,\n'
        '  "photo_originality": 0.910, "dispute_rate": 2e-2, "on_time_rate": 0.95,\n'
        '  "orders_delivered": 42.0, "issued_at": "2026-11-08T10:00:00Z", "seller_id": "s_amina"\n}\n'
    ) % signed["signature"]
    assert verify_passport(json.loads(text), PUBLIC_KEY) is True

    reordered = json.loads(json.dumps(dict(reversed(list(signed.items()))), indent=4))
    assert verify_passport(reordered, PUBLIC_KEY) is True


def test_a_passport_that_went_through_a_browser_still_verifies():
    signed = sign_passport({**PASSPORT, "on_time_rate": 1.0, "dispute_rate": 0.0}, PRIVATE_KEY)
    # JSON.parse then JSON.stringify writes 1.0 as 1 and 0.0 as 0.
    from_browser = {**signed, "on_time_rate": 1, "dispute_rate": 0}
    assert verify_passport(from_browser, PUBLIC_KEY) is True


def test_wrong_key_fails(signed):
    _, other_public_b64 = generate_keypair()
    assert verify_passport(signed, load_public_key(other_public_b64)) is False
    assert verify_passport(signed, FIXED_PUBLIC_KEY) is False


def test_other_spellings_really_are_the_same_bytes():
    # Guards two malformed cases below: they only prove something if a lax decoder accepts them.
    def decode(signature: str) -> bytes:
        return base64.urlsafe_b64decode(signature.removeprefix(SIGNATURE_PREFIX) + "==")

    assert decode(SPARE_BIT_SET) == decode(FIXED_SIGNATURE)
    assert decode(STANDARD_ALPHABET) == decode(FIXED_SIGNATURE)
    assert len({SPARE_BIT_SET, STANDARD_ALPHABET, FIXED_SIGNATURE}) == 3


@pytest.mark.parametrize(
    "signature",
    [
        None,
        42,
        ["ed25519:..."],
        {"value": FIXED_SIGNATURE},
        "",
        "ed25519:",
        "ed25519:...",
        BODY,
        "rsa:" + BODY,
        "ED25519:" + BODY,
        " " + FIXED_SIGNATURE,
        FIXED_SIGNATURE + "\n",
        FIXED_SIGNATURE + "==",
        FIXED_SIGNATURE[:-1],
        FIXED_SIGNATURE + "A",
        FIXED_SIGNATURE[:40] + "!" + FIXED_SIGNATURE[40:],
        SPARE_BIT_SET,
        STANDARD_ALPHABET,
        SIGNATURE_PREFIX + "é" * 86,
        SIGNATURE_PREFIX + "A" * 86,
    ],
)
def test_malformed_signatures_fail(signature):
    passport = {**PASSPORT, "signature": signature}
    assert verify_passport(passport, FIXED_PUBLIC_KEY) is False


def test_missing_signature_fails():
    assert verify_passport(PASSPORT, FIXED_PUBLIC_KEY) is False


def test_signature_from_another_passport_fails():
    other = sign_passport({**PASSPORT, "seller_id": "s_priya"}, FIXED_KEY)
    assert verify_passport({**PASSPORT, "signature": other["signature"]}, FIXED_PUBLIC_KEY) is False


@pytest.mark.parametrize("passport", [None, [], "{}", 42])
def test_things_that_are_not_passports_fail(passport):
    assert verify_passport(passport, PUBLIC_KEY) is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {"a", "set"}, b"bytes"])
def test_signed_passports_with_non_json_values_fail(signed, bad):
    signed["on_time_rate"] = bad
    assert verify_passport(signed, PUBLIC_KEY) is False


def test_passing_the_wrong_kind_of_key_is_a_programming_error(signed):
    with pytest.raises(TypeError):
        verify_passport(signed, PRIVATE_KEY)
    with pytest.raises(TypeError):
        verify_passport(signed, PUBLIC_B64)
    with pytest.raises(TypeError):
        sign_passport(PASSPORT, PUBLIC_KEY)
    with pytest.raises(TypeError):
        sign_passport(PASSPORT, PRIVATE_B64)


@pytest.mark.parametrize("not_a_passport", [None, [("seller_id", "s_amina")], "text"])
def test_only_json_objects_can_be_signed(not_a_passport):
    with pytest.raises(TypeError):
        sign_passport(not_a_passport, PRIVATE_KEY)


def test_keys_are_44_character_base64_of_32_bytes():
    assert len(PRIVATE_B64) == len(PUBLIC_B64) == 44
    assert len(base64.b64decode(PRIVATE_B64, validate=True)) == 32
    assert len(base64.b64decode(PUBLIC_B64, validate=True)) == 32


def test_keys_round_trip():
    assert public_key_b64(PRIVATE_KEY) == PUBLIC_B64
    assert public_key_b64(PUBLIC_KEY) == PUBLIC_B64
    assert public_key_b64(load_private_key(PRIVATE_B64)) == PUBLIC_B64


def test_every_key_pair_is_new():
    assert generate_keypair()[0] != generate_keypair()[0]


def test_surrounding_whitespace_in_a_key_is_ignored():
    # Keys pasted into .env files often pick up a stray space or newline.
    assert public_key_b64(load_private_key(f"  {PRIVATE_B64}\n")) == PUBLIC_B64
    assert public_key_b64(load_public_key(f"{PUBLIC_B64}\r\n")) == PUBLIC_B64


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not base64!",
        PRIVATE_B64[:-1],
        # A stray character inside a real key; a lax decoder would skip it.
        PRIVATE_B64[:20] + "!" + PRIVATE_B64[20:],
        base64.b64encode(bytes(31)).decode(),
        base64.b64encode(bytes(33)).decode(),
        # A 64-byte "secret key" (seed plus public key), as libsodium writes it.
        base64.b64encode(bytes(64)).decode(),
        # base64url ("-" and "_"), not the standard base64 that generate_keypair writes.
        base64.urlsafe_b64encode(b"\xfb" * 32).decode(),
    ],
)
def test_bad_keys_are_rejected_without_repeating_them(bad):
    for load in (load_private_key, load_public_key):
        with pytest.raises(ValueError) as error:
            load(bad)
        assert "make_signing_key" in str(error.value)
        if bad:
            assert bad not in str(error.value)


def test_keys_must_be_strings():
    with pytest.raises(TypeError):
        load_private_key(None)
    with pytest.raises(TypeError):
        load_public_key(base64.b64decode(PUBLIC_B64))
