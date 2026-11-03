"""Run every check before a push: pytest, mypy on the PayPal package, then lint, npm test, npm run build and npm run
e2e in apps/web.

Stops at the first failure and prints a summary. The project has no CI, so this is the only gate.

Usage: python scripts/check_all.py
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "apps" / "web"


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)  # added to this process's environment


@dataclass(frozen=True)
class Outcome:
    step: Step
    status: Literal["passed", "failed", "not run"]
    seconds: float | None = None


def venv_python(repo_root: Path = REPO_ROOT, windows: bool = os.name == "nt") -> str:
    """The repo's virtualenv Python if there is one, else the Python running this script."""
    venv = repo_root / ".venv"
    candidate = venv / "Scripts" / "python.exe" if windows else venv / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def npm() -> str:
    """npm's full path. On Windows that is npm.cmd, which subprocess does not find from the bare name."""
    path = shutil.which("npm")
    if path is None:
        raise SystemExit("npm was not found. Install Node 24.15 or newer, then run this again.")
    return path


def default_steps() -> list[Step]:
    """The checks, in order. Later build steps add theirs here."""
    python = venv_python()
    npm_path = npm()
    # The e2e API runs on the same Python as pytest, unless E2E_PYTHON says otherwise.
    e2e_env = {"E2E_PYTHON": os.environ.get("E2E_PYTHON", python)}
    return [
        Step("pytest", [python, "-m", "pytest", "-q"], REPO_ROOT),
        # The PayPal package against APIMatic's PayPal SDK, which ships py.typed and is checked under --strict.
        Step("mypy", [python, "-m", "mypy", "--strict", "packages/paypal/openstall_paypal"], REPO_ROOT),
        Step("npm run lint", [npm_path, "run", "lint"], WEB_DIR),
        Step("npm test", [npm_path, "test"], WEB_DIR),
        Step("npm run build", [npm_path, "run", "build"], WEB_DIR),
        Step("npm run e2e", [npm_path, "run", "e2e"], WEB_DIR, e2e_env),
    ]


def run_step(step: Step) -> bool:
    """Run one step with its output going straight to the terminal. True if it exits with 0."""
    try:
        return subprocess.call(step.command, cwd=step.cwd, env={**os.environ, **step.env}) == 0
    except OSError as error:
        print(f"Could not start {step.name}: {error}", flush=True)
        return False


def run_steps(steps: list[Step]) -> list[Outcome]:
    """Run the steps in order. After the first failure, the rest are not run."""
    outcomes: list[Outcome] = []
    failed = False
    for step in steps:
        if failed:
            outcomes.append(Outcome(step, "not run"))
            continue
        print(f"\n==> {step.name} (in {step.cwd})", flush=True)
        started = time.monotonic()
        passed = run_step(step)
        outcomes.append(Outcome(step, "passed" if passed else "failed", time.monotonic() - started))
        failed = not passed
    return outcomes


def summary(outcomes: list[Outcome]) -> str:
    """Each step's outcome and time, then what to do next."""
    lines = ["", "Summary:"]
    for outcome in outcomes:
        label = "FAILED" if outcome.status == "failed" else outcome.status
        took = f"{outcome.seconds:7.1f}s" if outcome.seconds is not None else ""
        lines.append(f"  {label:<8} {outcome.step.name:<16} {took}".rstrip())
    failures = [outcome.step.name for outcome in outcomes if outcome.status == "failed"]
    if failures:
        lines.append(f"Stopped at {failures[0]}. Fix it, then run python scripts/check_all.py again. Do not push.")
    else:
        lines.append(f"All {len(outcomes)} checks passed.")
    return "\n".join(lines)


def main(steps: list[Step] | None = None) -> int:
    outcomes = run_steps(default_steps() if steps is None else steps)
    print(summary(outcomes), flush=True)
    return 0 if all(outcome.status == "passed" for outcome in outcomes) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Not every check ran, so do not push.", flush=True)
        sys.exit(130)
