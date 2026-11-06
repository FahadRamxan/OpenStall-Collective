"""The sandbox gateways send PayPal exactly what each payment path needs.

Orders and Payments go through APIMatic's PayPal SDK, so PayPal is faked at the SDK's own seam: a transport passed
as custom_http_client, which answers each request and keeps it, so the tests check the request the SDK really
built. Payouts still go through our own PayPalClient, mocked with respx as before.
"""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx2
import pytest
import respx
from paypal.core import HttpRequest, HttpResponse, JsonBody, RetryOptions, TransportError

from openstall_paypal import Advance, AdvancePayment
from openstall_paypal import (
    RETRY_POLICY,
    WHOLE_ORDER,
    CheckoutPart,
    CheckoutRequest,
    MultipartyGateway,
    PaymentError,
    PaymentGateway,
    PaymentUnavailable,
    PayoutsGateway,
    PayPalClient,
    PayPalSdk,
    SandboxGateway,
    Share,
    Tracking,
)

BASE = "https://api-m.sandbox.paypal.com"
TOKEN_PATH = "/v1/oauth2/token"
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
# The real policy, with the waits between retries shortened so the tests do not sleep.
FAST_RETRIES: RetryOptions = RETRY_POLICY.model_copy(update={"initial_delay": 0.001, "max_jitter": 0.0})


def authorized(*units: tuple[str, str]) -> dict[str, Any]:
    return {
        "id": "5O190127TN364715T",
        "status": "COMPLETED",
        "purchase_units": [
            {"reference_id": reference, "payments": {"authorizations": [{"id": hold, "status": "CREATED"}]}}
            for reference, hold in units
        ],
    }


# The fake PayPal behind the SDK: the transport protocol (send and close), routed by method and path.


@dataclass
class StubResponse:
    """A canned response head, with its body held until the SDK reads it."""

    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    chunks: list[bytes] = field(default_factory=list)
    url: str = BASE
    closed: bool = False

    def iter_bytes(self, chunk_size: int | None) -> Iterator[bytes]:
        yield from self.chunks
        self.close()

    def read(self) -> bytes:
        self.close()
        return b"".join(self.chunks)

    def close(self) -> None:
        self.closed = True


@dataclass
class Route:
    """The answers for one method and path, in order (the last one repeats), and the requests it got."""

    answers: list[StubResponse | Exception]
    calls: list[HttpRequest] = field(default_factory=list)

    @property
    def called(self) -> bool:
        return bool(self.calls)

    @property
    def last(self) -> HttpRequest:
        return self.calls[-1]


def answer(status: int = 200, body: Any = None, *, raw: bytes | None = None) -> StubResponse:
    content = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
    return StubResponse(
        status_code=status, headers={"content-type": "application/json"}, chunks=[content] if content else []
    )


class FakePayPal:
    """Answers the token request by itself (once, as the SDK caches the token), and each route as it was told."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Route] = {}
        self.requests: list[HttpRequest] = []
        self.closed = False
        self.on("POST", TOKEN_PATH, answer(200, {"access_token": "TOKEN", "token_type": "Bearer", "expires_in": 32400}))

    def on(self, method: str, path: str, *answers: StubResponse | Exception) -> Route:
        route = Route(list(answers))
        self.routes[(method, path)] = route
        return route

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        route = self.routes.get((request.method, urlsplit(request.url).path))
        if route is None:
            return answer(404, {"name": "RESOURCE_NOT_FOUND", "message": "no fake route", "debug_id": "x"})
        route.calls.append(request)
        reply = route.answers.pop(0) if len(route.answers) > 1 else route.answers[0]
        if isinstance(reply, Exception):
            raise TransportError(reply)  # as the SDK's own Httpx2Client reports a request with no response
        return StubResponse(reply.status_code, reply.headers, list(reply.chunks), request.url)

    def close(self) -> None:
        self.closed = True

    def token_requests(self) -> int:
        return len(self.routes[("POST", TOKEN_PATH)].calls)


def sent(route: Route) -> tuple[Any, str | None]:
    """The body the SDK sent (as JSON) and its PayPal-Request-Id."""
    request = route.last
    body = request.body.value if isinstance(request.body, JsonBody) else None
    return body, request.headers.get("paypal-request-id")


@pytest.fixture
def fake() -> FakePayPal:
    return FakePayPal()


@pytest.fixture
def sdk(fake: FakePayPal) -> Iterator[PayPalSdk]:
    sdk = PayPalSdk(BASE, "made-up-client-id", "made-up-secret", transport=fake, retry_options=FAST_RETRIES)
    yield sdk
    sdk.close()


@pytest.fixture
def paypal() -> Iterator[respx.MockRouter]:
    """Our own PayPalClient's side (payouts), mocked with respx."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.post(TOKEN_PATH).respond(json={"access_token": "TOKEN", "expires_in": 32400})
        yield router


