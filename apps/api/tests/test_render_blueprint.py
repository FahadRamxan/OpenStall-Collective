"""render.yaml, the hosted demo's blueprint: no secret in git, URLs that point at each other, a deploy that never wipes
the database, and media on the persistent disk."""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from pydantic import SecretStr

from openstall_api.settings import Settings

BLUEPRINT = Path(__file__).resolve().parents[3] / "render.yaml"
# Settings that name an account: not secret by themselves, but they belong to us, so they are entered by hand too.
ACCOUNT_SETTINGS = {"PAYPAL_CLIENT_ID", "PAYPAL_WEBHOOK_ID", "TWILIO_ACCOUNT_SID"}
HOST_ONLY = {"PYTHON_VERSION"}  # read by Render, not by the app


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))


def service(blueprint: dict, runtime: str) -> dict:
    [found] = [entry for entry in blueprint["services"] if entry["runtime"] == runtime]
    return found


def env(entry: dict) -> dict[str, dict]:
    return {variable["key"]: variable for variable in entry["envVars"]}


def test_every_secret_is_entered_in_the_dashboard_never_written_in_git(blueprint):
    api = env(service(blueprint, "python"))
    secrets = {
        name for name, field in Settings.model_fields.items() if field.annotation in (SecretStr, SecretStr | None)
    }
    for name in (secrets | ACCOUNT_SETTINGS) - {"DATABASE_URL"}:
        assert api[name] == {"key": name, "sync": False}, f"{name} must be sync: false in render.yaml"


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
