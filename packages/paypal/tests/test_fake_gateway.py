"""FakeGateway: PayPal's order flow without the network, the same on every run, with every call recorded."""

from dataclasses import replace
from decimal import Decimal

import pytest

from openstall_paypal.gateway import (
    Capture,
    CheckoutPart,
    CheckoutRequest,
    FakeGateway,
    PaymentError,
    PaymentGateway,
)

ORDER = CheckoutRequest(
    order_id="ord_demo",
    parts=(
        CheckoutPart("op_001", Decimal("216.00"), "12 cushion covers, Amina", "MADE_UP_MERCHANT_AMINA"),
        CheckoutPart("op_002", Decimal("176.00"), "11 cushion covers, Priya", "MADE_UP_MERCHANT_PRIYA"),
    ),
    return_url="http://localhost:3000/approve/ord_demo/return",
    cancel_url="http://localhost:3000/approve/ord_demo?cancelled=1",
)


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
    assert gateway.get_order_status(first.paypal_order_id) == "APPROVED"


def test_capture_needs_the_buyers_approval_and_happens_only_once():
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    assert gateway.get_order_status(paypal_order_id) == "CREATED"

    with pytest.raises(PaymentError) as not_approved:
        gateway.capture(paypal_order_id)
    assert not_approved.value.issue == "ORDER_NOT_APPROVED"

    gateway.approve(paypal_order_id)
    assert gateway.capture(paypal_order_id) == Capture(
        paypal_order_id, {"op_001": f"{paypal_order_id}-CAP-1", "op_002": f"{paypal_order_id}-CAP-2"}
    )
    assert gateway.get_order_status(paypal_order_id) == "COMPLETED"

    with pytest.raises(PaymentError) as again:
        gateway.capture(paypal_order_id)
    assert again.value.issue == "ORDER_ALREADY_CAPTURED"


def test_an_unknown_order_is_not_found():
    with pytest.raises(PaymentError) as error:
        FakeGateway().get_order_status("FAKE-NO-SUCH-ORDER")

    assert error.value.issue == "RESOURCE_NOT_FOUND"


def test_every_gateway_call_is_recorded_in_order():
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    gateway.approve(paypal_order_id)
    gateway.get_order_status(paypal_order_id)
    gateway.capture(paypal_order_id)

    assert gateway.calls == [
        ("create_checkout", ORDER),
        ("get_order_status", paypal_order_id),
        ("capture", paypal_order_id),
    ]


def test_the_total_is_the_sum_of_the_parts_to_the_cent():
    assert ORDER.total_usd == Decimal("392.00")
