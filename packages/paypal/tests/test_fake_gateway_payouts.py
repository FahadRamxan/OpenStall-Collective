"""FakeGateway on the payouts path, the one we run: one authorization for the whole order, a partial capture per
share (final_capture only on the last), a void of whatever is left, and a payout to each maker's rail."""

from decimal import Decimal
from typing import Any

import pytest

from openstall_paypal.gateway import (
    WHOLE_ORDER,
    Advance,
    AdvancePayment,
    CheckoutPart,
    CheckoutRequest,
    FakeGateway,
    PaymentError,
    Reservation,
    Share,
)

ORDER = CheckoutRequest(
    order_id="ord_demo",
    parts=(
        CheckoutPart("op_001", Decimal("216.00"), "12 × Cushion cover, Amina"),
        CheckoutPart("op_002", Decimal("176.00"), "11 × Cushion cover, Priya"),
        CheckoutPart("op_003", Decimal("220.00"), "10 × Cushion cover, Lucía"),
        CheckoutPart("op_004", Decimal("203.00"), "7 × Cushion cover, Grace"),
    ),
    return_url="http://localhost:3000/approve/ord_demo/return",
    cancel_url="http://localhost:3000/approve/ord_demo?cancelled=1",
)


def reserved(gateway: FakeGateway) -> Reservation:
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    gateway.approve(paypal_order_id)
    gateway.take_outbox()
    return gateway.reserve(paypal_order_id)


def share(reservation: Reservation, part_id: str, amount: str, *, last: bool = False, **rail: str) -> Share:
    return Share(
        part_id=part_id,
        hold_id=reservation.holds[WHOLE_ORDER],
        amount_usd=Decimal(amount),
        note="Your share of OpenStall order ord_demo",
        last=last,
        **rail,  # type: ignore[arg-type]  # payout_rail is a Literal
    )


def events(gateway: FakeGateway, kind: str) -> list[dict[str, Any]]:
    return [event["resource"] for event in gateway.take_outbox() if event["event_type"] == kind]


def test_one_authorization_holds_the_whole_order() -> None:
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    gateway.approve(paypal_order_id)
    gateway.take_outbox()

    reservation = gateway.reserve(paypal_order_id)

    assert gateway.path == "payouts"
    assert reservation.holds == {WHOLE_ORDER: f"{paypal_order_id}-AUTH"}
    assert reservation.hold_for("op_003") == f"{paypal_order_id}-AUTH"
    [authorized] = events(gateway, "PAYMENT.AUTHORIZATION.CREATED")
    assert authorized["id"] == f"{paypal_order_id}-AUTH"
    assert authorized["amount"] == {"currency_code": "USD", "value": "815.00"}
    assert gateway.authorization(authorized["id"]) == (Decimal("815.00"), Decimal("0.00"), "CREATED")


def test_each_share_is_a_partial_capture_and_only_the_last_is_final() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()

    first = gateway.pay_share(share(reservation, "op_priya", "176.00"))
    second = gateway.pay_share(share(reservation, "op_lucia", "220.00"))
    last = gateway.pay_share(share(reservation, "op_grace", "203.00", last=True))

    hold = reservation.holds[WHOLE_ORDER]
    assert [first.capture_id, second.capture_id, last.capture_id] == [f"{hold}-CAP-1", f"{hold}-CAP-2", f"{hold}-CAP-3"]
    captures = events(gateway, "PAYMENT.CAPTURE.COMPLETED")
    assert [(c["invoice_id"], c["amount"]["value"], c["final_capture"]) for c in captures] == [
        ("op_priya", "176.00", False),
        ("op_lucia", "220.00", False),
        ("op_grace", "203.00", True),
    ]
    assert gateway.authorization(hold) == (Decimal("815.00"), Decimal("599.00"), "CAPTURED")
    with pytest.raises(PaymentError) as closed:  # the final capture closed the hold
        gateway.pay_share(share(reservation, "op_late", "1.00"))
    assert closed.value.issue == "AUTHORIZATION_ALREADY_CAPTURED"


def test_capture_beyond_the_remaining_authorization_is_refused() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.pay_share(share(reservation, "op_lucia", "700.00"))
    gateway.take_outbox()

    with pytest.raises(PaymentError) as error:
        gateway.pay_share(share(reservation, "op_grace", "203.00"))

    assert error.value.issue == "EXCEEDS_REMAINING_AUTHORIZATION"
    assert gateway.take_outbox() == []
    assert gateway.authorization(reservation.holds[WHOLE_ORDER])[1] == Decimal("700.00")


def test_releasing_a_middle_share_captures_and_voids_nothing() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()

    gateway.release_share(share(reservation, "op_lucia", "220.00", last=False))

    assert gateway.take_outbox() == []
    assert gateway.authorization(reservation.holds[WHOLE_ORDER]) == (Decimal("815.00"), Decimal("0.00"), "CREATED")
    assert gateway.pay_share(share(reservation, "op_priya", "176.00")).capture_id.endswith("-CAP-1")


def test_last_release_voids_the_remainder() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.pay_share(share(reservation, "op_priya", "176.00"))
    gateway.release_share(share(reservation, "op_lucia", "220.00"))
    gateway.take_outbox()

    gateway.release_share(share(reservation, "op_grace", "203.00", last=True))
    gateway.release_share(share(reservation, "op_grace", "203.00", last=True))  # again: nothing more happens

    [voided] = events(gateway, "PAYMENT.AUTHORIZATION.VOIDED")
    assert voided["id"] == reservation.holds[WHOLE_ORDER]
    assert voided["amount"]["value"] == "639.00"  # 815.00 less Priya's 176.00
    with pytest.raises(PaymentError) as error:
        gateway.pay_share(share(reservation, "op_amina", "216.00"))
    assert error.value.issue == "AUTHORIZATION_VOIDED"


