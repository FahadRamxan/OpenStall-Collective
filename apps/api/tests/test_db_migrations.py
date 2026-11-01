"""Migrations: they build exactly the tables in models.py, and they can be undone."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from openstall_api.db import alembic_config, get_engine, migrate
from openstall_api.models import Base


def table_names() -> set[str]:
    return set(inspect(get_engine()).get_table_names()) - {"alembic_version"}


def test_upgrading_a_fresh_database_creates_every_table():
    migrate()

    assert table_names() == set(Base.metadata.tables)


def test_the_migrations_match_the_models_exactly():
    # If this fails, a model changed without a migration: run alembic revision --autogenerate.
    migrate()

    with get_engine().connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_downgrading_removes_every_table_and_upgrading_again_works():
    migrate()

    command.downgrade(alembic_config(), "base")
    assert table_names() == set()

    migrate()
    assert table_names() == set(Base.metadata.tables)


def test_upgrading_twice_changes_nothing():
    migrate()
    migrate()

    assert table_names() == set(Base.metadata.tables)


def test_the_app_migrates_at_start_up_when_auto_migrate_is_on():
    # The app's lifespan calls this before serving; the Playwright tests start the real app on a fresh database.
    from openstall_api.main import migrate_if_enabled

    assert migrate_if_enabled() is True
    assert table_names() == set(Base.metadata.tables)


def test_the_app_leaves_the_database_alone_when_auto_migrate_is_off(use_settings):
    from openstall_api.main import migrate_if_enabled

    use_settings(AUTO_MIGRATE="false")

    assert migrate_if_enabled() is False
    assert table_names() == set()
