"""The guardrail panel's API (prompt 40, guardrails.py): GET /api/guardrails lists the attacks, POST
/api/guardrails/run tries every one, and POST /api/guardrails/{key}/run tries one. Always in fake mode; in sandbox mode
only with the DEMO_RUN_TOKEN header, like the other demo controls, since each run writes to the live feed and a forged
webhook asks PayPal to verify it."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openstall_api.adapters import AdapterRegistry, get_registry
from openstall_api.demo_api import demo_controls_allowed
from openstall_api.guardrails import ATTACKS, BY_KEY, Outcome, run_attack

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])

RegistryDep = Annotated[AdapterRegistry, Depends(get_registry)]


class AttackOut(BaseModel):
    key: str
    name: str
    guard: str


@router.get("")
def list_attacks() -> list[AttackOut]:
    """Every attack the panel can try, and what refuses it. Running none of them."""
    return [AttackOut(key=attack.key, name=attack.name, guard=attack.guard) for attack in ATTACKS]


@router.post("/run", dependencies=[Depends(demo_controls_allowed)])
async def run_every_attack(registry: RegistryDep) -> list[Outcome]:
    """Try every attack, one after the other. Each refusal is recorded in the live feed."""
    return [await run_attack(attack.key, registry) for attack in ATTACKS]


@router.post("/{key}/run", dependencies=[Depends(demo_controls_allowed)])
async def run_one_attack(key: str, registry: RegistryDep) -> Outcome:
    """Try one attack. Its refusal is recorded in the live feed."""
    if key not in BY_KEY:
        raise HTTPException(status_code=404, detail=f"There is no attack called {key!r}.")
    return await run_attack(key, registry)
