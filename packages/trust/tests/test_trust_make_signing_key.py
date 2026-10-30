"""scripts/make_signing_key.py prints a working key pair."""

import subprocess
import sys
from pathlib import Path

from openstall_trust import load_private_key, load_public_key, public_key_b64

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "make_signing_key.py"


def run_script() -> list[str]:
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def test_prints_a_private_key_for_env_and_its_public_key():
    env_line, public_line = run_script()
    name, _, private_b64 = env_line.partition("=")
    assert name == "PASSPORT_SIGNING_KEY"
    # A comment line, so the whole output can be pasted into .env as it is.
    assert public_line.startswith("# public key (safe to share): ")
    public_b64 = public_line.removeprefix("# public key (safe to share): ")
    assert public_key_b64(load_private_key(private_b64)) == public_b64
    assert public_key_b64(load_public_key(public_b64)) == public_b64


def test_each_run_makes_a_new_key():
    assert run_script()[0] != run_script()[0]
