"""GET /api/status: the mode, the app version and each adapter's state, for the web app's /status page.

It reports which keys are missing by name, and never a key's value.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from openstall_api import __version__
from openstall_api.adapters import AdapterRegistry, AdapterStatus, get_registry
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


class StatusReport(BaseModel):
    mode: Mode
    version: str
    adapters: list[AdapterState]


@router.get("/status")
def read_status(registry: Annotated[AdapterRegistry, Depends(get_registry)], response: Response) -> StatusReport:
    # Always current: a browser or proxy must not show the mode from before a restart.
    response.headers["Cache-Control"] = "no-store"
    return StatusReport(
        mode=registry.settings.OPENSTALL_MODE,
        version=__version__,
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
