"""The sandbox gateways send PayPal exactly what each payment path needs. PayPal is mocked with respx."""

import json
from decimal import Decimal

import httpx
import pytest
import respx

from openstall_paypal import (
    WHOLE_ORDER,
    CheckoutPart,
    CheckoutRequest,
    MultipartyGateway,
    PaymentError,
    PaymentGateway,
    PaymentUnavailable,
    PayoutsGateway,
    PayPalClient,
    Share,
)

BASE = "https://api-m.sandbox.paypal.com"
ORDER = CheckoutRequest(
    order_id="ord_demo",
    parts=(
        CheckoutPart("op_001", Decimal("216.00"), "12 × Cushion cover, Amina", payee_merchant_id="AMINAMERCHANT1"),
        CheckoutPart("op_002", Decimal("176.00"), "11 × Cushion cover, Priya", payee_email="priya@example.com"),
    ),
    return_url="https://openstall.example/approve/ord_demo/return",
    cancel_url="https://openstall.example/approve/ord_demo?cancelled=1",
)
CREATED = {
    "id": "5O190127TN364715T",
    "status": "PAYER_ACTION_REQUIRED",
    "links": [
        {"rel": "self", "href": f"{BASE}/v2/checkout/orders/5O190127TN364715T"},
        {"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"},
    ],
}


def authorized(*units: tuple[str, str]) -> dict:
    return {
        "id": "5O190127TN364715T",
        "status": "COMPLETED",
        "purchase_units": [
            {"reference_id": reference, "payments": {"authorizations": [{"id": hold, "status": "CREATED"}]}}
            for reference, hold in units
        ],
    }


@pytest.fixture
def paypal():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        yield router


@pytest.fixture
def client() -> PayPalClient:
    return PayPalClient(BASE, "made-up-client-id", "made-up-secret")


def sent(route: respx.Route) -> tuple[dict, str | None]:
    request = route.calls.last.request
    return (json.loads(request.content) if request.content else None), request.headers.get("PayPal-Request-Id")


@pytest.mark.parametrize("gateway", [MultipartyGateway, PayoutsGateway])
def test_both_paths_follow_the_payment_gateway_interface(gateway, client):
    assert isinstance(gateway(client), PaymentGateway)


@pytest.mark.parametrize("gateway", [MultipartyGateway, PayoutsGateway])
def test_both_paths_only_reserve_on_approval_and_send_the_buyer_back_to_us(paypal, client, gateway):
    route = paypal.post("/v2/checkout/orders").respond(201, json=CREATED)

    checkout = gateway(client).create_checkout(ORDER)

    body, key = sent(route)
    assert body["intent"] == "AUTHORIZE"
    assert key == "openstall-checkout-ord_demo"
    context = body["payment_source"]["paypal"]["experience_context"]
    assert context["return_url"] == "https://openstall.example/approve/ord_demo/return"
    assert context["cancel_url"] == "https://openstall.example/approve/ord_demo?cancelled=1"
    assert context["shipping_preference"] == "NO_SHIPPING"
    assert checkout.paypal_order_id == "5O190127TN364715T"
    assert checkout.approval_url == "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"


def test_multiparty_makes_one_purchase_unit_per_seller_with_her_as_payee(paypal, client):
    route = paypal.post("/v2/checkout/orders").respond(201, json=CREATED)

    MultipartyGateway(client).create_checkout(ORDER)

    body, _ = sent(route)
    assert body["purchase_units"] == [
        {
            "reference_id": "op_001",
            "custom_id": "ord_demo",
            "description": "12 × Cushion cover, Amina",
            "amount": {"currency_code": "USD", "value": "216.00"},
            "payee": {"merchant_id": "AMINAMERCHANT1"},
        },
        {
            "reference_id": "op_002",
            "custom_id": "ord_demo",
            "description": "11 × Cushion cover, Priya",
            "amount": {"currency_code": "USD", "value": "176.00"},
            "payee": {"email_address": "priya@example.com"},
        },
    ]


