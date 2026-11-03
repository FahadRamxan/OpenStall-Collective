"""Settings: one object read from the environment and .env, in fake mode by default, with secrets kept hidden."""

import re
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from openstall_api.adapters import reset_app_state
from openstall_api.settings import ENV_FILE, IGNORE_DOTENV, Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# A made-up value for every setting.
ENVIRONMENT = {
    "OPENSTALL_MODE": "sandbox",
    "PUBLIC_BASE_URL": "https://api.openstall.example",
    "WEB_BASE_URL": "https://openstall.example",
    "PAYPAL_CLIENT_ID": "made-up-paypal-client-id",
    "PAYPAL_CLIENT_SECRET": "made-up-paypal-secret",
    "PAYPAL_API_BASE": "https://api-m.paypal.example",
    "PAYPAL_WEBHOOK_ID": "made-up-webhook-id",
    "PAYMENT_PATH": "multiparty",
    "TWILIO_ACCOUNT_SID": "ACmadeup0000",
    "TWILIO_AUTH_TOKEN": "made-up-twilio-token",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+15550100000",
    "ANTHROPIC_API_KEY": "made-up-anthropic-key",
    "OPENAI_API_KEY": "made-up-openai-key",
    "LLM_MODEL": "made-up-model",
    "GOOGLE_VISION_API_KEY": "made-up-vision-key",
    "DATABASE_URL": "postgresql://openstall:made-up-password@db.example:5432/openstall",
    "PASSPORT_SIGNING_KEY": "bWFkZS11cCBzaWduaW5nIGtleQ==",
    "AUTO_MIGRATE": "false",
    "MEDIA_DIR": "/var/data/media",
}

SECRETS = (
    "PAYPAL_CLIENT_SECRET",
    "TWILIO_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_VISION_API_KEY",
    "PASSPORT_SIGNING_KEY",
)
KEYS = ("PAYPAL_CLIENT_ID", "PAYPAL_WEBHOOK_ID", "TWILIO_ACCOUNT_SID", *SECRETS)
# Never printed either. DATABASE_URL is not a key: it always has a value, the local SQLite file by default.
HIDDEN = (*SECRETS, "DATABASE_URL")


def plain(value: object) -> object:
    if isinstance(value, bool):
        return str(value).lower()
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def test_settings_load_from_the_environment(use_settings):
    assert set(ENVIRONMENT) == set(Settings.model_fields), "give every setting a value here"

    settings = use_settings(**ENVIRONMENT)

    assert {name: plain(getattr(settings, name)) for name in ENVIRONMENT} == ENVIRONMENT


def test_with_nothing_set_the_app_runs_locally_in_fake_mode(use_settings, monkeypatch):
    use_settings()
    monkeypatch.delenv("DATABASE_URL")  # the tests keep their own database; look at the real default
    settings = Settings(_env_file=None)

    assert settings.OPENSTALL_MODE == "fake"
    assert settings.PUBLIC_BASE_URL == "http://localhost:8000"
    assert settings.WEB_BASE_URL == "http://localhost:3000"
    assert settings.PAYPAL_API_BASE == "https://api-m.sandbox.paypal.com"
    assert settings.PAYMENT_PATH == "payouts"
    assert settings.TWILIO_WHATSAPP_FROM == "whatsapp:+14155238886"
    assert settings.LLM_MODEL == "claude-sonnet-5-5"
    assert settings.DATABASE_URL.get_secret_value() == "sqlite:///./data/openstall.db"
    assert settings.AUTO_MIGRATE is True
    assert not any(settings.is_set(key) for key in KEYS)


@pytest.mark.parametrize("value", ["sandbox", "Sandbox", " SANDBOX "])
def test_the_mode_ignores_case_and_spaces(use_settings, value):
    assert use_settings(OPENSTALL_MODE=value).OPENSTALL_MODE == "sandbox"


@pytest.mark.parametrize("value", ["production", "live", "real"])
def test_the_mode_is_fake_or_sandbox_and_nothing_else(use_settings, value):
    with pytest.raises(ValidationError, match="OPENSTALL_MODE"):
        use_settings(OPENSTALL_MODE=value)


