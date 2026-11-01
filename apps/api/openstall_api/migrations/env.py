"""Alembic environment: the URL comes from the app's settings (DATABASE_URL), the tables from models.py."""

from alembic import context
from sqlalchemy import create_engine, pool

from openstall_api.db import database_url
from openstall_api.models import Base
from openstall_api.settings import get_settings

target_metadata = Base.metadata


def _url():
    return database_url(get_settings().DATABASE_URL.get_secret_value())


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,  # SQLite can only change a table by copying it; batch mode does that
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
