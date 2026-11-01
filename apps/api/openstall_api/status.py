"""GET /api/status: the mode, the app version, the database and each adapter's state, for the web app's /status page.

It reports which keys are missing by name, and never a key's value or the database URL.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, inspect, select

from openstall_api import __version__
from openstall_api.adapters import AdapterRegistry, AdapterStatus, get_registry
from openstall_api.db import get_engine
from openstall_api.models import Base
from openstall_api.settings import Mode

router = APIRouter(prefix="/api", tags=["status"])


class AdapterState(BaseModel):
    name: str
    label: str
    purpose: str
    service: str
    status: AdapterStatus
    keys: list[str]  # the settings the real service needs, by name
    missing_keys: list[str]  # in sandbox mode, those of them that are not set


class DatabaseState(BaseModel):
    status: Literal["ok", "not migrated", "error"]
    tables: dict[str, int]  # rows per table, when the status is ok
    message: str | None = None  # what is wrong, never the URL, which can hold a password


class StatusReport(BaseModel):
    mode: Mode
    version: str
    database: DatabaseState
    adapters: list[AdapterState]


def database_state() -> DatabaseState:
    table_names = sorted(Base.metadata.tables)
    try:
        with get_engine().connect() as connection:
            existing = set(inspect(connection).get_table_names())
            missing = [name for name in table_names if name not in existing]
            if missing:
                return DatabaseState(
                    status="not migrated",
                    tables={},
                    message=f"Missing tables: {', '.join(missing)}. Run alembic upgrade head, or start the API with "
                    "AUTO_MIGRATE on.",
                )
            tables = {
                name: connection.execute(select(func.count()).select_from(Base.metadata.tables[name])).scalar_one()
                for name in table_names
            }
    except Exception as error:  # the status page must load even when the database cannot
        return DatabaseState(
            status="error", tables={}, message=f"The database could not be reached ({type(error).__name__})."
        )
    return DatabaseState(status="ok", tables=tables)


@router.get("/status")
def read_status(registry: Annotated[AdapterRegistry, Depends(get_registry)], response: Response) -> StatusReport:
    # Always current: a browser or proxy must not show the mode from before a restart.
    response.headers["Cache-Control"] = "no-store"
    return StatusReport(
        mode=registry.settings.OPENSTALL_MODE,
        version=__version__,
        database=database_state(),
        adapters=[
            AdapterState(
                name=adapter.name,
                label=adapter.label,
                purpose=adapter.purpose,
                service=adapter.service,
                status=adapter.status,
                keys=list(adapter.keys),
                missing_keys=list(adapter.missing_keys),
            )
            for adapter in registry.report()
        ],
    )
