"""The adapter registry: which implementation of each outside service the app uses, chosen by OPENSTALL_MODE.

Fake mode uses the deterministic fakes and needs no keys. Sandbox mode uses the real services and never falls back
to a fake: if a key is missing, or the real adapter is not built yet, using it raises AdapterUnavailable, which names
the adapter. Each build step that adds a real adapter sets its spec's make_real.
"""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

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
from openstall_agents.adapters.claude import ClaudeLLM
from openstall_agents.fake_answers import fake_answer
from openstall_api.db import reset_engine
from openstall_api.feeds import clear_catalog_cache
from openstall_api.messaging import FakeMessenger, Messenger
from openstall_api.settings import Settings, get_settings
from openstall_api.whatsapp import TwilioMessenger
from openstall_paypal import FakeGateway, MultipartyGateway, PaymentGateway, PayoutsGateway

# fake: a stand-in, in fake mode. real: the real service, in sandbox mode. missing key: sandbox mode, but a key the
# real service needs is not set. not built: sandbox mode with the keys set, but the real adapter does not exist yet.
AdapterStatus = Literal["fake", "real", "missing key", "not built"]


class AdapterUnavailable(RuntimeError):
    """Sandbox mode needs a real adapter that cannot be made: a key is missing, or it is not built yet."""


@dataclass(frozen=True)
class AdapterSpec:
    """One outside service: who it is for people, which keys its real implementation needs, and how to make each."""

    name: str  # its name in the API, for example "llm"
    label: str  # its name for people, for example "LLM"
    purpose: str  # what OpenStall uses it for
    service: str  # the real service behind it in sandbox mode
    keys: tuple[str, ...]  # the settings the real service needs; names only
    make_fake: Callable[[Settings], Any]
    make_real: Callable[[Settings], Any] | None = None  # None until a build step adds the real adapter


def make_paypal_gateway(settings: Settings) -> PaymentGateway:
    """The sandbox gateway for the chosen payment path. The registry checks the keys are set before calling it.

    It holds two clients for the same PayPal REST app: APIMatic's PayPal SDK for Orders and Payments, and our own
    PayPalClient for Payouts and webhook checks, which that SDK does not cover. Both are told the base URL.
    """
    assert settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET
    gateway = MultipartyGateway if settings.PAYMENT_PATH == "multiparty" else PayoutsGateway
    return gateway.connect(
        settings.PAYPAL_API_BASE, settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET.get_secret_value()
    )


def make_claude(settings: Settings) -> ClaudeLLM:
    """Claude through Anthropic's SDK, with the model from LLM_MODEL. The registry checks the key is set first."""
    assert settings.ANTHROPIC_API_KEY
    return ClaudeLLM(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.LLM_MODEL)


def make_twilio_messenger(settings: Settings) -> TwilioMessenger:
    """Twilio's WhatsApp sandbox. The registry checks the keys are set before calling it."""
    assert settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
    return TwilioMessenger(
        settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN.get_secret_value(), settings.TWILIO_WHATSAPP_FROM
    )


ADAPTERS: tuple[AdapterSpec, ...] = (
    AdapterSpec(
        name="llm",
        label="LLM",
        purpose="Reads sellers' photos and messages, and writes listings, offers and replies.",
        service="Claude (Anthropic)",
        keys=("ANTHROPIC_API_KEY",),
        make_fake=lambda settings: FakeLLM(responder=fake_answer),
        make_real=lambda settings: make_claude(settings),
    ),
    AdapterSpec(
        name="speech_to_text",
        label="Speech to text",
        purpose="Turns sellers' voice notes into text.",
        service="OpenAI transcription",
        keys=("OPENAI_API_KEY",),
        make_fake=lambda settings: FakeSpeechToText(),
    ),
    AdapterSpec(
        name="embedder",
        label="Embedder",
        purpose="Groups searches nobody could serve, for Demand Radar.",
        service="OpenAI embeddings",
        keys=("OPENAI_API_KEY",),
        make_fake=lambda settings: FakeEmbedder(),
    ),
    AdapterSpec(
        name="messenger",
        label="Messenger",
        purpose="Sends WhatsApp messages to sellers.",
        service="Twilio WhatsApp sandbox",
        keys=("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"),
        make_fake=lambda settings: FakeMessenger(),
        make_real=lambda settings: make_twilio_messenger(settings),
    ),
    AdapterSpec(
        name="payment_gateway",
        label="Payment gateway",
        purpose="PayPal checkout, and paying each seller.",
        service="PayPal sandbox",
        keys=("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"),
        make_fake=lambda settings: FakeGateway(settings.WEB_BASE_URL, settings.PAYMENT_PATH),
        make_real=lambda settings: make_paypal_gateway(settings),
    ),
    AdapterSpec(
        name="image_search",
        label="Image search",
        purpose="Checks that product photos are the seller's own.",
        service="Google Cloud Vision",
        keys=("GOOGLE_VISION_API_KEY",),
        make_fake=lambda settings: FakeImageSearch(),
    ),
)


