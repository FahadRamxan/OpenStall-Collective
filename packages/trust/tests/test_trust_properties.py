"""Property tests for passport signatures (spec 3.7).

Any passport verifies once signed, however its JSON is spelled, and no single change survives.
"""

import base64
import copy
import json

from hypothesis import given, settings
from hypothesis import strategies as st

from openstall_trust import (
    SIGNATURE_PREFIX,
    generate_keypair,
    load_private_key,
    load_public_key,
    sign_passport,
    verify_passport,
)

_private_b64, _public_b64 = generate_keypair()
PRIVATE_KEY = load_private_key(_private_b64)
PUBLIC_KEY = load_public_key(_public_b64)

# What a passport can hold after json.loads.
json_leaves = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=12)
)
json_values = st.recursive(
    json_leaves,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
passports = st.dictionaries(
    st.text(max_size=12).filter(lambda key: key != "signature"),
    json_values,
    min_size=1,
    max_size=8,
)

# Signing is fast; the deadline only adds flakiness on a slow CI machine.
checks = settings(deadline=None, max_examples=200)


def same_json(a, b) -> bool:
    """Equal as JSON values: numbers compare by value (1 equals 1.0), but true is not 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_json(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def nodes(value, path=()):
    """Every value inside a JSON value, the root included, with its path of keys and indexes."""
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from nodes(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nodes(child, (*path, index))


def at(value, path):
    for step in path:
        value = value[step]
    return value


def reversed_keys(value):
    """The same JSON value with the keys of every object in reverse order."""
    if isinstance(value, dict):
        return {key: reversed_keys(value[key]) for key in reversed(value)}
    if isinstance(value, list):
        return [reversed_keys(item) for item in value]
    return value


@checks
@given(passports)
def test_signed_passports_verify(passport):
    assert verify_passport(sign_passport(passport, PRIVATE_KEY), PUBLIC_KEY) is True


@checks
@given(passports, st.sampled_from([None, 0, 2, "\t"]))
def test_key_order_and_whitespace_never_matter(passport, indent):
    signed = sign_passport(passport, PRIVATE_KEY)
    text = json.dumps(reversed_keys(signed), indent=indent)
    assert verify_passport(json.loads(text), PUBLIC_KEY) is True


@checks
@given(passports, st.data())
def test_any_single_change_breaks_the_signature(passport, data):
    signed = sign_passport(passport, PRIVATE_KEY)
    tampered = copy.deepcopy(signed)
    change = data.draw(st.sampled_from(["replace", "remove", "add"]), label="change")
    if change == "add":
        homes = [path for path, node in nodes(signed) if isinstance(node, (dict, list))]
        target = at(tampered, data.draw(st.sampled_from(homes), label="into"))
        value = data.draw(json_values, label="value")
        if isinstance(target, list):
            target.append(value)
        else:
            key = data.draw(st.text(max_size=8).filter(lambda k: k not in target), label="key")
            target[key] = value
    else:
        fields = [path for path, _ in nodes(signed) if path not in {(), ("signature",)}]
        path = data.draw(st.sampled_from(fields), label="field")
        parent, key = at(tampered, path[:-1]), path[-1]
        if change == "remove":
            del parent[key]
        else:
            old = parent[key]
            parent[key] = data.draw(json_values.filter(lambda new: not same_json(new, old)), label="new")
    assert verify_passport(tampered, PUBLIC_KEY) is False


@checks
@given(passports, st.integers(min_value=0, max_value=64 * 8 - 1))
def test_any_flipped_signature_bit_fails(passport, bit):
    signed = sign_passport(passport, PRIVATE_KEY)
    raw = bytearray(base64.urlsafe_b64decode(signed["signature"].removeprefix(SIGNATURE_PREFIX) + "=="))
    raw[bit // 8] ^= 1 << (bit % 8)
    signed["signature"] = SIGNATURE_PREFIX + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    assert verify_passport(signed, PUBLIC_KEY) is False
