"""Canonical JSON: the exact bytes a passport signature covers (spec 3.7).

The same passport content always gives the same bytes, whatever its key order, whitespace or
number spelling, so a signature checks the content and nothing else.
"""

import json
from collections.abc import Mapping
from typing import Any

SIGNATURE_FIELD = "signature"

# Passports nest a level or two. The limit keeps hostile input to the verify endpoint cheap.
MAX_DEPTH = 32

# JSON has one number type, and JavaScript writes 1.0 as 1. A browser writes every whole float up
# to 2**53 as its exact integer, so whole floats in that range are written as integers here too.
# Bigger whole numbers do not survive a trip through a browser (see docs/decisions.md).
_EXACT_INTEGERS = 2**53


def canonical_json(passport: Mapping[str, Any]) -> bytes:
    """Return the bytes a passport's signature covers.

    Keys are sorted at every level, there is no whitespace, text is UTF-8 rather than \\u escapes,
    and the top-level "signature" field is left out. Whole-number floats up to 2**53 are written as
    integers (1.0 as 1), the way browsers write them, so a passport that went through JavaScript
    still verifies.

    Raises TypeError for anything that is not plain JSON (non-string keys, sets, bytes, Decimal:
    convert those first) and ValueError for NaN, Infinity, or objects and arrays nested more than
    MAX_DEPTH deep.
    """
    if not isinstance(passport, Mapping):
        raise TypeError(f"a passport is a JSON object, not {type(passport).__name__}")
    content = {key: value for key, value in passport.items() if key != SIGNATURE_FIELD}
    text = json.dumps(
        _plain(content, depth=0),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def _plain(value: Any, depth: int) -> Any:
    """Check the nesting and key types, and write whole-number floats as integers."""
    if isinstance(value, (Mapping, list, tuple)) and depth >= MAX_DEPTH:
        raise ValueError(f"passport nests more than {MAX_DEPTH} objects or arrays deep")
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("passport keys must be strings")
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    if isinstance(value, float) and value.is_integer() and abs(value) <= _EXACT_INTEGERS:
        return int(value)
    return value
