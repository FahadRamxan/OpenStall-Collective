"""Settings: one object, read from the environment and, in development, from the repo's .env file.

Environment variables win over .env. An empty value counts as unset, so a fresh copy of .env.example
changes nothing.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# fake: deterministic stand-ins for PayPal, Twilio and the AI models. sandbox: the real sandboxes and models.
Mode = Literal["fake", "sandbox"]

# How sellers are paid (docs/day-one-checks.md). payouts: the platform holds the buyer's authorization and pays each
# seller with PayPal Payouts when she ships. multiparty: each seller is a payee on the PayPal order herself.
PaymentPath = Literal["multiparty", "payouts"]

# The repo root's .env, found from this file, not the working directory, so it loads wherever the API starts.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Set to 1 to ignore the .env file and read only real environment variables. The tests set it.
IGNORE_DOTENV = "OPENSTALL_IGNORE_DOTENV"


class Settings(BaseSettings):
    """Every setting the app reads. Each name is the environment variable it comes from (see .env.example)."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        # .env may also hold variables for other tools, such as the web app's NEXT_PUBLIC_API_BASE_URL.
        extra="ignore",
        str_strip_whitespace=True,
        frozen=True,
    )

    OPENSTALL_MODE: Mode = "fake"

    # Where the API is reachable from outside. The MCP server only accepts this host and localhost.
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    # Where the web app runs. Browsers may call the API (CORS) only from this origin.
    WEB_BASE_URL: str = "http://localhost:3000"

    PAYPAL_CLIENT_ID: str | None = None
    PAYPAL_CLIENT_SECRET: SecretStr | None = None
    PAYPAL_API_BASE: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_WEBHOOK_ID: str | None = None
    PAYMENT_PATH: PaymentPath = "payouts"
    # Sandbox personal accounts the seeded makers are paid to, in sandbox mode only (made in the Developer Dashboard
    # with country IN, MX and GB). Empty: that maker's payout rail is "not connected yet", and her share is never
    # captured. Grace is paid on Venmo, which the sandbox simulates; Amina has no PayPal rail (prompt 52).
    PAYPAL_SANDBOX_PAYEE_PRIYA: str | None = None
    PAYPAL_SANDBOX_PAYEE_LUCIA: str | None = None
    PAYPAL_SANDBOX_PAYEE_NOOR: str | None = None

    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: SecretStr | None = None
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    ANTHROPIC_API_KEY: SecretStr | None = None
    OPENAI_API_KEY: SecretStr | None = None
    LLM_MODEL: str = "claude-sonnet-5-5"
    # OpenAI's model for voice notes. whisper-1 also says which language it heard; other models do not.
    SPEECH_MODEL: str = "whisper-1"
    # Unlocks /demo's Run and Reset controls in sandbox mode (header X-Demo-Run-Token). Unset: they are off there.
    DEMO_RUN_TOKEN: SecretStr | None = None
    GOOGLE_VISION_API_KEY: SecretStr | None = None

    # Can hold a password (hosted Postgres), so it is never shown, like the keys. Read it with get_secret_value().
    DATABASE_URL: SecretStr = SecretStr("sqlite:///./data/openstall.db")
    # Apply database migrations when the API starts. On by default for local runs; the host sets it explicitly.
    AUTO_MIGRATE: bool = True

    # Seller photos and voice notes. A relative path is taken from the repo root; on Render, a persistent disk.
    MEDIA_DIR: str = "data/media"

    # Trust passports: Ed25519 private key, base64.
    PASSPORT_SIGNING_KEY: SecretStr | None = None

    @field_validator("OPENSTALL_MODE", "PAYMENT_PATH", mode="before")
    @classmethod
    def _choice_ignores_case(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("PUBLIC_BASE_URL", "WEB_BASE_URL")
    @classmethod
    def _base_url(cls, url: str, info: ValidationInfo) -> str:
        # A bad value would otherwise fail quietly later: the MCP host check or CORS would just refuse requests.
        url = url.rstrip("/")  # Browsers send Origin without one, and paths such as /api/... are appended.
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"{info.field_name} must be a full http(s) URL like https://example.com, not {url!r}")
        if info.field_name == "WEB_BASE_URL" and (parts.path or parts.query or parts.fragment):
            raise ValueError(f"WEB_BASE_URL must be an origin with no path, like https://example.com, not {url!r}")
        return url

    def is_set(self, name: str) -> bool:
        """Whether the setting `name` has a value, without handing the value out."""
        value = getattr(self, name)
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        return bool(value)


@lru_cache
def get_settings() -> Settings:
    """The app's settings, read once per process. Tests clear this cache to read them again."""
    if os.environ.get(IGNORE_DOTENV) == "1":
        return Settings(_env_file=None)
    return Settings()