@pytest.fixture
def client() -> PayPalClient:
    return PayPalClient(BASE, "made-up-client-id", "made-up-secret")


def payout_sent(route: respx.Route) -> tuple[Any, str | None]:
    request = route.calls.last.request
    return (json.loads(request.content) if request.content else None), request.headers.get("PayPal-Request-Id")


# What each path sends.


@pytest.mark.parametrize("gateway", [MultipartyGateway, PayoutsGateway])
def test_both_paths_follow_the_payment_gateway_interface(gateway: type[SandboxGateway], client: PayPalClient, sdk: PayPalSdk) -> None:
    assert isinstance(gateway(client, sdk), PaymentGateway)


@pytest.mark.parametrize("gateway", [MultipartyGateway, PayoutsGateway])
def test_both_paths_only_reserve_on_approval_and_send_the_buyer_back_to_us(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk, gateway: type[SandboxGateway]) -> None:
    route = fake.on("POST", "/v2/checkout/orders", answer(201, CREATED))

    checkout = gateway(client, sdk).create_checkout(ORDER)

    body, key = sent(route)
    assert body["intent"] == "AUTHORIZE"
    assert key == "openstall-checkout-ord_demo"
    context = body["payment_source"]["paypal"]["experience_context"]
    assert context["return_url"] == "https://openstall.example/approve/ord_demo/return"
    assert context["cancel_url"] == "https://openstall.example/approve/ord_demo?cancelled=1"
    assert context["shipping_preference"] == "NO_SHIPPING"
    assert context["user_action"] == "PAY_NOW"
    assert context["brand_name"] == "OpenStall Collective"
    assert checkout.paypal_order_id == "5O190127TN364715T"
    assert checkout.approval_url == "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"


def test_multiparty_makes_one_purchase_unit_per_seller_with_her_as_payee(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", "/v2/checkout/orders", answer(201, CREATED))

    MultipartyGateway(client, sdk).create_checkout(ORDER)

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


def test_multiparty_refuses_a_seller_with_no_paypal_account_before_calling_paypal(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", "/v2/checkout/orders", answer(201, CREATED))
    order = CheckoutRequest(
        "ord_x", (CheckoutPart("op_001", Decimal("203.00"), "7 × Cushion cover, Grace"),), "https://a.b/r", "https://a.b/c"
    )

    with pytest.raises(PaymentError, match="Grace") as error:
        MultipartyGateway(client, sdk).create_checkout(order)

    assert error.value.issue == "PAYEE_MISSING"
    assert not route.called
    assert fake.requests == []  # not even a token


def test_payouts_makes_one_purchase_unit_for_the_whole_total_listing_each_seller(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", "/v2/checkout/orders", answer(201, CREATED))

    PayoutsGateway(client, sdk).create_checkout(ORDER)

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
    assert {(item["quantity"], item["category"]) for item in unit["items"]} == {("1", "PHYSICAL_GOODS")}


def test_every_write_asks_for_the_full_answer_and_carries_our_token(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    create = fake.on("POST", "/v2/checkout/orders", answer(201, CREATED))
    authorize = fake.on(
        "POST", "/v2/checkout/orders/5O190127TN364715T/authorize", answer(201, authorized(("op_001", "AUTH-1")))
    )
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(201, {"id": "CAPTURE-1"}))
    void = fake.on("POST", "/v2/payments/authorizations/AUTH-2/void", answer(200, {"id": "AUTH-2", "status": "VOIDED"}))
    gateway = MultipartyGateway(client, sdk)

    gateway.create_checkout(ORDER)
    gateway.reserve("5O190127TN364715T")
    gateway.pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))
    gateway.release_share(Share("op_2", "AUTH-2", Decimal("1.00")))

    for route in (create, authorize, capture, void):
        assert route.last.headers["prefer"] == "return=representation"  # the SDK's default is return=minimal
        assert route.last.headers["authorization"] == "Bearer TOKEN"
    assert fake.token_requests() == 1  # the SDK keeps its token


def test_an_older_answer_with_an_approve_link_still_works(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on(
        "POST",
        "/v2/checkout/orders",
        answer(201, {"id": "ORDER-2", "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/x"}]}),
    )

    assert PayoutsGateway(client, sdk).create_checkout(ORDER).approval_url == "https://www.sandbox.paypal.com/x"


