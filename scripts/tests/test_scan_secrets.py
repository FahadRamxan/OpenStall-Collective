"""The secret scan (prompt 46, spec section 7: "Repo scan finds no secrets in files or git history"): the repository
is clean, files and history, and each kind of real key would be found. The keys below are built while the test runs,
so this file itself holds none."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scan_secrets.py"
_spec = importlib.util.spec_from_file_location("scan_secrets", SCRIPT)
assert _spec is not None and _spec.loader is not None
scan_secrets = importlib.util.module_from_spec(_spec)
sys.modules["scan_secrets"] = scan_secrets
_spec.loader.exec_module(scan_secrets)

HEX = "0123456789abcdef"


def test_the_repository_and_its_whole_history_hold_no_secret() -> None:
    found = scan_secrets.scan(history=True)

    assert [str(finding) for finding in found] == []


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key = " + "sk-ant-" + "api03-" + "Ab1_" * 10, "Anthropic API key"),
        ("OPENAI_API_KEY=" + "sk-" + "proj-" + "Zx9" * 16, "OpenAI API key"),
        ("ELEVENLABS_API_KEY=" + "sk" + "_" + HEX * 3, "ElevenLabs API key"),
        ("token " + "gh" + "p_" + "A1b2C3" * 7, "GitHub token"),
        ("AKIA" + "ABCDEFGHIJKLMNOP", "AWS access key"),
        ("-----BEGIN " + "OPENSSH PRIVATE KEY-----", "Private key"),
        ("PAYPAL_CLIENT_SECRET=" + "E" + "Kq9-" * 15, "PayPal client secret"),
        ("TWILIO_AUTH_TOKEN=" + HEX * 2, "Twilio auth token"),
        ("PASSPORT_SIGNING_KEY=" + "Qk" * 21 + "a=", "Passport signing key"),
        ("DEMO_RUN_TOKEN=" + "r4nd0m-" * 3, "Demo run token"),
    ],
)
def test_each_kind_of_real_key_is_found(text: str, kind: str) -> None:
    assert [finding.kind for finding in scan_secrets.scan_text("f.py:1", text, {})] == [kind]


def test_a_value_that_says_it_is_made_up_is_not_a_secret() -> None:
    assert list(scan_secrets.scan_text("t.py:1", 'DEMO_RUN_TOKEN="made-up-demo-token"', {})) == []
    assert list(scan_secrets.scan_text("t.py:1", "sk-ant-made-up-4c7b", {})) == []


def test_this_computer_s_own_secret_values_are_found_wherever_they_are_and_never_shown(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    secret = "Pq" + "7z" * 10
    env.write_text(f"PAYPAL_CLIENT_ID=public-id-is-fine\nPAYPAL_CLIENT_SECRET={secret}\nLLM_MODEL=claude\n", encoding="utf-8")

    values = scan_secrets.env_secrets(env)

    assert set(values) == {"PAYPAL_CLIENT_SECRET"}  # a client id is public, a model name is not a secret
    [finding] = scan_secrets.scan_text("notes.md:3", f"the secret is {secret}", values)
    assert str(finding) == "notes.md:3: the value of PAYPAL_CLIENT_SECRET from .env"
    assert secret not in str(finding)


def test_the_script_prints_where_never_what(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert scan_secrets.main(["--files"]) == 0
    assert capsys.readouterr().out.strip() == "No secrets in tracked files."