@dataclass(frozen=True)
class AdapterReport:
    """An adapter's state for the status page: names and states only, never a key's value."""

    name: str
    label: str
    purpose: str
    service: str
    status: AdapterStatus
    keys: tuple[str, ...]
    missing_keys: tuple[str, ...]


class AdapterRegistry:
    """Makes each adapter on first use and keeps it, so the whole process shares one fake or one client."""

    def __init__(self, settings: Settings, specs: Sequence[AdapterSpec] = ADAPTERS) -> None:
        self.settings = settings
        self._specs = {spec.name: spec for spec in specs}
        self._made: dict[str, Any] = {}
        # Reentrant, so an adapter that is made from another adapter cannot deadlock.
        self._lock = threading.RLock()

    def missing_keys(self, name: str) -> tuple[str, ...]:
        """The keys this adapter needs that are not set. Always empty in fake mode, which needs none."""
        if self.settings.OPENSTALL_MODE == "fake":
            return ()
        return tuple(key for key in self._spec(name).keys if not self.settings.is_set(key))

    def status(self, name: str) -> AdapterStatus:
        spec = self._spec(name)
        if self.settings.OPENSTALL_MODE == "fake":
            return "fake"
        if self.missing_keys(name):
            return "missing key"
        return "real" if spec.make_real is not None else "not built"

    def report(self) -> list[AdapterReport]:
        """Every adapter's state, in a fixed order."""
        return [
            AdapterReport(
                name=spec.name,
                label=spec.label,
                purpose=spec.purpose,
                service=spec.service,
                status=self.status(spec.name),
                keys=spec.keys,
                missing_keys=self.missing_keys(spec.name),
            )
            for spec in self._specs.values()
        ]

    def get(self, name: str) -> Any:
        """The adapter called `name` for this mode. Raises AdapterUnavailable if sandbox mode cannot have it."""
        with self._lock:
            if name not in self._made:
                self._made[name] = self._make(self._spec(name))
            return self._made[name]

    @property
    def llm(self) -> LLM:
        return cast(LLM, self.get("llm"))

    @property
    def speech_to_text(self) -> SpeechToText:
        return cast(SpeechToText, self.get("speech_to_text"))

    @property
    def embedder(self) -> Embedder:
        return cast(Embedder, self.get("embedder"))

    @property
    def messenger(self) -> Messenger:
        return cast(Messenger, self.get("messenger"))

    @property
    def payment_gateway(self) -> PaymentGateway:
        return cast(PaymentGateway, self.get("payment_gateway"))

    @property
    def image_search(self) -> ImageSearch:
        return cast(ImageSearch, self.get("image_search"))

    def close(self) -> None:
        """Close every adapter made so far that holds connections (the PayPal clients), and forget them all."""
        with self._lock:
            made, self._made = self._made, {}
        for adapter in made.values():
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

    def _spec(self, name: str) -> AdapterSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError(f"No adapter called {name!r}. Adapters: {', '.join(self._specs)}") from None

    def _make(self, spec: AdapterSpec) -> Any:
        if self.settings.OPENSTALL_MODE == "fake":
            return spec.make_fake(self.settings)
        missing = self.missing_keys(spec.name)
        if missing:
            raise AdapterUnavailable(
                f"Sandbox mode needs {' and '.join(missing)} for the {spec.label} adapter ({spec.service}). "
                f"Set {'it' if len(missing) == 1 else 'them'} in .env or the host's environment, "
                "or run with OPENSTALL_MODE=fake."
            )
        if spec.make_real is None:
            raise AdapterUnavailable(
                f"Sandbox mode needs the real {spec.label} adapter ({spec.service}), and it is not built yet. "
                "Run with OPENSTALL_MODE=fake until it is."
            )
        return spec.make_real(self.settings)


_registry: AdapterRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> AdapterRegistry:
    """The app's registry, made exactly once from the app's settings.

    A lock rather than lru_cache: FastAPI calls this from a thread pool, and lru_cache can build it twice when
    the first calls overlap, which would give some requests a different set of fakes or clients.
    """
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = AdapterRegistry(get_settings())
        return _registry


def reset_app_state() -> None:
    """Forget the settings, the registry and the database engine, so the next call reads settings again and makes
    fresh adapters and a fresh connection pool. The old registry's clients are closed, and the cached /catalog.json,
    built from the old settings and database, is dropped."""
    global _registry
    with _registry_lock:
        registry, _registry = _registry, None
    if registry is not None:
        registry.close()
    get_settings.cache_clear()
    reset_engine()
    clear_catalog_cache()