def test_public_base_url_drops_a_trailing_slash(use_settings):
    # Webhook URLs are built by appending a path, which must not start with a double slash.
    assert use_settings(PUBLIC_BASE_URL="https://api.openstall.example/").PUBLIC_BASE_URL == (
        "https://api.openstall.example"
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PUBLIC_BASE_URL", "api.openstall.example"),  # no scheme: the MCP host check would allow an empty host
        ("PUBLIC_BASE_URL", "ftp://api.openstall.example"),
        ("WEB_BASE_URL", "openstall.example"),
        ("WEB_BASE_URL", "https://openstall.example/app"),  # a path can never match a browser's Origin
        ("WEB_BASE_URL", "https://"),
    ],
)
def test_a_bad_base_url_stops_the_app_at_start_up(use_settings, name, value):
    with pytest.raises(ValidationError, match=name):
        use_settings(**{name: value})


def test_dot_env_is_read_and_the_environment_wins(use_settings, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENSTALL_MODE=sandbox\nWEB_BASE_URL=https://from-file.example/\nLLM_MODEL=model-from-file\n",
        encoding="utf-8",
    )
    use_settings(LLM_MODEL="model-from-environment")

    settings = Settings(_env_file=env_file)

    assert settings.OPENSTALL_MODE == "sandbox"
    assert settings.WEB_BASE_URL == "https://from-file.example"
    assert settings.LLM_MODEL == "model-from-environment"


def test_the_app_reads_the_dot_env_at_the_repo_root():
    # Found from the code's location, so it loads whichever folder the API is started from. The tests no longer
    # change the class's config, so this checks what the app really uses.
    assert ENV_FILE == REPO_ROOT / ".env"
    assert Settings.model_config["env_file"] == ENV_FILE


def test_get_settings_reads_the_env_file_unless_told_to_ignore_it(use_settings, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=model-from-file\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    use_settings()

    monkeypatch.delenv(IGNORE_DOTENV)
    reset_app_state()
    assert get_settings().LLM_MODEL == "model-from-file"

    monkeypatch.setenv(IGNORE_DOTENV, "1")
    reset_app_state()
    assert get_settings().LLM_MODEL == "claude-sonnet-5-5"


def test_a_fresh_copy_of_env_example_runs_in_fake_mode_with_no_keys(use_settings, monkeypatch):
    use_settings()
    monkeypatch.delenv("DATABASE_URL")  # the tests keep their own database; check the file's own default

    settings = Settings(_env_file=ENV_EXAMPLE)

    assert settings.OPENSTALL_MODE == "fake"
    assert not any(settings.is_set(key) for key in KEYS)
    # Its `DATABASE_URL=` line is empty, and an empty value means the default.
    assert settings.DATABASE_URL.get_secret_value() == "sqlite:///./data/openstall.db"


def test_an_empty_value_in_dot_env_means_the_default(use_settings, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PAYPAL_API_BASE=\nWEB_BASE_URL=\nANTHROPIC_API_KEY=\n", encoding="utf-8")
    use_settings()

    settings = Settings(_env_file=env_file)

    assert settings.PAYPAL_API_BASE == "https://api-m.sandbox.paypal.com"
    assert settings.WEB_BASE_URL == "http://localhost:3000"
    assert settings.ANTHROPIC_API_KEY is None


def test_other_variables_in_dot_env_are_ignored(use_settings, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NEXT_PUBLIC_API_BASE_URL=http://localhost:8000\nSOME_OTHER_TOOL=1\n", encoding="utf-8")
    use_settings()

    assert Settings(_env_file=env_file).OPENSTALL_MODE == "fake"


def test_every_variable_in_env_example_is_a_setting_and_every_setting_is_in_env_example():
    in_example = re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(encoding="utf-8"), re.MULTILINE)

    assert sorted(in_example) == sorted(Settings.model_fields)


def test_secrets_stay_hidden_when_settings_are_printed_or_dumped(use_settings):
    settings = use_settings(**ENVIRONMENT)

    for name in HIDDEN:
        assert isinstance(getattr(settings, name), SecretStr), f"{name} should be a SecretStr"
        assert ENVIRONMENT[name] not in repr(settings)
        assert ENVIRONMENT[name] not in settings.model_dump_json()


def test_a_key_that_is_blank_counts_as_not_set(use_settings):
    settings = use_settings(ANTHROPIC_API_KEY="   ", PAYPAL_CLIENT_ID="  ", OPENAI_API_KEY="made-up-openai-key")

    assert not settings.is_set("ANTHROPIC_API_KEY")
    assert not settings.is_set("PAYPAL_CLIENT_ID")
    assert settings.is_set("OPENAI_API_KEY")


def test_settings_are_read_once_and_never_change(settings):
    assert get_settings() is settings
    with pytest.raises(ValidationError):
        settings.OPENSTALL_MODE = "sandbox"
