"""Tracking on the PayPal order (prompt 33): a courier's name as PayPal's carrier code, which tracker is ours, and the
fake gateway following PayPal's rules for it."""

from decimal import Decimal

import pytest
from paypal.models.enums import ShipmentCarrier

from openstall_paypal import (
    CheckoutPart,
    CheckoutRequest,
    FakeGateway,
    PaymentError,
    Share,
    Tracking,
    carrier_code,
    tracker_for,
)
from openstall_paypal.tracking import CARRIERS, UNNAMED


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("TCS", ("TCS", None)),
        ("TCS Express", ("TCS", None)),
        ("India Post", ("INDIA_POST", None)),
        ("india  post", ("INDIA_POST", None)),
        ("Estafeta", ("MEX_ESTAFETA", None)),
        ("Royal Mail", ("ROYAL_MAIL", None)),
        ("USPS", ("USPS", None)),
        ("DHL Express", ("DHL", None)),
        ("Leopards Courier", ("OTHER", "Leopards Courier")),
        ("  Swyft   Logistics ", ("OTHER", "Swyft Logistics")),
        ("OTHER", ("OTHER", UNNAMED)),
        (None, ("OTHER", UNNAMED)),
        ("", ("OTHER", UNNAMED)),
    ],
)
def test_a_couriers_name_becomes_paypals_carrier_or_other_with_its_name(name, code):
    assert carrier_code(name) == code


def test_every_mapped_carrier_is_a_member_of_the_sdks_own_list():
    assert all(isinstance(carrier, ShipmentCarrier) for carrier in CARRIERS.values())
    assert {carrier.value for carrier in CARRIERS.values()} >= {"TCS", "INDIA_POST", "MEX_ESTAFETA", "ROYAL_MAIL", "USPS"}


def test_ours_is_the_tracker_with_her_number_else_the_one_new_since_we_looked():
    assert tracker_for(["CAP-1-7712345678", "CAP-2-EE123456789IN"], "EE123456789IN") == "CAP-2-EE123456789IN"
    assert tracker_for(["T-OLD", "T-NEW"], "EE123456789IN", known=["T-OLD"]) == "T-NEW"
    assert tracker_for(["T-OLD", "T-A", "T-B"], "EE123456789IN", known=["T-OLD"]) is None  # two new: cannot tell
    assert tracker_for(["T-OLD"], "EE123456789IN", known=["T-OLD"]) is None  # nothing new


def test_reading_an_order_back_never_takes_another_makers_tracker_for_hers():
    assert tracker_for(["CAP-1-7712345678"], "EE123456789IN") is None


ORDER = CheckoutRequest(
    order_id="ord_demo",
    parts=(
        CheckoutPart("op_001", Decimal("216.00"), "12 × Cushion cover, Amina"),
        CheckoutPart("op_002", Decimal("176.00"), "11 × Cushion cover, Priya"),
    ),
    return_url="http://localhost:3000/approve/ord_demo/return",
    cancel_url="http://localhost:3000/approve/ord_demo?cancelled=1",
)


@pytest.fixture
def paid():
    """A fake order, approved and reserved, with Priya's share captured. Returns the gateway, the PayPal order id and
    her capture id."""
    gateway = FakeGateway()
    paypal_order_id = gateway.create_checkout(ORDER).paypal_order_id
    gateway.approve(paypal_order_id)
    hold = gateway.reserve(paypal_order_id).hold_for("op_002")
    payment = gateway.pay_share(Share("op_002", hold, Decimal("176.00"), payee_email="priya@example.com", last=False))
    return gateway, paypal_order_id, payment.capture_id


def test_fake_paypal_puts_tracking_on_a_capture_of_the_order(paid):
    gateway, paypal_order_id, capture_id = paid

    tracker = gateway.add_tracking(Tracking("op_002", paypal_order_id, capture_id, "EE123456789IN", "INDIA_POST"))

    assert tracker == f"{capture_id}-EE123456789IN"
    assert gateway.get_order(paypal_order_id).trackers == (tracker,)
    assert ("add_tracking", Tracking("op_002", paypal_order_id, capture_id, "EE123456789IN", "INDIA_POST")) in gateway.calls


def test_fake_paypal_keeps_one_tracker_for_the_same_shipment(paid):
    gateway, paypal_order_id, capture_id = paid
    shipment = Tracking("op_002", paypal_order_id, capture_id, "EE123456789IN", "INDIA_POST")

    gateway.add_tracking(shipment)
    gateway.add_tracking(shipment)

    assert len(gateway.get_order(paypal_order_id).trackers) == 1


def test_fake_paypal_refuses_tracking_on_a_capture_that_is_not_this_orders(paid):
    gateway, paypal_order_id, _ = paid

    with pytest.raises(PaymentError) as error:
        gateway.add_tracking(Tracking("op_001", paypal_order_id, "NO-SUCH-CAPTURE", "7712345678", "TCS"))

    assert error.value.issue == "RESOURCE_NOT_FOUND"


def test_fake_paypal_wants_a_name_with_other_as_paypal_does(paid):
    gateway, paypal_order_id, capture_id = paid

    with pytest.raises(PaymentError) as error:
        gateway.add_tracking(Tracking("op_002", paypal_order_id, capture_id, "LE123456", "OTHER"))

    assert error.value.issue == "MISSING_REQUIRED_PARAMETER"
