"""The adapter registry: fakes in fake mode; in sandbox mode the real adapters, or a clear error naming the adapter."""

from decimal import Decimal

import pytest

from openstall_agents.adapters import (
    LLM,
    Embedder,
    FakeEmbedder,
    FakeImageSearch,
    FakeLLM,
    FakeSpeechToText,
    ImageSearch,
    SpeechToText,
)
from openstall_api.adapters import ADAPTERS, AdapterRegistry, AdapterSpec, AdapterUnavailable, get_registry
from openstall_api.messaging import FakeMessenger, Messenger
from openstall_paypal import (
    CheckoutPart,
    CheckoutRequest,
    FakeGateway,
    MultipartyGateway,
    PaymentGateway,
    PayoutsGateway,
    PayPalSdk,
)

ALL_ADAPTERS = ["llm", "speech_to_text", "embedder", "messenger", "payment_gateway", "image_search"]

EVERY_KEY = {
    "ANTHROPIC_API_KEY": "made-up-anthropic-key",
    "OPENAI_API_KEY": "made-up-openai-key",
    "TWILIO_ACCOUNT_SID": "ACmadeup0000",
    "TWILIO_AUTH_TOKEN": "made-up-twilio-token",
    "PAYPAL_CLIENT_ID": "made-up-paypal-client-id",
    "PAYPAL_CLIENT_SECRET": "made-up-paypal-secret",
    "GOOGLE_VISION_API_KEY": "made-up-vision-key",
}


def statuses(registry: AdapterRegistry) -> dict[str, str]:
    return {report.name: report.status for report in registry.report()}


def test_there_is_one_adapter_per_outside_service():
    assert [spec.name for spec in ADAPTERS] == ALL_ADAPTERS


def test_fake_mode_uses_a_fake_for_every_adapter(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="fake"))

    assert isinstance(registry.llm, FakeLLM)
    assert isinstance(registry.speech_to_text, FakeSpeechToText)
    assert isinstance(registry.embedder, FakeEmbedder)
    assert isinstance(registry.messenger, FakeMessenger)
    assert isinstance(registry.payment_gateway, FakeGateway)
    assert isinstance(registry.image_search, FakeImageSearch)
    assert statuses(registry) == dict.fromkeys(ALL_ADAPTERS, "fake")
    assert all(report.missing_keys == () for report in registry.report())


def test_fake_mode_uses_fakes_even_when_keys_are_set(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="fake", **EVERY_KEY))

    assert isinstance(registry.payment_gateway, FakeGateway)
    assert set(statuses(registry).values()) == {"fake"}


def test_each_fake_follows_its_interface(use_settings):
    registry = AdapterRegistry(use_settings())

    assert isinstance(registry.llm, LLM)
    assert isinstance(registry.speech_to_text, SpeechToText)
    assert isinstance(registry.embedder, Embedder)
    assert isinstance(registry.messenger, Messenger)
    assert isinstance(registry.payment_gateway, PaymentGateway)
    assert isinstance(registry.image_search, ImageSearch)


