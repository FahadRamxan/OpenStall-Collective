# Decisions

Design choices the spec leaves open, and the reason for each. Add new entries at the end.

## 2026-10-30 · Trust passports: score, canonical JSON and signatures (prompt 35)

Code: `packages/trust/openstall_trust`. Spec: section 3.7.

- **Score.** `trust_score` is the spec 3.7 formula and returns a `Decimal` rounded half-up to 2 places. Each rate is read through `str()`, so 0.82 counts as 0.82 and not as its binary value 0.8199…. Otherwise rates such as 0.82, 0.02 and 0.91 (exactly 0.895) would score 0.89 instead of 0.90. Rates outside 0 to 1, NaN, infinities and booleans raise an error instead of being clamped, because they mean a bug upstream.
- **What gets signed.** The signature covers `canonical_json(passport)`: keys sorted at every level, no whitespace, text as UTF-8 (not `\u` escapes), and the top-level `signature` field left out. Nested fields named `signature` are signed like any other field.
- **Whole-number floats are written as integers** (1.0 as 1). Browsers do the same, so a passport that goes through `JSON.parse` and `JSON.stringify` (the tamper-check panel, prompt 38) still verifies. Rates of exactly 1.0 or 0.0 will be common once prompt 36 adds live deliveries. Whole numbers above 2**53 are left as they are, because JavaScript cannot hold them exactly.
- **Not RFC 8785.** Other numbers keep Python's spelling, which matches JavaScript for everything a passport holds (counts, and rates of 0.0001 or more). Someone checking passports outside Python should use `POST /passport/verify` or port `canonical_json` exactly.
- **Only plain JSON can be signed.** NaN and Infinity raise `ValueError`. Non-string keys, sets, bytes, `Decimal` and `datetime` raise `TypeError`: convert them first (`float(score)`, ISO time strings). `Decimal` is refused because encoders disagree on it (Pydantic writes a string, FastAPI's encoder a float), so its signed form would be ambiguous.
- **Nesting is capped at 32 objects or arrays.** `POST /passport/verify` will accept JSON from anyone, and real passports nest one or two levels.
- **Signature format.** `ed25519:` followed by the 64 signature bytes in base64url without padding (86 characters). Verification accepts only that exact spelling. Python's decoder skips stray characters and ignores the spare bits of the last character, so without this check one signature would have many accepted spellings.
- **Keys.** Raw 32-byte Ed25519 keys as standard base64 (44 characters), not PEM: one short line fits in `.env` and in the host's settings, and it is the form most Ed25519 libraries take. `PASSPORT_SIGNING_KEY` holds the private key, and `scripts/make_signing_key.py` makes a new pair. Loading rejects anything else, base64url included, with an error that never repeats the input, since the input may be the secret.
- **`verify_passport` never raises for a bad passport.** Tampering, a missing or malformed signature, content that is not plain JSON, or another key's signature all return `False`. Passing something that is not an Ed25519 public key is a programming error and raises `TypeError`.
- **The trust package reads no settings.** The API reads `PASSPORT_SIGNING_KEY` and passes keys in, so tests and scripts can use their own keys.