def test_multiparty_refuses_a_seller_with_no_paypal_account_before_calling_paypal(paypal, client):
    route = paypal.post("/v2/checkout/orders").respond(201, json=CREATED)
    order = CheckoutRequest(
        "ord_x", (CheckoutPart("op_001", Decimal("203.00"), "7 × Cushion cover, Grace"),), "https://a.b/r", "https://a.b/c"
    )

    with pytest.raises(PaymentError, match="Grace") as error:
        MultipartyGateway(client).create_checkout(order)

    assert error.value.issue == "PAYEE_MISSING"
    assert not route.called


def test_payouts_makes_one_purchase_unit_for_the_whole_total_listing_each_seller(paypal, client):
    route = paypal.post("/v2/checkout/orders").respond(201, json=CREATED)

    PayoutsGateway(client).create_checkout(ORDER)

    body, _ = sent(route)
    [unit] = body["purchase_units"]
    assert unit["reference_id"] == WHOLE_ORDER
    assert unit["custom_id"] == "ord_demo"
    assert "payee" not in unit  # the platform's own account
    assert unit["amount"] == {
        "currency_code": "USD",
        "value": "392.00",
        "breakdown": {"item_total": {"currency_code": "USD", "value": "392.00"}},
    }
    assert [(item["sku"], item["name"], item["unit_amount"]["value"]) for item in unit["items"]] == [
        ("op_001", "12 × Cushion cover, Amina", "216.00"),
        ("op_002", "11 × Cushion cover, Priya", "176.00"),
    ]


def test_an_older_answer_with_an_approve_link_still_works(paypal, client):
    paypal.post("/v2/checkout/orders").respond(
        201, json={"id": "ORDER-2", "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/x"}]}
    )

    assert PayoutsGateway(client).create_checkout(ORDER).approval_url == "https://www.sandbox.paypal.com/x"


def test_an_order_without_an_approval_link_is_an_error(paypal, client):
    paypal.post("/v2/checkout/orders").respond(201, json={"id": "ORDER-3", "links": []})

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client).create_checkout(ORDER)

    assert error.value.issue == "NO_APPROVAL_LINK"


def test_multiparty_reserves_one_authorization_per_share(paypal, client):
    route = paypal.post("/v2/checkout/orders/5O190127TN364715T/authorize").respond(
        201, json=authorized(("op_001", "AUTH-AMINA"), ("op_002", "AUTH-PRIYA"))
    )

    reservation = MultipartyGateway(client).reserve("5O190127TN364715T")

    assert reservation.holds == {"op_001": "AUTH-AMINA", "op_002": "AUTH-PRIYA"}
    assert sent(route) == ({}, "openstall-reserve-5O190127TN364715T")


def test_on_the_payouts_path_one_authorization_holds_every_share(paypal, client):
    paypal.post("/v2/checkout/orders/5O190127TN364715T/authorize").respond(
        201, json=authorized((WHOLE_ORDER, "AUTH-ALL"))
    )

    reservation = PayoutsGateway(client).reserve("5O190127TN364715T")

    assert reservation.hold_for("op_001") == reservation.hold_for("op_002") == "AUTH-ALL"


def test_reading_an_order_back_shows_its_status_and_any_holds(paypal, client):
    paypal.get("/v2/checkout/orders/5O190127TN364715T").respond(
        json=authorized(("op_001", "AUTH-AMINA"))
    )

    state = MultipartyGateway(client).get_order("5O190127TN364715T")

    assert state.status == "COMPLETED"
    assert state.holds == {"op_001": "AUTH-AMINA"}


def test_multiparty_pays_a_share_by_capturing_her_whole_authorization(paypal, client):
    route = paypal.post("/v2/payments/authorizations/AUTH-AMINA/capture").respond(
        201, json={"id": "CAPTURE-1", "status": "COMPLETED"}
    )

    payment = MultipartyGateway(client).pay_share(Share("op_amina", "AUTH-AMINA", Decimal("216.00")))

    assert payment.capture_id == "CAPTURE-1"
    assert sent(route) == ({"invoice_id": "op_amina", "final_capture": True}, "openstall-capture-op_amina")


