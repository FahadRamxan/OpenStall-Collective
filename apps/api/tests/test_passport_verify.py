"""Signed trust passports anyone can check (prompt 35, spec 3.7): the trust card is the signed passport itself, the
public key is published, and GET /passport/{seller_id}/verify and POST /passport/verify say whether OpenStall's key
signed exactly that card. Change one number and it fails; a delivery signs it again, and it still holds."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from openstall_api.db import session_scope
from openstall_api.delivery import confirm_delivery
from openstall_api.main import app
from openstall_api.models import Order
from openstall_api.passports import FAKE_MODE_KEY_B64
from openstall_api.seed import DEMO_ORDER_ID, MAKERS, seed, seed_demo_order
from openstall_trust import canonical_json, load_private_key, load_public_key, public_key_b64, verify_passport

client = TestClient(app)
FAKE_PUBLIC_KEY = public_key_b64(load_private_key(FAKE_MODE_KEY_B64))
CARD_FIELDS = {
    "seller_id",
    "issued_at",
    "orders_delivered",
    "on_time_rate",
    "dispute_rate",
    "photo_originality",
    "score",
    "live_deliveries",
    "live_on_time",
    "data_source",
    "signature",
}


@pytest.fixture
def seeded(db):
    seed(db, with_amina=True)
    db.commit()
    return db


def card(seller_id: str) -> dict:
    response = client.get(f"/passport/{seller_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_public_key_is_published_and_says_test_mode(seeded):
    key = client.get("/passport/public-key").json()

    assert key["algorithm"] == "Ed25519"
    assert key["public_key"] == FAKE_PUBLIC_KEY
    assert key["test_mode"] is True
    assert "keys sorted at every level" in key["canonical_json"]


@pytest.mark.parametrize("maker", [maker.id for maker in MAKERS])
def test_every_seeded_card_is_exactly_what_was_signed_and_checks_with_the_public_key(seeded, maker):
    signed = card(maker)

    assert set(signed) == CARD_FIELDS  # paypal_account_verified is gone: nothing checks a PayPal account
    assert signed["signature"].startswith("ed25519:")
    assert verify_passport(signed, load_public_key(FAKE_PUBLIC_KEY))
    assert client.get(f"/passport/{maker}/verify").json() == {
        "valid": True,
        "seller_id": maker,
        "reason": "OpenStall signed exactly this card: nothing in it was changed.",
    }


def test_the_score_on_the_card_is_signed_and_matches_the_rates(seeded):
    noor = card("s_noor")

    assert noor["score"] == 0.97  # 0.4 x 0.96 + 0.3 x 1.00 + 0.3 x 0.94 = 0.966
    assert b'"dispute_rate":0,' in canonical_json(noor)  # 0.0 is signed as 0, as a browser writes it


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("orders_delivered", 2500),
        ("on_time_rate", 1.0),
        ("score", 0.99),
        ("data_source", "live"),
        ("live_deliveries", 7),
    ],
)
def test_change_one_number_and_the_check_fails(seeded, change, value):
    tampered = {**card("s_noor"), change: value}

    verdict = client.post("/passport/verify", json=tampered).json()

    assert verdict == {
        "valid": False,
        "seller_id": "s_noor",
        "reason": "The signature does not match: this card was changed after OpenStall signed it, or OpenStall did not "
        "sign it.",
    }


def test_an_untouched_card_sent_back_checks_out(seeded):
    assert client.post("/passport/verify", json=card("s_priya")).json()["valid"] is True


def test_a_card_with_no_signature_or_a_made_up_one_fails(seeded):
    unsigned = {key: value for key, value in card("s_lucia").items() if key != "signature"}
    forged = {**card("s_lucia"), "signature": "ed25519:" + "A" * 86}

    assert client.post("/passport/verify", json=unsigned).json()["reason"] == (
        "This is not a signed trust card: it has no signature."
    )
    assert client.post("/passport/verify", json=forged).json()["valid"] is False


def test_something_far_bigger_than_a_card_is_refused(seeded):
    response = client.post("/passport/verify", json={"seller_id": "s_noor", "padding": "x" * 20_000})

    assert response.status_code == 413


def test_an_unknown_maker_has_no_card_to_check(seeded):
    assert client.get("/passport/s_nobody/verify").status_code == 404


def test_a_delivery_signs_it_again_and_it_still_checks_out(seeded, fakes):
    seed_demo_order(seeded, date(2026, 11, 10))
    seeded.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    client.post(f"/api/dev/fake-paypal/{token}/approve")
    client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve")
    seeded.expire_all()
    priya = next(part.id for part in seeded.get(Order, DEMO_ORDER_ID).parts if part.seller_id == "s_priya")
    before = card("s_priya")
    assert client.post(f"/api/dev/parts/{priya}/proof").status_code == 200
    with session_scope() as session:
        confirm_delivery(session, priya, now=datetime(2026, 12, 1, tzinfo=UTC))

    after = card("s_priya")

    assert (after["orders_delivered"], after["live_deliveries"]) == (68, 1)
    assert after["signature"] != before["signature"]
    assert client.get("/passport/s_priya/verify").json()["valid"] is True
    assert client.post("/passport/verify", json=before).json()["valid"] is True  # the old card was signed too
    assert set(after) == CARD_FIELDS


def test_sandbox_mode_without_a_signing_key_says_so(use_settings):
    use_settings(OPENSTALL_MODE="sandbox")

    response = client.get("/passport/public-key")

    assert response.status_code == 503
    assert "PASSPORT_SIGNING_KEY" in response.json()["detail"]
