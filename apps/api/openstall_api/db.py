"""The database: engine, sessions, migrations, and the Money column type the models share.

SQLite for local runs and tests, Postgres on the hosted demo. The tables are in models.py.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Integer, Numeric, create_engine, event
from sqlalchemy.engine import URL, Dialect, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator, TypeEngine

from openstall_allocator import usd
from openstall_api.settings import ENV_FILE, get_settings

REPO_ROOT = ENV_FILE.parent
MIGRATIONS = Path(__file__).resolve().parent / "migrations"
CENT = Decimal("0.01")


def database_url(raw: str) -> URL:
    """The SQLAlchemy URL for a DATABASE_URL value.

    Hosts such as Render hand out Postgres URLs as postgres://, which SQLAlchemy does not accept, and we use the
    psycopg (version 3) driver. A relative SQLite path is taken from the repo root, so it does not depend on the
    folder the API starts in, and its folder is created.
    """
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw.removeprefix("postgres://")
    url = make_url(raw)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(path))
    return url


class Money(TypeDecorator[Decimal]):
    """US dollars in whole cents, exact on every database.

    NUMERIC(10, 2) on Postgres. SQLite has no exact decimal type (SQLAlchemy would go through floats), so there the
    column holds whole cents in an INTEGER, which also keeps comparisons such as price <= 9.50 correct. Amounts go
    through openstall_allocator.usd, so a negative or sub-cent amount is refused instead of rounded.
    """

    impl = Numeric(10, 2)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Integer())
        return dialect.type_descriptor(Numeric(10, 2, asdecimal=True))

    def process_bind_param(self, value: object, dialect: Dialect) -> Decimal | int | None:
        if value is None:
            return None
        amount = usd(value)  # type: ignore[arg-type]
        return int(amount * 100) if dialect.name == "sqlite" else amount

    def process_result_value(self, value: object, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        if dialect.name == "sqlite":
            return (Decimal(value) / 100).quantize(CENT)  # type: ignore[arg-type]
        return Decimal(value).quantize(CENT)  # type: ignore[arg-type]


_engine: Engine | None = None
_sessions: sessionmaker[Session] | None = None
_lock = threading.Lock()


def _sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # SQLite ignores foreign keys unless each connection asks for them.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine() -> Engine:
    """The app's engine, made once from DATABASE_URL."""
    global _engine, _sessions
    with _lock:
        if _engine is None:
            url = database_url(get_settings().DATABASE_URL.get_secret_value())
            if url.get_backend_name() == "sqlite":
                # FastAPI runs sync endpoints in a thread pool, so connections move between threads.
                _engine = create_engine(url, connect_args={"check_same_thread": False})
                event.listen(_engine, "connect", _sqlite_foreign_keys)
            else:
                _engine = create_engine(url, pool_pre_ping=True)
            _sessions = sessionmaker(_engine, expire_on_commit=False)
        return _engine


def reset_engine() -> None:
    """Close the engine's connections and forget it, so the next use reads DATABASE_URL again."""
    global _engine, _sessions
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _sessions = None


def new_session() -> Session:
    get_engine()
    assert _sessions is not None
    return _sessions()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request. Endpoints commit what they change."""
    with new_session() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session for scripts and background work: commits on success, rolls back on any error."""
    with new_session() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def alembic_config() -> Config:
    """Alembic settings for the app's database, without an alembic.ini (the CLI uses the one at the repo root)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return config


def migrate(revision: str = "head") -> None:
    """Bring the database to `revision`, the latest by default. The URL comes from the settings (migrations/env.py)."""
    command.upgrade(alembic_config(), revision)