def test_sandbox_mode_with_no_keys_reports_a_missing_key_for_every_adapter(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox"))

    assert statuses(registry) == dict.fromkeys(ALL_ADAPTERS, "missing key")
    assert registry.missing_keys("messenger") == ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN")
    assert registry.missing_keys("llm") == ("ANTHROPIC_API_KEY",)


def test_sandbox_mode_names_only_the_keys_still_missing(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", TWILIO_ACCOUNT_SID="ACmadeup0000"))

    assert registry.status("messenger") == "missing key"
    assert registry.missing_keys("messenger") == ("TWILIO_AUTH_TOKEN",)


def test_a_key_that_is_only_spaces_is_missing(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", ANTHROPIC_API_KEY="   "))

    assert registry.status("llm") == "missing key"


def test_using_an_adapter_whose_key_is_missing_raises_an_error_naming_the_adapter_and_key(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox"))

    with pytest.raises(AdapterUnavailable, match=r"needs ANTHROPIC_API_KEY for the LLM adapter \(Claude"):
        registry.llm
    with pytest.raises(AdapterUnavailable, match="TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN for the Messenger"):
        registry.messenger


def test_sandbox_mode_never_falls_back_to_a_fake(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox"))

    for name in ALL_ADAPTERS:
        with pytest.raises(AdapterUnavailable):
            registry.get(name)


def test_with_its_keys_but_no_real_implementation_an_adapter_is_not_built(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", **EVERY_KEY))

    assert statuses(registry) == {
        **dict.fromkeys(ALL_ADAPTERS, "not built"),
        "payment_gateway": "real",
        "messenger": "real",
    }
    assert all(report.missing_keys == () for report in registry.report())
    with pytest.raises(AdapterUnavailable, match=r"real LLM adapter \(Claude \(Anthropic\)\).*not built yet"):
        registry.llm


@pytest.mark.parametrize(("path", "gateway"), [("payouts", PayoutsGateway), ("multiparty", MultipartyGateway)])
def test_sandbox_mode_uses_the_paypal_gateway_for_the_chosen_payment_path(use_settings, path, gateway):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", PAYMENT_PATH=path, **EVERY_KEY))

    assert type(registry.payment_gateway) is gateway
    assert registry.payment_gateway.client.base_url == "https://api-m.sandbox.paypal.com"
    # Orders and Payments go through APIMatic's PayPal SDK, told the same base URL rather than left to its default.
    assert isinstance(registry.payment_gateway.sdk, PayPalSdk)
    assert registry.payment_gateway.sdk.base_url == "https://api-m.sandbox.paypal.com"


def test_closing_the_registry_closes_the_paypal_clients(use_settings):
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", **EVERY_KEY))
    gateway = registry.payment_gateway

    registry.close()

    assert gateway.client._http.is_closed
    assert registry.payment_gateway is not gateway  # a fresh one is made on next use


def test_sandbox_mode_uses_the_real_adapter_once_it_is_built(use_settings):
    spec = AdapterSpec(
        name="llm",
        label="LLM",
        purpose="Writes listings.",
        service="Claude (Anthropic)",
        keys=("ANTHROPIC_API_KEY",),
        make_fake=lambda settings: FakeLLM(),
        make_real=lambda settings: ("real LLM", settings.ANTHROPIC_API_KEY.get_secret_value()),
    )
    registry = AdapterRegistry(use_settings(OPENSTALL_MODE="sandbox", ANTHROPIC_API_KEY="made-up-key"), [spec])

    assert registry.status("llm") == "real"
    assert registry.get("llm") == ("real LLM", "made-up-key")


def test_each_adapter_is_made_once_and_shared(use_settings):
    registry = AdapterRegistry(use_settings())

    assert registry.llm is registry.llm
    assert registry.get("messenger") is registry.messenger


def test_an_unknown_adapter_name_is_a_clear_error(use_settings):
    with pytest.raises(KeyError, match="No adapter called 'printer'"):
        AdapterRegistry(use_settings()).get("printer")


def test_the_app_registry_is_made_once_from_the_app_settings(settings):
    assert get_registry() is get_registry()
    assert get_registry().settings is settings


def test_the_fake_gateway_sends_buyers_to_the_web_app(use_settings):
    registry = AdapterRegistry(use_settings(WEB_BASE_URL="https://openstall.example"))
    order = CheckoutRequest(
        order_id="ord_demo",
        parts=(CheckoutPart("op_001", Decimal("216.00"), "12 cushion covers, Amina"),),
        return_url="https://openstall.example/approve/ord_demo/return",
        cancel_url="https://openstall.example/approve/ord_demo?cancelled=1",
    )

    checkout = registry.payment_gateway.create_checkout(order)

    assert checkout.approval_url == f"https://openstall.example/fake-paypal?token={checkout.paypal_order_id}"
