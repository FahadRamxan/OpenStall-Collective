"""render.yaml, the hosted demo's blueprint: no secret in git, URLs that point at each other, a deploy that never wipes
the database, media on the persistent disk, and plans that keep the demo up until judging ends."""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from pydantic import SecretStr

from openstall_api.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = ROOT / "render.yaml"
# Settings that name an account: not secret by themselves, but they belong to us, so they are entered by hand too.
ACCOUNT_SETTINGS = {"PAYPAL_CLIENT_ID", "PAYPAL_WEBHOOK_ID", "TWILIO_ACCOUNT_SID", "META_WHATSAPP_PHONE_NUMBER_ID"}
# Secrets that belong to no outside account: Render makes them when the blueprint is created.
GENERATED = {"DEMO_RUN_TOKEN", "PASSPORT_SIGNING_KEY", "META_WHATSAPP_VERIFY_TOKEN"}
HOST_ONLY = {"PYTHON_VERSION"}  # read by Render, not by the app
# Render's paid instance types, as its blueprint spec lists them (render.com/docs/blueprint-spec, November 10, 2026);
# the old names (starter, basic-256mb) are no longer listed there. Free is left out on purpose: a free web service
# sleeps after 15 idle minutes and cannot have a disk, and a free database is deleted 30 days after it is made,
# before judging ends on December 15.
PAID_SERVICE_PLANS = {
    "0.5c-512mb", "1c-2g", "2c-4g", "2c-8g", "2c-16g", "4c-8g", "4c-16g", "4c-32g", "8c-16g", "8c-32g", "8c-64g",
    "12c-24g", "12c-48g", "12c-96g",
}
PAID_DATABASE_PLANS = {
    "0.1c-256mb", "0.5c-1g", "1c-2g", "1c-4g", "2c-4g", "2c-8g", "2c-16g", "4c-16g", "4c-32g", "8c-32g", "8c-64g",
    "16c-64g", "16c-128g", "32c-128g", "32c-256g", "48c-192g", "48c-384g", "64c-256g", "64c-512g", "96c-384g",
    "96c-768g", "128c-512g", "128c-1024g",
}


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))


def service(blueprint: dict, runtime: str) -> dict:
    [found] = [entry for entry in blueprint["services"] if entry["runtime"] == runtime]
    return found


def env(entry: dict) -> dict[str, dict]:
    return {variable["key"]: variable for variable in entry["envVars"]}


def test_every_secret_is_entered_in_the_dashboard_or_generated_never_written_in_git(blueprint):
    api = env(service(blueprint, "python"))
    secrets = {
        name for name, field in Settings.model_fields.items() if field.annotation in (SecretStr, SecretStr | None)
    }
    assert GENERATED <= secrets  # only our own secrets are made by Render, never an account's id or key
    for name in (secrets | ACCOUNT_SETTINGS) - {"DATABASE_URL"}:
        if name in GENERATED:
            assert api[name] == {"key": name, "generateValue": True}, f"{name} must be generateValue: true"
        else:
            assert api[name] == {"key": name, "sync": False}, f"{name} must be sync: false in render.yaml"


def test_the_plans_keep_the_demo_up_until_judging_ends(blueprint):
    for entry in blueprint["services"]:
        assert entry["plan"] in PAID_SERVICE_PLANS, f"{entry['name']}: {entry['plan']!r} is not a paid instance type"
    for database in blueprint["databases"]:
        assert database["plan"] in PAID_DATABASE_PLANS, f"{database['name']}: {database['plan']!r} is not paid"


def test_the_host_runs_the_python_the_tests_run_on(blueprint):
    version = env(service(blueprint, "python"))["PYTHON_VERSION"]["value"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", version), "Render needs the full Python version, such as 3.13.3"
    assert tuple(int(part) for part in version.split(".")[:2]) == sys.version_info[:2]


def test_the_hosted_demo_runs_on_the_sandbox_and_pays_the_sandbox_accounts(blueprint):
    api = env(service(blueprint, "python"))
    accounts = (ROOT / "docs" / "day-one-checks.md").read_text(encoding="utf-8")

    assert api["OPENSTALL_MODE"]["value"] == "sandbox"
    for maker in ("PRIYA", "LUCIA", "NOOR"):
        payee = api[f"PAYPAL_SANDBOX_PAYEE_{maker}"]["value"]
        assert payee.endswith("@personal.example.com")  # a PayPal sandbox account, never a real one
        assert f"{payee} (`PAYPAL_SANDBOX_PAYEE_{maker}`)" in accounts


def test_the_database_url_comes_from_the_blueprints_own_database(blueprint):
    api = env(service(blueprint, "python"))
    [database] = blueprint["databases"]

    assert api["DATABASE_URL"]["fromDatabase"] == {"name": database["name"], "property": "connectionString"}
    assert database["ipAllowList"] == []


def test_every_api_variable_is_a_setting_the_app_reads(blueprint):
    api = env(service(blueprint, "python"))

    assert set(api) - HOST_ONLY <= set(Settings.model_fields)


def test_the_services_point_at_each_other(blueprint):
    api, web = service(blueprint, "python"), service(blueprint, "node")
    api_env, web_env = env(api), env(web)

    assert web_env["NEXT_PUBLIC_API_BASE_URL"]["value"] == api_env["PUBLIC_BASE_URL"]["value"]
    assert urlsplit(api_env["PUBLIC_BASE_URL"]["value"]).hostname == f"{api['name']}.onrender.com"
    assert urlsplit(api_env["WEB_BASE_URL"]["value"]).hostname == f"{web['name']}.onrender.com"
    Settings(_env_file=None, PUBLIC_BASE_URL=api_env["PUBLIC_BASE_URL"]["value"], WEB_BASE_URL=api_env["WEB_BASE_URL"]["value"])


def test_a_deploy_migrates_and_seeds_only_an_empty_database(blueprint):
    start = service(blueprint, "python")["startCommand"]

    assert "alembic upgrade head" in start
    assert "seed_demo.py --if-empty" in start
    assert "--reset" not in start


def test_seller_media_lives_on_the_persistent_disk(blueprint):
    api = service(blueprint, "python")

    assert env(api)["MEDIA_DIR"]["value"].startswith(api["disk"]["mountPath"] + "/")


def test_the_api_installs_the_postgres_driver_and_is_health_checked(blueprint):
    api = service(blueprint, "python")

    assert api["buildCommand"] == 'pip install -e ".[postgres]"'
    assert api["healthCheckPath"] == "/health"