def test_an_order_without_an_approval_link_is_an_error(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/checkout/orders", answer(201, {"id": "ORDER-3", "links": []}))

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client, sdk).create_checkout(ORDER)

    assert error.value.issue == "NO_APPROVAL_LINK"


def test_multiparty_reserves_one_authorization_per_share(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on(
        "POST",
        "/v2/checkout/orders/5O190127TN364715T/authorize",
        answer(201, authorized(("op_001", "AUTH-AMINA"), ("op_002", "AUTH-PRIYA"))),
    )

    reservation = MultipartyGateway(client, sdk).reserve("5O190127TN364715T")

    assert reservation.holds == {"op_001": "AUTH-AMINA", "op_002": "AUTH-PRIYA"}
    assert sent(route) == ({}, "openstall-reserve-5O190127TN364715T")


def test_on_the_payouts_path_one_authorization_holds_every_share(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on(
        "POST", "/v2/checkout/orders/5O190127TN364715T/authorize", answer(201, authorized((WHOLE_ORDER, "AUTH-ALL")))
    )

    reservation = PayoutsGateway(client, sdk).reserve("5O190127TN364715T")

    assert reservation.hold_for("op_001") == reservation.hold_for("op_002") == "AUTH-ALL"


def test_an_authorization_without_holds_is_an_error(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/checkout/orders/ORDER-4/authorize", answer(201, {"id": "ORDER-4", "status": "COMPLETED"}))

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).reserve("ORDER-4")

    assert error.value.issue == "NO_AUTHORIZATION"


def test_reading_an_order_back_shows_its_status_and_any_holds(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("GET", "/v2/checkout/orders/5O190127TN364715T", answer(200, authorized(("op_001", "AUTH-AMINA"))))

    state = MultipartyGateway(client, sdk).get_order("5O190127TN364715T")

    assert state.status == "COMPLETED"
    assert state.holds == {"op_001": "AUTH-AMINA"}
    assert route.last.body is None and "paypal-request-id" not in route.last.headers  # a read, with no key


def test_an_order_status_newer_than_the_sdk_is_kept_as_paypal_wrote_it(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("GET", "/v2/checkout/orders/ORDER-5", answer(200, {"id": "ORDER-5", "status": "SOMETHING_NEW"}))

    assert str(MultipartyGateway(client, sdk).get_order("ORDER-5").status) == "SOMETHING_NEW"


def test_multiparty_pays_a_share_by_capturing_her_whole_authorization(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on(
        "POST", "/v2/payments/authorizations/AUTH-AMINA/capture", answer(201, {"id": "CAPTURE-1", "status": "COMPLETED"})
    )

    payment = MultipartyGateway(client, sdk).pay_share(Share("op_amina", "AUTH-AMINA", Decimal("216.00")))

    assert payment.capture_id == "CAPTURE-1"
    assert sent(route) == ({"invoice_id": "op_amina", "final_capture": True}, "openstall-capture-op_amina")


def test_multiparty_releases_a_share_by_voiding_her_authorization(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", "/v2/payments/authorizations/AUTH-LUCIA/void", answer(204))

    MultipartyGateway(client, sdk).release_share(Share("op_lucia", "AUTH-LUCIA", Decimal("220.00"), last=False))

    assert sent(route) == (None, "openstall-release-op_lucia")


def test_a_void_answered_with_the_authorization_is_fine_too(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-1/void", answer(200, {"id": "AUTH-1", "status": "VOIDED"}))

    MultipartyGateway(client, sdk).release_share(Share("op_1", "AUTH-1", Decimal("1.00")))


@pytest.mark.parametrize("last", [False, True])
def test_payouts_captures_only_her_amount_then_pays_her(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk, last: bool) -> None:
    capture = fake.on(
        "POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "CAPTURE-7", "status": "COMPLETED"})
    )
    payout = paypal.post("/v1/payments/payouts").respond(
        201, json={"batch_header": {"payout_batch_id": "BATCH-7", "batch_status": "PENDING"}}
    )
    share = Share("op_grace", "AUTH-ALL", Decimal("203.00"), payee_email="grace@example.com", note="7 covers", last=last)

    payment = PayoutsGateway(client, sdk).pay_share(share)

    assert payment.capture_id == "CAPTURE-7" and payment.payout_batch_id == "BATCH-7"
    assert sent(capture) == (
        {"amount": {"currency_code": "USD", "value": "203.00"}, "invoice_id": "op_grace", "final_capture": last},
        "openstall-capture-op_grace",
    )
    body, key = payout_sent(payout)
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


def test_payouts_pays_by_merchant_id_when_there_is_no_email(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "C"}))
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})

    PayoutsGateway(client, sdk).pay_share(Share("op_1", "AUTH-ALL", Decimal("1.00"), payee_merchant_id="MERCHANT9"))

    body, _ = payout_sent(payout)
    assert body["items"][0]["recipient_type"] == "PAYPAL_ID" and body["items"][0]["receiver"] == "MERCHANT9"


def test_payouts_never_captures_for_a_seller_it_cannot_pay(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "C"}))

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client, sdk).pay_share(Share("op_noor", "AUTH-ALL", Decimal("186.00")))

    assert error.value.issue == "PAYEE_MISSING"
    assert not capture.called


