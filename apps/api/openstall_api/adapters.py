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
    ElevenLabsSpeechToText,
    ElevenLabsTextToSpeech,
    Embedder,
    FakeEmbedder,
    FakeImageSearch,
    FakeLLM,
    FakeSpeechToText,
    FakeTextToSpeech,
    ImageSearch,
    OpenAISpeechToText,
    SpeechToText,
    TextToSpeech,
)
from openstall_agents.adapters.claude import ClaudeBuyer, ClaudeLLM
from openstall_agents.buyer_agent import BuyerModel, FakeBuyer
from openstall_agents.fake_answers import fake_answer
from openstall_api.db import reset_engine
from openstall_api.feeds import clear_catalog_cache
from openstall_api.fixtures import known_voice_notes
from openstall_api.messaging import FakeMessenger, Messenger
from openstall_api.settings import Settings, get_settings
from openstall_api.meta_whatsapp import MetaMessenger
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
    # When a setting chooses the real service (SPEECH_PROVIDER): its name and keys for those settings.
    service_for: Callable[[Settings], str] | None = None
    keys_for: Callable[[Settings], tuple[str, ...]] | None = None


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


def make_claude_buyer(settings: Settings) -> ClaudeBuyer:
    """The buyer's AI agent on Claude, with the model from LLM_MODEL. The registry checks the key is set first."""
    assert settings.ANTHROPIC_API_KEY
    return ClaudeBuyer(settings.ANTHROPIC_API_KEY.get_secret_value(), settings.LLM_MODEL)


def make_openai_speech(settings: Settings) -> OpenAISpeechToText:
    """OpenAI's transcriptions, with the model from SPEECH_MODEL. The registry checks the key is set first."""
    assert settings.OPENAI_API_KEY
    return OpenAISpeechToText(settings.OPENAI_API_KEY.get_secret_value(), settings.SPEECH_MODEL)


def make_speech(settings: Settings) -> SpeechToText:
    """The speech to text SPEECH_PROVIDER names: ElevenLabs' Scribe (the default) or OpenAI. The registry checks
    its key is set first."""
    if settings.SPEECH_PROVIDER == "openai":
        return make_openai_speech(settings)
    assert settings.ELEVENLABS_API_KEY
    return ElevenLabsSpeechToText(settings.ELEVENLABS_API_KEY.get_secret_value(), settings.ELEVENLABS_SPEECH_MODEL)


def make_voice(settings: Settings) -> ElevenLabsTextToSpeech:
    """ElevenLabs' text to speech, with VOICE_MODEL and VOICE_ID. The registry checks the key is set first."""
    assert settings.ELEVENLABS_API_KEY
    return ElevenLabsTextToSpeech(
        settings.ELEVENLABS_API_KEY.get_secret_value(), settings.VOICE_MODEL, settings.VOICE_ID
    )


def speech_service(settings: Settings) -> str:
    return "OpenAI transcription" if settings.SPEECH_PROVIDER == "openai" else "ElevenLabs Scribe"


def speech_keys(settings: Settings) -> tuple[str, ...]:
    return ("OPENAI_API_KEY",) if settings.SPEECH_PROVIDER == "openai" else ("ELEVENLABS_API_KEY",)


def make_twilio_messenger(settings: Settings) -> TwilioMessenger:
    """Twilio's WhatsApp sandbox. The registry checks the keys are set before calling it."""
    assert settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
    return TwilioMessenger(
        settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN.get_secret_value(), settings.TWILIO_WHATSAPP_FROM
    )


def make_messenger(settings: Settings) -> Messenger:
    """The WhatsApp provider WHATSAPP_PROVIDER names: Twilio, or Meta's WhatsApp Cloud API. The registry checks its
    keys are set before calling it."""
    if settings.WHATSAPP_PROVIDER == "meta":
        assert settings.META_WHATSAPP_TOKEN and settings.META_WHATSAPP_PHONE_NUMBER_ID
        return MetaMessenger(
            settings.META_WHATSAPP_TOKEN.get_secret_value(),
            settings.META_WHATSAPP_PHONE_NUMBER_ID,
            settings.META_GRAPH_VERSION,
        )
    return make_twilio_messenger(settings)


def messenger_service(settings: Settings) -> str:
    return "Meta WhatsApp Cloud API" if settings.WHATSAPP_PROVIDER == "meta" else "Twilio WhatsApp sandbox"


def messenger_keys(settings: Settings) -> tuple[str, ...]:
    if settings.WHATSAPP_PROVIDER == "meta":
        return ("META_WHATSAPP_TOKEN", "META_WHATSAPP_PHONE_NUMBER_ID")
    return ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN")


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
        name="buyer_agent",
        label="Buyer agent",
        purpose="Buys on /demo as an AI agent would: reads a person's request and chooses the MCP storefront's "
        "tools itself.",
        service="Claude (Anthropic)",
        keys=("ANTHROPIC_API_KEY",),
        make_fake=lambda settings: FakeBuyer(),
        make_real=lambda settings: make_claude_buyer(settings),
    ),
    AdapterSpec(
        name="speech_to_text",
        label="Speech to text",
        purpose="Turns sellers' voice notes into text.",
        service="ElevenLabs Scribe",
        keys=("ELEVENLABS_API_KEY",),
        make_fake=lambda settings: FakeSpeechToText(known=known_voice_notes()),
        make_real=lambda settings: make_speech(settings),
        service_for=speech_service,
        keys_for=speech_keys,
    ),
    AdapterSpec(
        name="text_to_speech",
        label="Text to speech",
        purpose="Speaks OpenStall's answers to sellers who send voice notes, in their language.",
        service="ElevenLabs (Eleven v4 Turbo)",
        keys=("ELEVENLABS_API_KEY",),
        make_fake=lambda settings: FakeTextToSpeech(),
        make_real=lambda settings: make_voice(settings),
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
        make_real=lambda settings: make_messenger(settings),
        service_for=messenger_service,
        keys_for=messenger_keys,
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
        return tuple(key for key in self.keys(name) if not self.settings.is_set(key))

    def keys(self, name: str) -> tuple[str, ...]:
        """The keys this adapter's real service needs, with these settings."""
        spec = self._spec(name)
        return spec.keys_for(self.settings) if spec.keys_for else spec.keys

    def service(self, name: str) -> str:
        """The real service behind this adapter, with these settings."""
        spec = self._spec(name)
        return spec.service_for(self.settings) if spec.service_for else spec.service

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
                service=self.service(spec.name),
                status=self.status(spec.name),
                keys=self.keys(spec.name),
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
    def buyer_agent(self) -> BuyerModel:
        return cast(BuyerModel, self.get("buyer_agent"))

    @property
    def speech_to_text(self) -> SpeechToText:
        return cast(SpeechToText, self.get("speech_to_text"))

    @property
    def text_to_speech(self) -> TextToSpeech:
        return cast(TextToSpeech, self.get("text_to_speech"))

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
                f"Sandbox mode needs {' and '.join(missing)} for the {spec.label} adapter ({self.service(spec.name)}). "
                f"Set {'it' if len(missing) == 1 else 'them'} in .env or the host's environment, "
                "or run with OPENSTALL_MODE=fake."
            )
        if spec.make_real is None:
            raise AdapterUnavailable(
                f"Sandbox mode needs the real {spec.label} adapter ({self.service(spec.name)}), and it is not built yet. "
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
