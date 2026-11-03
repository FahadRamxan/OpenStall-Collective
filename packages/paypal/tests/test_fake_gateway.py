"""FakeGateway: PayPal's pay-on-proof flow without the network, the same on every run, with every call recorded."""

from dataclasses import replace
from decimal import Decimal

import pytest

from openstall_paypal.gateway import (
    CheckoutPart,
    CheckoutRequest,
    FakeGateway,
    OrderState,
    Payment,
    PaymentError,
    PaymentGateway,
    Reservation,
    Share,
)

ORDER = CheckoutRequest(
    order_id="ord_demo",
    parts=(
        CheckoutPart("op_001", Decimal("216.00"), "12 × Cushion cover, Amina", "MADE_UP_MERCHANT_AMINA"),
        CheckoutPart("op_002", Decimal("176.00"), "11 × Cushion cover, Priya", "MADE_UP_MERCHANT_PRIYA"),
    ),
    return_url="http://localhost:3000/approve/ord_demo/return",
    cancel_url="http://localhost:3000/approve/ord_demo?cancelled=1",
)


def reserved(gateway: FakeGateway) -> Reservation:
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    gateway.approve(paypal_order_id)
    return gateway.reserve(paypal_order_id)


def share(reservation: Reservation, reference_id: str, part_id: str) -> Share:
    return Share(part_id=part_id, hold_id=reservation.holds[reference_id], amount_usd=Decimal("216.00"))


def test_follows_the_payment_gateway_interface():
    assert isinstance(FakeGateway(), PaymentGateway)


def test_checkout_sends_the_buyer_to_the_simulated_paypal_page():
    checkout = FakeGateway("https://openstall.example/").create_checkout(ORDER)

    assert checkout.paypal_order_id.startswith("FAKE-")
    assert checkout.approval_url == f"https://openstall.example/fake-paypal?token={checkout.paypal_order_id}"


def test_paypal_order_ids_are_the_same_on_every_run_and_differ_between_orders():
    first = FakeGateway().create_checkout(ORDER)

    assert FakeGateway().create_checkout(ORDER) == first
    assert FakeGateway().create_checkout(replace(ORDER, order_id="ord_other")).paypal_order_id != first.paypal_order_id


def test_a_repeated_checkout_returns_the_same_paypal_order_unchanged():
    gateway = FakeGateway()
    first = gateway.create_checkout(ORDER)
    gateway.approve(first.paypal_order_id)

    assert gateway.create_checkout(ORDER) == first
    assert gateway.get_order(first.paypal_order_id).status == "APPROVED"


def test_the_simulated_page_shows_the_order_as_the_buyer_sees_it():
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id

    view = gateway.view(paypal_order_id)

    assert view.status == "PAYER_ACTION_REQUIRED"
    assert view.request == ORDER
    assert gateway.approve(paypal_order_id).status == "APPROVED"
    assert gateway.approve(paypal_order_id).status == "APPROVED"


def test_reserving_needs_the_buyers_approval():
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id

    with pytest.raises(PaymentError) as error:
        gateway.reserve(paypal_order_id)

    assert error.value.issue == "ORDER_NOT_APPROVED"


def test_reserving_holds_each_share_and_a_repeat_returns_the_same_holds():
    gateway = FakeGateway()
    reservation = reserved(gateway)
    paypal_order_id = reservation.paypal_order_id

    assert reservation.holds == {"op_001": f"{paypal_order_id}-AUTH-1", "op_002": f"{paypal_order_id}-AUTH-2"}
    assert gateway.reserve(paypal_order_id) == reservation
    assert gateway.get_order(paypal_order_id) == OrderState("COMPLETED", reservation.holds)


def test_a_share_is_paid_once_however_often_it_is_asked():
    gateway = FakeGateway()
    amina = share(reserved(gateway), "op_001", "op_amina")

    first = gateway.pay_share(amina)

    assert first == Payment(capture_id=f"{amina.hold_id}-CAP")
    assert gateway.pay_share(amina) == first


def test_a_captured_hold_cannot_be_captured_again_for_another_share_or_released():
    gateway = FakeGateway()
    amina = share(reserved(gateway), "op_001", "op_amina")
    gateway.pay_share(amina)

    with pytest.raises(PaymentError) as again:
        gateway.pay_share(replace(amina, part_id="op_someone_else"))
    with pytest.raises(PaymentError) as release:
        gateway.release_share(amina)

    assert again.value.issue == "AUTHORIZATION_ALREADY_CAPTURED"
    assert release.value.issue == "AUTHORIZATION_ALREADY_CAPTURED"


def test_a_released_share_is_never_paid():
    gateway = FakeGateway()
    lucia = share(reserved(gateway), "op_002", "op_lucia")
    gateway.release_share(lucia)
    gateway.release_share(lucia)  # releasing again changes nothing

    with pytest.raises(PaymentError) as error:
        gateway.pay_share(lucia)

    assert error.value.issue == "AUTHORIZATION_VOIDED"


def test_releasing_one_share_leaves_the_others_payable():
    gateway = FakeGateway()
    reservation = reserved(gateway)
    gateway.release_share(share(reservation, "op_002", "op_priya"))

    assert gateway.pay_share(share(reservation, "op_001", "op_amina")).capture_id.endswith("-AUTH-1-CAP")


@pytest.mark.parametrize("call", ["get_order", "reserve", "view", "approve"])
def test_an_unknown_order_is_not_found(call):
    with pytest.raises(PaymentError) as error:
        getattr(FakeGateway(), call)("FAKE-NO-SUCH-ORDER")

    assert error.value.issue == "RESOURCE_NOT_FOUND"


def test_every_gateway_call_is_recorded_in_order_and_the_buyers_clicks_are_not():
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    gateway.view(paypal_order_id)
    gateway.approve(paypal_order_id)
    gateway.get_order(paypal_order_id)
    reservation = gateway.reserve(paypal_order_id)
    amina = share(reservation, "op_001", "op_amina")
    gateway.pay_share(amina)

    assert gateway.calls == [
        ("create_checkout", ORDER),
        ("get_order", paypal_order_id),
        ("reserve", paypal_order_id),
        ("pay_share", amina),
    ]


def test_the_total_is_the_sum_of_the_parts_to_the_cent():
    assert ORDER.total_usd == Decimal("392.00")