def test_payouts_releases_a_share_by_leaving_it_uncaptured_and_the_last_one_frees_the_rest(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    void = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/void", answer(204))
    gateway = PayoutsGateway(client, sdk)

    gateway.release_share(Share("op_lucia", "AUTH-ALL", Decimal("220.00"), last=False))
    assert not void.called

    gateway.release_share(Share("op_grace", "AUTH-ALL", Decimal("203.00"), last=True))
    assert sent(void) == (None, "openstall-release-op_grace")


def test_a_failed_payout_after_the_capture_keeps_paypals_issue(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "C"}))
    paypal.post("/v1/payments/payouts").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "RECEIVER_UNREGISTERED"}]}
    )

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client, sdk).pay_share(Share("op_1", "AUTH-ALL", Decimal("1.00"), payee_email="a@b.c"))

    assert error.value.issue == "RECEIVER_UNREGISTERED"



# Payout rails (spec 3.5a, rails.py).

GRACE_VENMO = Share(
    "op_grace",
    "AUTH-ALL",
    Decimal("203.00"),
    note="Your share of OpenStall order ord_demo",
    last=True,
    payout_rail="venmo",
    venmo_handle="grace-detroit-demo",
)


def test_payouts_gateway_sends_the_venmo_item(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    """Where Venmo payouts run (live PayPal; the sandbox refuses them), her item goes to Venmo by her handle."""
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "CAPTURE-G"}))
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "BATCH-G"}})

    payment = PayoutsGateway(client, sdk, simulate_venmo=False).pay_share(GRACE_VENMO)

    assert capture.called
    assert (payment.capture_id, payment.payout_batch_id, payment.payout_rail) == ("CAPTURE-G", "BATCH-G", "venmo")
    assert not payment.payout_simulated
    body, key = payout_sent(payout)
    assert key == "openstall-payout-op_grace"
    assert body["sender_batch_header"]["sender_batch_id"] == "openstall-op_grace"
    assert body["items"] == [
        {
            "recipient_wallet": "Venmo",
            "recipient_type": "USER_HANDLE",
            "receiver": "grace-detroit-demo",
            "note": "Your share of OpenStall order ord_demo",
            "amount": {"currency": "USD", "value": "203.00"},
            "sender_item_id": "op_grace",
        }
    ]


def test_on_the_sandbox_a_venmo_share_is_captured_and_her_payout_simulated(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    """PayPal's sandbox refuses Venmo payouts after the capture would already have happened, so none is sent."""
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "CAPTURE-G"}))
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})
    gateway = PayoutsGateway(client, sdk)  # the client is on the sandbox host

    payment = gateway.pay_share(GRACE_VENMO)

    assert gateway.simulate_venmo
    assert capture.called and not payout.called
    assert (payment.capture_id, payment.payout_batch_id) == ("CAPTURE-G", None)
    assert (payment.payout_rail, payment.payout_simulated) == ("venmo", True)


def test_a_hyperwallet_share_is_captured_and_no_paypal_payout_is_sent(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    """Prompt 52: her capture is real; her bank payout through Hyperwallet is simulated, as no Hyperwallet
    account is connected, so no PayPal payout goes out and she needs no PayPal account."""
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "CAPTURE-A"}))
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})
    amina = Share("op_amina", "AUTH-ALL", Decimal("216.00"), payout_rail="hyperwallet", last=False)

    payment = PayoutsGateway(client, sdk).pay_share(amina)

    assert capture.called and not payout.called
    assert sent(capture)[0]["amount"] == {"currency_code": "USD", "value": "216.00"}
    assert sent(capture)[0]["final_capture"] is False
    assert (payment.capture_id, payment.payout_batch_id) == ("CAPTURE-A", None)
    assert (payment.payout_rail, payment.payout_simulated) == ("hyperwallet", True)


