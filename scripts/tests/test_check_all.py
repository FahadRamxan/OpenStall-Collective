"""scripts/check_all.py: runs every check in order, stops at the first failure and says what ran."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_all.py"
_spec = importlib.util.spec_from_file_location("check_all", SCRIPT)
check_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_all)


def python_step(name, code, cwd):
    """A step that runs a line of Python, so these tests never start the real checks."""
    return check_all.Step(name, [sys.executable, "-c", code], cwd)


def summary_rows(out):
    """(status, step name) for each row of the printed summary."""
    rows = re.findall(r"^  (passed|FAILED|not run)\s+(.+?)(?:\s+[\d.]+s)?$", out, re.MULTILINE)
    return [(status, name) for status, name in rows]


def test_runs_every_step_in_order(tmp_path, capsys):
    log = tmp_path / "log.txt"
    steps = [
        python_step(name, f"open({str(log)!r}, 'a').write({name!r} + '\\n')", tmp_path)
        for name in ("first", "second", "third")
    ]

    assert check_all.main(steps) == 0

    assert log.read_text().split() == ["first", "second", "third"]
    out = capsys.readouterr().out
    assert summary_rows(out) == [("passed", "first"), ("passed", "second"), ("passed", "third")]
    assert "All 3 checks passed." in out


def test_stops_at_the_first_failure(tmp_path, capsys):
    never = tmp_path / "never-created"
    steps = [
        python_step("lint", "pass", tmp_path),
        python_step("tests", "raise SystemExit(3)", tmp_path),
        python_step("e2e", f"open({str(never)!r}, 'w')", tmp_path),
    ]

    assert check_all.main(steps) == 1

    assert not never.exists()
    out = capsys.readouterr().out
    assert summary_rows(out) == [("passed", "lint"), ("FAILED", "tests"), ("not run", "e2e")]
    assert "Stopped at tests." in out
    assert "checks passed" not in out


def test_a_command_that_cannot_start_is_a_failure(tmp_path, capsys):
    missing = check_all.Step("missing tool", [str(tmp_path / "no-such-program")], tmp_path)

    assert check_all.main([missing, python_step("after", "pass", tmp_path)]) == 1

    out = capsys.readouterr().out
    assert "Could not start missing tool" in out
    assert summary_rows(out) == [("FAILED", "missing tool"), ("not run", "after")]


def test_steps_run_in_their_folder_with_their_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECK_ALL_TEST_INHERITED", "kept")
    record = tmp_path / "record.txt"
    code = (
        "import os, pathlib; "
        f"pathlib.Path({str(record)!r}).write_text("
        "os.getcwd() + '|' + os.environ['CHECK_ALL_TEST_INHERITED'] + '|' + os.environ['CHECK_ALL_TEST_EXTRA'])"
    )
    step = check_all.Step("env", [sys.executable, "-c", code], tmp_path, {"CHECK_ALL_TEST_EXTRA": "added"})

    assert check_all.main([step]) == 0

    cwd, inherited, extra = record.read_text().split("|")
    assert Path(cwd).resolve() == tmp_path.resolve()
    assert (inherited, extra) == ("kept", "added")


@pytest.mark.parametrize(
    ("windows", "relative"),
    [(True, ".venv/Scripts/python.exe"), (False, ".venv/bin/python")],
)
def test_prefers_the_repo_virtualenv(tmp_path, windows, relative):
    python = tmp_path / relative
    python.parent.mkdir(parents=True)
    python.touch()

    assert check_all.venv_python(tmp_path, windows=windows) == str(python)


def test_falls_back_to_the_python_running_the_script(tmp_path):
    assert check_all.venv_python(tmp_path, windows=True) == sys.executable
    assert check_all.venv_python(tmp_path, windows=False) == sys.executable


def test_default_steps_match_the_plan(monkeypatch):
    monkeypatch.setattr(check_all.shutil, "which", lambda name: f"/tools/{name}.cmd")
    monkeypatch.delenv("E2E_PYTHON", raising=False)

    steps = check_all.default_steps()

    assert [step.name for step in steps] == ["pytest", "npm run lint", "npm test", "npm run build", "npm run e2e"]
    assert steps[0].cwd == check_all.REPO_ROOT
    assert steps[0].command[1:] == ["-m", "pytest", "-q"]
    assert all(step.cwd == check_all.WEB_DIR for step in steps[1:])
    # npm is called by its full path (npm.cmd on Windows), never through a shell.
    assert all(step.command[0] == "/tools/npm.cmd" for step in steps[1:])
    # The e2e API runs on the same Python as pytest.
    assert steps[-1].env == {"E2E_PYTHON": steps[0].command[0]}


def test_keeps_an_e2e_python_that_is_already_set(monkeypatch):
    monkeypatch.setattr(check_all.shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setenv("E2E_PYTHON", "/opt/python3.12")

    assert check_all.default_steps()[-1].env == {"E2E_PYTHON": "/opt/python3.12"}


def test_explains_when_npm_is_missing(monkeypatch):
    monkeypatch.setattr(check_all.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit, match="Install Node 24.15 or newer"):
        check_all.default_steps()


def test_finds_the_repo_from_its_own_location():
    assert (check_all.REPO_ROOT / "pyproject.toml").is_file()
    assert (check_all.WEB_DIR / "package.json").is_file()