def test_paying_a_share_twice_pays_once() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    priya = share(reservation, "op_priya", "176.00")
    gateway.take_outbox()

    first = gateway.pay_share(priya)
    again = gateway.pay_share(priya)

    assert again == first
    assert len(events(gateway, "PAYMENT.CAPTURE.COMPLETED")) == 1
    assert gateway.authorization(reservation.holds[WHOLE_ORDER])[1] == Decimal("176.00")
    with pytest.raises(PaymentError):  # and a paid share is never released
        gateway.release_share(priya)


def test_payout_item_succeeded_event_is_sent() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()

    payment = gateway.pay_share(share(reservation, "op_grace", "203.00", payout_rail="venmo", venmo_handle="grace-d"))

    [item] = events(gateway, "PAYMENT.PAYOUTS-ITEM.SUCCEEDED")
    assert item["transaction_status"] == "SUCCESS"
    assert item["payout_batch_id"] == payment.payout_batch_id
    assert item["payout_item"]["sender_item_id"] == "op_grace"
    assert item["payout_item"]["recipient_wallet"] == "Venmo"
    assert item["payout_item"]["receiver"] == "grace-d"
    assert item["payout_item"]["amount"] == {"currency": "USD", "value": "203.00"}
    assert payment.payout_rail == "venmo" and not payment.payout_simulated


def test_payout_events_have_ids_of_their_own() -> None:
    """Each payout item event gets its own id, so the webhook handler never takes the second for a repeat."""
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()
    gateway.pay_share(share(reservation, "op_priya", "176.00"))
    gateway.pay_share(share(reservation, "op_lucia", "220.00"))

    ids = [event["id"] for event in gateway.take_outbox()]

    assert len(ids) == len(set(ids)) == 4


def test_a_hyperwallet_share_is_captured_and_her_bank_payout_simulated() -> None:
    """Prompt 52: Amina in Pakistan is paid to her bank through Hyperwallet, which is simulated. Her capture is
    as real as anyone's; no PayPal payout is sent for her, so no payout event follows."""
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()
    amina = share(reservation, "op_amina", "216.00", payout_rail="hyperwallet")

    payment = gateway.pay_share(amina)

    assert (payment.payout_rail, payment.payout_simulated, payment.payout_batch_id) == ("hyperwallet", True, None)
    kinds = [event["event_type"] for event in gateway.take_outbox()]
    assert kinds == ["PAYMENT.CAPTURE.COMPLETED"]
    assert gateway.authorization(reservation.holds[WHOLE_ORDER])[1] == Decimal("216.00")
    assert gateway.pay_share(amina) == payment  # once


def test_a_share_no_rail_can_reach_is_never_captured() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()

    with pytest.raises(PaymentError) as error:
        gateway.pay_share(share(reservation, "op_amina", "216.00", payout_rail="unavailable"))

    assert error.value.issue == "PAYOUT_RAIL_UNAVAILABLE"
    assert gateway.take_outbox() == []
    assert gateway.authorization(reservation.holds[WHOLE_ORDER])[1] == Decimal("0.00")


# A materials advance (prompt 37): paid by the platform, ahead of her proof; nothing is captured for it.


def test_an_advance_is_paid_once_and_nothing_is_captured_for_it() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    grace = share(reservation, "op_grace", "203.00", payee_email="grace@example.com")

    first = gateway.pay_advance(Advance(grace, Decimal("50.75")))
    again = gateway.pay_advance(Advance(grace, Decimal("50.75")))

    assert first == again and isinstance(first, AdvancePayment) and first.payout_rail == "paypal"
    assert gateway.authorization(reservation.holds[WHOLE_ORDER]) == (Decimal("815.00"), Decimal("0.00"), "CREATED")


def test_a_share_paid_ahead_is_captured_whole_and_paid_out_the_rest() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()
    grace = Share(
        part_id="op_grace",
        hold_id=reservation.holds[WHOLE_ORDER],
        amount_usd=Decimal("203.00"),
        payee_email="grace@example.com",
        paid_ahead_usd=Decimal("50.75"),
    )

    gateway.pay_share(grace)

    assert gateway.authorization(reservation.holds[WHOLE_ORDER])[1] == Decimal("203.00")
    [payout] = events(gateway, "PAYMENT.PAYOUTS-ITEM.SUCCEEDED")
    assert payout["payout_item"]["amount"] == {"currency": "USD", "value": "152.25"}


def test_no_advance_for_a_maker_no_rail_reaches() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)

    with pytest.raises(PaymentError, match="no payout rail"):
        amina = share(reservation, "op_amina", "216.00", payout_rail="unavailable")
        gateway.pay_advance(Advance(amina, Decimal("54.00")))


def test_an_advance_through_hyperwallet_is_simulated() -> None:
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.take_outbox()

    paid = gateway.pay_advance(Advance(share(reservation, "op_amina", "216.00", payout_rail="hyperwallet"), Decimal("54.00")))

    assert paid == AdvancePayment(None, "hyperwallet", payout_simulated=True)
    assert gateway.take_outbox() == []