def test_no_capture_call_when_rail_unavailable(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})
    amina = Share("op_amina", "AUTH-ALL", Decimal("216.00"), payee_email="amina@example.com", payout_rail="unavailable")

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client, sdk).pay_share(amina)

    assert error.value.issue == "PAYOUT_RAIL_UNAVAILABLE"
    assert not [r for r in fake.requests if urlsplit(r.url).path.startswith("/v2/payments/authorizations/")]
    assert not [r for r in fake.requests if urlsplit(r.url).path.endswith("/capture")]
    assert not payout.called


def test_no_capture_call_for_a_venmo_maker_without_a_handle(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "C"}))

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client, sdk).pay_share(Share("op_grace", "AUTH-ALL", Decimal("203.00"), payout_rail="venmo"))

    assert error.value.issue == "PAYEE_MISSING"
    assert not capture.called


# PayPal's refusals: PaymentError with PayPal's issue code.


def test_paypal_refusals_keep_their_issue_code(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    # No debug_id, so this is not the SDK's Error shape: the issue is still read from the body PayPal sent.
    fake.on(
        "POST",
        "/v2/payments/authorizations/AUTH-1/capture",
        answer(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "AUTHORIZATION_VOIDED"}], "message": "Voided"}),
    )

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.issue == "AUTHORIZATION_VOIDED"
    assert not isinstance(error.value, PaymentUnavailable)


def test_a_refusal_in_the_sdks_error_shape_keeps_its_issue_and_message(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on(
        "POST",
        "/v2/checkout/orders/ORDER-6/authorize",
        answer(
            422,
            {
                "name": "UNPROCESSABLE_ENTITY",
                "message": "The requested action could not be performed.",
                "debug_id": "f00d",
                "details": [{"issue": "ORDER_NOT_APPROVED", "description": "Payer has not yet approved the Order."}],
            },
        ),
    )

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).reserve("ORDER-6")

    assert error.value.issue == "ORDER_NOT_APPROVED"
    assert error.value.message == "The requested action could not be performed."
    assert not isinstance(error.value, PaymentUnavailable)


def test_a_refusal_without_details_uses_paypals_name(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on(
        "GET",
        "/v2/checkout/orders/ORDER-7",
        answer(404, {"name": "RESOURCE_NOT_FOUND", "message": "Not found", "debug_id": "f00d"}),
    )

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).get_order("ORDER-7")

    assert error.value.issue == "RESOURCE_NOT_FOUND"


def test_a_status_the_sdk_does_not_map_is_still_a_refusal_with_its_issue(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(418, {"name": "TEAPOT"}))

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.issue == "TEAPOT"
    assert not isinstance(error.value, PaymentUnavailable)


def test_bad_credentials_are_a_refusal_of_our_keys_and_nothing_is_sent(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", TOKEN_PATH, answer(401, {"error": "invalid_client", "error_description": "Client Authentication failed"}))
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(201, {"id": "C"}))

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.issue == "invalid_client"
    assert error.value.message == "Client Authentication failed"
    assert not isinstance(error.value, PaymentUnavailable)
    assert not capture.called


# PayPal's own 401 bodies. An expired or revoked token gets an OAuth-style body, and AUTHENTICATION_FAILURE often
# comes without a debug_id; neither fits the SDK's Error model (name, message and debug_id all required).
EXPIRED_TOKEN = {"error": "invalid_token", "error_description": "Access Token not found in cache"}
AUTHENTICATION_FAILURE = {
    "name": "AUTHENTICATION_FAILURE",
    "message": "Authentication failed due to invalid authentication credentials or a missing Authorization header.",
    "links": [{"href": "https://developer.paypal.com/docs/api/overview/#error", "rel": "information_link"}],
}
IN_THE_SDKS_SHAPE = {"name": "AUTHENTICATION_FAILURE", "message": "expired", "debug_id": "x"}


@pytest.mark.parametrize(
    "body", [EXPIRED_TOKEN, AUTHENTICATION_FAILURE, IN_THE_SDKS_SHAPE], ids=["invalid_token", "no debug_id", "Error"]
)
def test_a_401_gets_a_fresh_token_and_one_more_try_with_the_same_request_id(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk, body: dict[str, Any]) -> None:
    capture = fake.on(
        "POST",
        "/v2/payments/authorizations/AUTH-1/capture",
        answer(401, body),
        answer(201, {"id": "CAPTURE-2"}),
    )

    payment = MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert payment.capture_id == "CAPTURE-2"
    assert fake.token_requests() == 2
    assert [request.headers["paypal-request-id"] for request in capture.calls] == ["openstall-capture-op_1"] * 2


