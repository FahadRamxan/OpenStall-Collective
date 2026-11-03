"""Payout rails (spec 3.5a): each maker is paid on the rail her country allows, and never captured without one."""

from decimal import Decimal

import pytest

from openstall_paypal import CheckoutRequest, FakeGateway, PaymentError, Share
from openstall_paypal.rails import NO_SANDBOX_PAYPAL_ACCOUNT, payout_item, rail_for, venmo_payouts_simulated

GRACE = Share(
    "op_grace",
    "AUTH-ALL",
    Decimal("203.00"),
    note="Your share of OpenStall order ord_demo",
    payout_rail="venmo",
    venmo_handle="grace-detroit-demo",
)


@pytest.mark.parametrize(
    ("country", "handle", "kind"),
    [
        ("PK", None, "unavailable"),  # Amina, Lahore: until prompt 52 adds Hyperwallet
        ("IN", None, "paypal"),  # Priya, Jaipur
        ("MX", None, "paypal"),  # Lucía, Oaxaca
        ("GB", None, "paypal"),  # Noor, Manchester
        ("US", "grace-detroit-demo", "venmo"),  # Grace, Detroit
        ("US", None, "paypal"),  # a US maker without a Venmo handle
    ],
)
def test_rail_for_each_seed_country(country: str, handle: str | None, kind: str) -> None:
    assert rail_for(country, handle, None, None).kind == kind


def test_pakistan_says_honestly_that_her_rail_is_not_connected_yet() -> None:
    rail = rail_for("PK", None, None, None)

    assert not rail.available
    assert rail.reason == "Payout rail not connected yet (Pakistan)"


def test_on_a_real_money_path_a_paypal_maker_needs_a_paypal_account() -> None:
    assert rail_for("IN", None, None, None, payee_required=True).reason == (
        f"Payout rail not connected yet ({NO_SANDBOX_PAYPAL_ACCOUNT})"
    )
    assert rail_for("IN", None, "priya@example.com", None, payee_required=True).kind == "paypal"
    assert rail_for("GB", None, None, "NOORMERCHANT", payee_required=True).kind == "paypal"
    assert rail_for("US", "grace-detroit-demo", None, None, payee_required=True).kind == "venmo"


def test_an_override_is_honoured_but_never_pays_venmo_without_a_handle_or_outside_the_us() -> None:
    assert rail_for("US", "grace", None, None, override="paypal").kind == "paypal"
    assert rail_for("US", None, None, None, override="venmo").kind == "unavailable"
    assert rail_for("MX", "lucia", None, None, override="venmo").kind == "unavailable"
    assert rail_for("PK", None, None, None, override="hyperwallet").kind == "unavailable"


def test_an_override_never_reaches_pakistan_on_paypal_or_venmo() -> None:
    pakistan = "Payout rail not connected yet (Pakistan)"
    assert rail_for("PK", None, "a@x.com", None, override="paypal", payee_required=True).kind == "unavailable"
    assert rail_for("PK", None, None, None, override="paypal").reason == pakistan  # fake mode too
    assert rail_for("PK", "amina", None, None, override="venmo").reason == pakistan


def test_venmo_item_has_wallet_note_and_user_handle() -> None:
    assert payout_item(GRACE) == {
        "recipient_wallet": "Venmo",
        "recipient_type": "USER_HANDLE",
        "receiver": "grace-detroit-demo",
        "note": "Your share of OpenStall order ord_demo",
        "amount": {"value": "203.00", "currency": "USD"},
        "sender_item_id": "op_grace",
    }


def test_venmo_item_never_uses_phone() -> None:
    item = payout_item(GRACE)

    assert item["recipient_type"] not in ("PHONE", "VENMO_HANDLE")
    assert "PHONE" not in str(item)


def test_a_venmo_item_without_a_handle_is_refused() -> None:
    with pytest.raises(PaymentError) as error:
        payout_item(Share("op_grace", "AUTH-ALL", Decimal("203.00"), payout_rail="venmo"))

    assert error.value.issue == "PAYEE_MISSING"


def test_paypal_item_pays_her_email_or_merchant_id() -> None:
    by_email = payout_item(Share("op_priya", "AUTH-ALL", Decimal("176.00"), payee_email="priya@example.com"))
    by_id = payout_item(Share("op_noor", "AUTH-ALL", Decimal("186.00"), payee_merchant_id="NOORMERCHANT"))

    assert (by_email["recipient_type"], by_email["receiver"]) == ("EMAIL", "priya@example.com")
    assert (by_id["recipient_type"], by_id["receiver"]) == ("PAYPAL_ID", "NOORMERCHANT")
    assert by_email["note"] == "Your share of an OpenStall Collective order."  # a default note when none is given


def test_unavailable_rail_refuses_before_capture() -> None:
    amina = Share("op_amina", "AUTH-ALL", Decimal("216.00"), payout_rail="unavailable")

    with pytest.raises(PaymentError) as error:
        payout_item(amina)
    assert error.value.issue == "PAYOUT_RAIL_UNAVAILABLE"

    # The fake follows the same rule: nothing is captured and no event is sent.
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(
        CheckoutRequest("ord_x", (), "http://x/return", "http://x/cancel")
    ).paypal_order_id
    gateway.approve(paypal_order_id)
    hold = gateway.reserve(paypal_order_id).holds["whole_order"]
    gateway.take_outbox()
    with pytest.raises(PaymentError) as fake_error:
        gateway.pay_share(Share("op_amina", hold, Decimal("0.00"), payout_rail="unavailable"))
    assert fake_error.value.issue == "PAYOUT_RAIL_UNAVAILABLE"
    assert gateway.take_outbox() == []


@pytest.mark.parametrize(
    ("base", "simulated"),
    [("https://api-m.sandbox.paypal.com", True), ("https://api-m.paypal.com", False)],
)
def test_venmo_payouts_are_simulated_only_on_the_sandbox(base: str, simulated: bool) -> None:
    assert venmo_payouts_simulated(base) is simulated
