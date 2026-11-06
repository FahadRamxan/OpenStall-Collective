"""The APIMatic cross-check (prompt 53): paypal-plan.md, the gateway's code and the installed SDK must agree.

paypal-plan.md is the contract sheet for our calls through APIMatic's PayPal Python SDK, written by the APIMatic
Context Plugin's process. The plan, the code and the SDK can drift apart without a test failing: a call added without
its row, a keyword the plan promises but the code no longer passes, or an SDK upgraded under both. This checks, with no
network:

1. Every SDK operation the code calls is in the plan's Operations table, and every operation there is called.
2. Each call passes exactly the keywords its row says, and no more.
3. The installed SDK has each operation, with the positional parameters and keywords the plan names.
4. The SDK the plan was checked against is the one pinned in pyproject.toml and the one installed.
"""

import ast
import inspect
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from openstall_paypal.sdk import sdk_info

__all__ = ["Finding", "PlannedCall", "code_calls", "cross_check", "planned_calls", "planned_commit", "sdk_problems"]

REPO = Path(__file__).resolve().parents[3]
CONTROLLERS = ("orders", "payments")
_PIPE = re.compile(r"(?<!\\)\|")
_ROW = re.compile(r"^\|\s*`(orders|payments)\.(\w+)`\s*\|")
_KEYWORD = re.compile(r"`(\w+)=")
_POSITIONAL = re.compile(r"`(\w+): ")
_COMMIT = re.compile(r"paypal-python-sdk\.git@([0-9a-f]{7,40})")


@dataclass(frozen=True)
class PlannedCall:
    operation: str  # for example "orders.create_order"
    positional: frozenset[str]  # its positional parameters, by name
    keywords: frozenset[str]  # the keywords we pass


@dataclass(frozen=True)
class Finding:
    check: str
    ok: bool
    detail: str


def planned_calls(plan: str) -> dict[str, PlannedCall]:
    """The rows of the plan's Operations table: each operation, its positional parameters and our keywords."""
    calls: dict[str, PlannedCall] = {}
    for line in plan.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        cells = _PIPE.split(line)
        positional, keywords = (cells[2], cells[3]) if len(cells) > 3 else ("", "")
        operation = f"{match.group(1)}.{match.group(2)}"
        calls[operation] = PlannedCall(
            operation, frozenset(_POSITIONAL.findall(positional)), frozenset(_KEYWORD.findall(keywords))
        )
    return calls


def planned_commit(text: str) -> str | None:
    """The SDK commit a text names (the plan's "SDK installed" line, or pyproject.toml's pin)."""
    match = _COMMIT.search(text)
    return match.group(1) if match else None


def code_calls(sources: Iterable[str]) -> dict[str, list[frozenset[str]]]:
    """Each `<...>.client.orders.<op>(...)` or `.client.payments.<op>(...)` call in the code, with its keywords."""
    found: dict[str, list[frozenset[str]]] = {}
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            controller = node.func.value
            if not (isinstance(controller, ast.Attribute) and controller.attr in CONTROLLERS):
                continue
            if not (isinstance(controller.value, ast.Attribute) and controller.value.attr == "client"):
                continue
            keywords = frozenset(keyword.arg for keyword in node.keywords if keyword.arg)
            found.setdefault(f"{controller.attr}.{node.func.attr}", []).append(keywords)
    return found


def sdk_problems(calls: Iterable[PlannedCall]) -> list[str]:
    """What the installed SDK lacks of the plan: an operation, a positional parameter or a keyword."""
    from paypal import PaypalClient  # the SDK, imported only when checked

    client = PaypalClient(base_url="https://api-m.sandbox.paypal.com")  # no credentials: nothing is sent
    problems: list[str] = []
    try:
        for call in calls:
            controller, name = call.operation.split(".")
            operation = getattr(getattr(client, controller), name, None)
            if operation is None:
                problems.append(f"the SDK has no {call.operation}")
                continue
            parameters = inspect.signature(operation).parameters
            for wanted in sorted(call.positional | call.keywords):
                if wanted not in parameters:
                    problems.append(f"{call.operation} takes no {wanted}")
            for wanted in sorted(call.keywords):
                if wanted in parameters and parameters[wanted].kind is not inspect.Parameter.KEYWORD_ONLY:
                    problems.append(f"{call.operation}'s {wanted} is not keyword-only, as the plan says")
    finally:
        client.close()
    return problems


def cross_check(
    plan_path: Path = REPO / "paypal-plan.md",
    code_dir: Path = Path(__file__).resolve().parent,
    pyproject: Path = REPO / "pyproject.toml",
) -> list[Finding]:
    """The four checks, each a finding. A missing plan is a finding too, not an error."""
    if not plan_path.is_file():
        return [Finding("paypal-plan.md", False, f"{plan_path.name} was not found next to the code")]
    plan = plan_path.read_text(encoding="utf-8")
    planned = planned_calls(plan)
    called = code_calls(path.read_text(encoding="utf-8") for path in sorted(code_dir.glob("*.py")))
    findings: list[Finding] = []

    unplanned = sorted(set(called) - set(planned))
    unused = sorted(set(planned) - set(called))
    gaps = []
    if not planned:
        gaps.append("the plan's Operations table has no rows")
    if unplanned:
        gaps.append(f"called but not in the plan: {', '.join(unplanned)}")
    if unused:
        gaps.append(f"in the plan but never called: {', '.join(unused)}")
    findings.append(
        Finding(
            "Every SDK call has its row in the plan",
            not gaps,
            "; ".join(gaps) or f"{len(planned)} operations, each called and each in the plan",
        )
    )

    mismatched = [
        f"{operation} passes {', '.join(sorted(keywords)) or 'no keywords'}, the plan says "
        f"{', '.join(sorted(planned[operation].keywords)) or 'none'}"
        for operation, uses in sorted(called.items())
        if operation in planned
        for keywords in uses
        if keywords != planned[operation].keywords
    ]
    findings.append(
        Finding(
            "Each call passes the keywords the plan says",
            not mismatched,
            "; ".join(mismatched) or "pay_pal_request_id and prefer exactly where the plan has them",
        )
    )

    try:
        missing = sdk_problems(planned.values())
    except ImportError:
        missing = ["APIMatic's PayPal SDK is not installed"]
    findings.append(
        Finding(
            "The installed SDK has every planned operation",
            not missing,
            "; ".join(missing) or "each operation, its parameters and keywords, by the SDK's own signatures",
        )
    )

    plan_commit = planned_commit(plan)
    pinned = planned_commit(pyproject.read_text(encoding="utf-8")) if pyproject.is_file() else None
    info = sdk_info()
    installed = info.commit if info else None
    # The installed SDK's metadata keeps its commit's first 7 characters.
    same = (
        plan_commit is not None
        and pinned is not None
        and installed is not None
        and plan_commit == pinned
        and pinned.startswith(installed)
    )
    findings.append(
        Finding(
            "The plan, the pin and the installed SDK are one commit",
            same,
            f"{info.label if info else 'the SDK'} at {installed}, as pinned and as the plan was checked against"
            if same
            else f"plan {plan_commit or 'names none'}, pyproject.toml {pinned or 'pins none'}, "
            f"installed {installed or 'unknown'}",
        )
    )
    return findings