def test_multiparty_releases_a_share_by_voiding_her_authorization(paypal, client):
    route = paypal.post("/v2/payments/authorizations/AUTH-LUCIA/void").respond(204)

    MultipartyGateway(client).release_share(Share("op_lucia", "AUTH-LUCIA", Decimal("220.00"), last=False))

    assert sent(route) == (None, "openstall-release-op_lucia")


@pytest.mark.parametrize("last", [False, True])
def test_payouts_captures_only_her_amount_then_pays_her(paypal, client, last):
    capture = paypal.post("/v2/payments/authorizations/AUTH-ALL/capture").respond(
        201, json={"id": "CAPTURE-7", "status": "COMPLETED"}
    )
    payout = paypal.post("/v1/payments/payouts").respond(
        201, json={"batch_header": {"payout_batch_id": "BATCH-7", "batch_status": "PENDING"}}
    )
    share = Share("op_grace", "AUTH-ALL", Decimal("203.00"), payee_email="grace@example.com", note="7 covers", last=last)

    payment = PayoutsGateway(client).pay_share(share)

    assert payment.capture_id == "CAPTURE-7" and payment.payout_batch_id == "BATCH-7"
    assert sent(capture) == (
        {"amount": {"currency_code": "USD", "value": "203.00"}, "invoice_id": "op_grace", "final_capture": last},
        "openstall-capture-op_grace",
    )
    body, key = sent(payout)
    assert key == "openstall-payout-op_grace"
    assert body["sender_batch_header"]["sender_batch_id"] == "openstall-op_grace"
    assert body["items"] == [
        {
            "recipient_type": "EMAIL",
            "receiver": "grace@example.com",
            "amount": {"currency": "USD", "value": "203.00"},
            "sender_item_id": "op_grace",
            "note": "7 covers",
        }
    ]


def test_payouts_pays_by_merchant_id_when_there_is_no_email(paypal, client):
    paypal.post("/v2/payments/authorizations/AUTH-ALL/capture").respond(201, json={"id": "C"})
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})

    PayoutsGateway(client).pay_share(Share("op_1", "AUTH-ALL", Decimal("1.00"), payee_merchant_id="MERCHANT9"))

    body, _ = sent(payout)
    assert body["items"][0]["recipient_type"] == "PAYPAL_ID" and body["items"][0]["receiver"] == "MERCHANT9"


def test_payouts_never_captures_for_a_seller_it_cannot_pay(paypal, client):
    capture = paypal.post("/v2/payments/authorizations/AUTH-ALL/capture").respond(201, json={"id": "C"})

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client).pay_share(Share("op_noor", "AUTH-ALL", Decimal("186.00")))

    assert error.value.issue == "PAYEE_MISSING"
    assert not capture.called


def test_payouts_releases_a_share_by_leaving_it_uncaptured_and_the_last_one_frees_the_rest(paypal, client):
    void = paypal.post("/v2/payments/authorizations/AUTH-ALL/void").respond(204)
    gateway = PayoutsGateway(client)

    gateway.release_share(Share("op_lucia", "AUTH-ALL", Decimal("220.00"), last=False))
    assert not void.called

    gateway.release_share(Share("op_grace", "AUTH-ALL", Decimal("203.00"), last=True))
    assert sent(void) == (None, "openstall-release-op_grace")


def test_paypal_refusals_keep_their_issue_code(paypal, client):
    paypal.post("/v2/payments/authorizations/AUTH-1/capture").respond(
        422,
        json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "AUTHORIZATION_VOIDED"}], "message": "Voided"},
    )

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.issue == "AUTHORIZATION_VOIDED"
    assert not isinstance(error.value, PaymentUnavailable)


def test_no_answer_from_paypal_is_unavailable_so_the_caller_reads_the_state_back(paypal, client):
    route = paypal.post("/v2/checkout/orders/ORDER-9/authorize").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(PaymentUnavailable):
        MultipartyGateway(client).reserve("ORDER-9")

    assert route.call_count == 1