@pytest.mark.parametrize(
    ("body", "issue"),
    [(EXPIRED_TOKEN, "invalid_token"), (AUTHENTICATION_FAILURE, "AUTHENTICATION_FAILURE"), (IN_THE_SDKS_SHAPE, "AUTHENTICATION_FAILURE")],
    ids=["invalid_token", "no debug_id", "Error"],
)
def test_a_second_401_is_a_refusal(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk, body: dict[str, Any], issue: str) -> None:
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(401, body))

    with pytest.raises(PaymentError) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.issue == issue
    assert not isinstance(error.value, PaymentUnavailable)
    assert len(capture.calls) == 2
    assert fake.token_requests() == 2


def test_a_401_on_a_read_is_tried_once_more_too(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on(
        "GET", "/v2/checkout/orders/ORDER-8", answer(401, EXPIRED_TOKEN), answer(200, {"id": "ORDER-8", "status": "APPROVED"})
    )

    assert MultipartyGateway(client, sdk).get_order("ORDER-8").status == "APPROVED"
    assert len(route.calls) == 2


# No answer: PaymentUnavailable, so the caller reads the state back. Never sent and may-have-landed differ.


def test_no_answer_from_paypal_is_unavailable_so_the_caller_reads_the_state_back(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", "/v2/checkout/orders/ORDER-9/authorize", httpx2.ReadTimeout("slow"))

    with pytest.raises(PaymentUnavailable) as error:
        MultipartyGateway(client, sdk).reserve("ORDER-9")

    assert len(route.calls) == 1  # a write is never sent again blindly
    assert error.value.outcome_unknown


def test_a_request_that_never_left_is_not_the_same_failure_as_one_that_may_have_landed(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", httpx2.ConnectError("refused"))
    fake.on("POST", "/v2/payments/authorizations/AUTH-2/capture", httpx2.ReadTimeout("no reply"))
    gateway = MultipartyGateway(client, sdk)

    with pytest.raises(PaymentUnavailable) as never_sent:
        gateway.pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))
    with pytest.raises(PaymentUnavailable) as may_have_landed:
        gateway.pay_share(Share("op_2", "AUTH-2", Decimal("1.00")))

    assert (never_sent.value.issue, never_sent.value.outcome_unknown) == ("PAYPAL_UNAVAILABLE", False)
    assert (may_have_landed.value.issue, may_have_landed.value.outcome_unknown) == ("PAYPAL_UNAVAILABLE", True)


def test_when_the_token_cannot_be_fetched_the_operation_was_never_sent(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", TOKEN_PATH, httpx2.ReadTimeout("slow"))
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(201, {"id": "C"}))

    with pytest.raises(PaymentUnavailable) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert not error.value.outcome_unknown
    assert not capture.called


def test_a_paypal_server_error_is_unavailable_and_keeps_its_issue(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on(
        "POST",
        "/v2/payments/authorizations/AUTH-1/capture",
        answer(500, {"name": "INTERNAL_SERVER_ERROR", "message": "oops", "debug_id": "x"}),
    )

    with pytest.raises(PaymentUnavailable) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.issue == "INTERNAL_SERVER_ERROR"
    assert error.value.outcome_unknown
    assert len(route.calls) == 1


def test_an_answer_that_cannot_be_read_may_have_succeeded(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(201, {"id": ["not", "a", "string"]}))
    fake.on("POST", "/v2/payments/authorizations/AUTH-2/capture", answer(201, raw=b"<html>gateway</html>"))
    gateway = MultipartyGateway(client, sdk)

    for share in (Share("op_1", "AUTH-1", Decimal("1.00")), Share("op_2", "AUTH-2", Decimal("1.00"))):
        with pytest.raises(PaymentUnavailable) as error:
            gateway.pay_share(share)
        assert (error.value.issue, error.value.outcome_unknown) == ("PAYPAL_UNREADABLE", True)


def test_a_capture_answered_without_an_id_is_not_taken_as_paid_or_as_failed(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", answer(201, {}))

    with pytest.raises(PaymentUnavailable) as error:
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert error.value.outcome_unknown


def test_an_order_created_without_an_id_is_read_back_not_guessed(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", "/v2/checkout/orders", answer(201, {"status": "PAYER_ACTION_REQUIRED"}))

    with pytest.raises(PaymentUnavailable):
        MultipartyGateway(client, sdk).create_checkout(ORDER)


# The retry policy: the SDK resends reads only.


def test_the_retry_policy_resends_reads_and_never_writes() -> None:
    assert RETRY_POLICY.http_methods_to_retry == frozenset({"GET"})
    assert RETRY_POLICY.max_retries == 2


def test_a_read_is_tried_again_after_a_server_error_or_no_answer(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on(
        "GET",
        "/v2/checkout/orders/ORDER-8",
        answer(503, {"name": "SERVICE_UNAVAILABLE", "message": "busy", "debug_id": "x"}),
        httpx2.ConnectError("refused"),
        answer(200, {"id": "ORDER-8", "status": "APPROVED"}),
    )

    assert MultipartyGateway(client, sdk).get_order("ORDER-8").status == "APPROVED"
    assert len(route.calls) == 3


def test_a_read_gives_up_after_its_retries(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("GET", "/v2/checkout/orders/ORDER-8", httpx2.ReadTimeout("slow"))

    with pytest.raises(PaymentUnavailable):
        MultipartyGateway(client, sdk).get_order("ORDER-8")

    assert len(route.calls) == 1 + RETRY_POLICY.max_retries


@pytest.mark.parametrize(
    "failure",
    [answer(503, {"name": "SERVICE_UNAVAILABLE", "message": "busy", "debug_id": "x"}), httpx2.ConnectError("refused")],
    ids=["server error", "no connection"],
)
def test_a_write_is_never_sent_twice_by_the_sdk(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk, failure: StubResponse | Exception) -> None:
    route = fake.on("POST", "/v2/payments/authorizations/AUTH-1/capture", failure, answer(201, {"id": "C"}))

    with pytest.raises(PaymentUnavailable):
        MultipartyGateway(client, sdk).pay_share(Share("op_1", "AUTH-1", Decimal("1.00")))

    assert len(route.calls) == 1


def test_the_gateway_closes_both_clients(fake: FakePayPal, sdk: PayPalSdk) -> None:
    client = PayPalClient(BASE, "id", "secret")

    MultipartyGateway(client, sdk).close()

    assert fake.closed  # the SDK client closes its transport
    assert client._http.is_closed


# Tracking on the PayPal order (prompt 33): orders.create_order_tracking, with no PayPal-Request-Id.

TRACK_PATH = "/v2/checkout/orders/5O190127TN364715T/track"


def with_trackers(*ids: str) -> dict[str, Any]:
    """An order whose one purchase unit has these trackers, as PayPal lists them."""
    return {
        "id": "5O190127TN364715T",
        "status": "COMPLETED",
        "purchase_units": [{"reference_id": WHOLE_ORDER, "shipping": {"trackers": [{"id": i, "status": "SHIPPED"} for i in ids]}}],
    }


def tracking(carrier: str = "INDIA_POST", other: str | None = None, known: tuple[str, ...] = ()) -> Tracking:
    return Tracking("op_002", "5O190127TN364715T", "CAP-2", "EE123456789IN", carrier, other, known)


def test_tracking_goes_on_her_capture_with_paypals_carrier_and_no_request_id(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", TRACK_PATH, answer(200, with_trackers("CAP-1-7712345678", "CAP-2-EE123456789IN")))

    tracker = PayoutsGateway(client, sdk).add_tracking(tracking())

    body, key = sent(route)
    assert body == {"capture_id": "CAP-2", "tracking_number": "EE123456789IN", "carrier": "INDIA_POST", "notify_payer": False}
    assert key is None  # this route takes no PayPal-Request-Id: the caller reads the order back first
    assert tracker == "CAP-2-EE123456789IN"


def test_a_courier_paypal_does_not_list_goes_as_other_with_its_name(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", TRACK_PATH, answer(200, with_trackers("CAP-2-EE123456789IN")))

    PayoutsGateway(client, sdk).add_tracking(tracking("OTHER", "Leopards Courier"))

    body, _ = sent(route)
    assert (body["carrier"], body["carrier_name_other"]) == ("OTHER", "Leopards Courier")


def test_whatever_its_id_says_the_one_tracker_new_since_we_read_the_order_is_ours(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", TRACK_PATH, answer(200, with_trackers("T-OLD", "T-NEW")))

    assert PayoutsGateway(client, sdk).add_tracking(tracking(known=("T-OLD",))) == "T-NEW"


def test_an_answer_without_a_new_tracker_is_unknown_never_success(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("POST", TRACK_PATH, answer(200, with_trackers("T-OLD")))

    with pytest.raises(PaymentUnavailable) as error:
        PayoutsGateway(client, sdk).add_tracking(tracking(known=("T-OLD",)))

    assert (error.value.issue, error.value.outcome_unknown) == ("PAYPAL_UNREADABLE", True)


def test_paypal_refusing_tracking_keeps_its_issue(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    refusal = {
        "name": "UNPROCESSABLE_ENTITY",
        "message": "The requested action could not be performed.",
        "debug_id": "f00d",
        "details": [{"issue": "INVALID_CAPTURE_ID", "description": "no such capture"}],
    }
    fake.on("POST", TRACK_PATH, answer(422, refusal))

    with pytest.raises(PaymentError) as error:
        PayoutsGateway(client, sdk).add_tracking(tracking())

    assert error.value.issue == "INVALID_CAPTURE_ID"
    assert not isinstance(error.value, PaymentUnavailable)


def test_a_track_call_that_got_no_answer_is_never_resent_by_the_sdk(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    route = fake.on("POST", TRACK_PATH, httpx2.ReadTimeout("no reply"), answer(200, with_trackers("CAP-2-EE123456789IN")))

    with pytest.raises(PaymentUnavailable) as error:
        PayoutsGateway(client, sdk).add_tracking(tracking())

    assert error.value.outcome_unknown
    assert len(route.calls) == 1


def test_reading_an_order_lists_its_trackers(fake: FakePayPal, client: PayPalClient, sdk: PayPalSdk) -> None:
    fake.on("GET", "/v2/checkout/orders/5O190127TN364715T", answer(200, with_trackers("CAP-1-7712345678")))
    fake.on("GET", "/v2/checkout/orders/ORDER-NONE", answer(200, {"id": "ORDER-NONE", "status": "APPROVED"}))

    gateway = PayoutsGateway(client, sdk)

    assert gateway.get_order("5O190127TN364715T").trackers == ("CAP-1-7712345678",)
    assert gateway.get_order("ORDER-NONE").trackers == ()


# A materials advance (prompt 37): a payout from the platform's balance, ahead of her proof.


def test_payouts_pays_an_advance_from_the_platform_without_capturing(paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "BATCH-ADV"}})
    share = Share("op_grace", "AUTH-ALL", Decimal("203.00"), payee_email="grace@example.com", note="7 covers")

    paid = PayoutsGateway(client, sdk).pay_advance(Advance(share, Decimal("50.75")))

    assert paid == AdvancePayment("BATCH-ADV", "paypal")
    body, key = payout_sent(payout)
    assert key == "openstall-advance-op_grace"
    assert body["sender_batch_header"]["sender_batch_id"] == "openstall-advance-op_grace"
    assert body["items"] == [
        {
            "recipient_type": "EMAIL",
            "receiver": "grace@example.com",
            "amount": {"currency": "USD", "value": "50.75"},
            "sender_item_id": "op_grace-advance",
            "note": "7 covers",
        }
    ]


def test_a_share_paid_ahead_is_captured_whole_and_paid_the_rest(fake: FakePayPal, paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    capture = fake.on("POST", "/v2/payments/authorizations/AUTH-ALL/capture", answer(201, {"id": "CAPTURE-8"}))
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})
    share = Share(
        "op_grace", "AUTH-ALL", Decimal("203.00"), payee_email="grace@example.com", paid_ahead_usd=Decimal("50.75")
    )

    PayoutsGateway(client, sdk).pay_share(share)

    assert sent(capture)[0]["amount"] == {"currency_code": "USD", "value": "203.00"}
    body, _ = payout_sent(payout)
    assert body["items"][0]["amount"] == {"currency": "USD", "value": "152.25"}


def test_an_advance_through_hyperwallet_sends_no_payout(paypal: respx.MockRouter, client: PayPalClient, sdk: PayPalSdk) -> None:
    payout = paypal.post("/v1/payments/payouts").respond(201, json={"batch_header": {"payout_batch_id": "B"}})
    amina = Share("op_amina", "AUTH-ALL", Decimal("216.00"), payout_rail="hyperwallet")

    paid = PayoutsGateway(client, sdk).pay_advance(Advance(amina, Decimal("54.00")))

    assert paid == AdvancePayment(None, "hyperwallet", payout_simulated=True)
    assert not payout.called


def test_the_multiparty_path_pays_no_advances(client: PayPalClient, sdk: PayPalSdk) -> None:
    with pytest.raises(PaymentError, match="payouts path"):
        MultipartyGateway(client, sdk).pay_advance(Advance(Share("op_1", "AUTH-1", Decimal("10.00")), Decimal("2.50")))
