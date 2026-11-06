"""Look for secrets in the repository: every tracked file, and every line its git history ever added (spec section 7:
"Repo scan finds no secrets in files or git history").

    python scripts/scan_secrets.py            tracked files and the whole history
    python scripts/scan_secrets.py --files    tracked files only

It looks for the shapes of real keys (Anthropic, OpenAI, ElevenLabs, PayPal, Twilio, GitHub, AWS, private keys) and,
when this computer has a .env, for that file's own secret values wherever they should never be. It also checks that
.env itself is not tracked. It prints where it found one and which kind, never the value, and exits with 1 if it
found any. scripts/tests/test_scan_secrets.py runs it with the tests.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The shapes of real keys. Test values are made up to miss these on purpose ("sk-ant-made-up-4c7b").
PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API key": re.compile(r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}"),
    "OpenAI API key": re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}"),
    "ElevenLabs API key": re.compile(r"\bsk_[0-9a-f]{40,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    # Secrets with no shape of their own, found by the setting they are given to.
    "PayPal client secret": re.compile(r"PAYPAL_CLIENT_SECRET\s*[=:]\s*[\"']?[A-Za-z0-9_-]{40,}"),
    "Twilio auth token": re.compile(r"TWILIO_AUTH_TOKEN\s*[=:]\s*[\"']?[0-9a-f]{32}\b"),
    "Passport signing key": re.compile(r"PASSPORT_SIGNING_KEY\s*[=:]\s*[\"']?[A-Za-z0-9+/]{43}="),
    "Demo run token": re.compile(r"DEMO_RUN_TOKEN\s*[=:]\s*[\"']?[A-Za-z0-9_-]{16,}"),
}
# Settings in .env whose values are secret. A PayPal client id is public (the JS SDK puts it in the page), and the
# sandbox payees are account names, not keys.
SECRET_NAME = re.compile(r"(SECRET|TOKEN|PASSWORD|_API_KEY|SIGNING_KEY|DATABASE_URL)$")
MIN_SECRET = 8  # shorter values are flags and words, not secrets
SKIPPED_FILES = (".env.example",)  # holds only empty settings and their comments
# A value that says it is not real, as the tests' values do ("made-up-demo-token"). A real value from .env is found
# whatever it says.
MADE_UP = re.compile(r"made[-_ ]?up|example|fake|dummy|placeholder", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    where: str  # a path and line, or a commit
    kind: str

    def __str__(self) -> str:
        return f"{self.where}: {self.kind}"


def env_secrets(env: Path) -> dict[str, str]:
    """This computer's own secret values from .env, by setting name. Never printed."""
    if not env.is_file():
        return {}
    found = {}
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip("'\"")
        if SECRET_NAME.search(name) and len(value) >= MIN_SECRET:
            found[name] = value
    return found


def scan_text(where: str, text: str, secrets: dict[str, str]) -> Iterator[Finding]:
    for kind, pattern in PATTERNS.items():
        if any(not MADE_UP.search(match.group(0)) for match in pattern.finditer(text)):
            yield Finding(where, kind)
    for name, value in secrets.items():
        if value in text:
            yield Finding(where, f"the value of {name} from .env")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def scan_files(secrets: dict[str, str]) -> Iterator[Finding]:
    tracked = git("ls-files", "-z").split("\0")
    if ".env" in tracked:
        yield Finding(".env", "the .env file itself is tracked")
    for name in tracked:
        if not name or name.endswith(SKIPPED_FILES):
            continue
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pictures and other binary files
            continue
        for number, line in enumerate(text.splitlines(), 1):
            yield from scan_text(f"{name}:{number}", line, secrets)


def scan_history(secrets: dict[str, str]) -> Iterator[Finding]:
    """Every line any commit on any branch ever added, so a secret committed once and deleted is found too."""
    commit = ""
    for line in git("log", "--all", "-p", "--no-color", "--no-ext-diff", "--format=commit %h").splitlines():
        if line.startswith("commit "):
            commit = line.split(" ", 1)[1]
        elif line.startswith("+") and not line.startswith("+++"):
            yield from scan_text(f"commit {commit}", line, secrets)


def scan(history: bool = True, env: Path = ROOT / ".env") -> list[Finding]:
    secrets = env_secrets(env)
    found: Iterable[Finding] = scan_files(secrets)
    if history:
        found = [*found, *scan_history(secrets)]
    return sorted(set(found), key=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--files", action="store_true", help="tracked files only, not the git history")
    args = parser.parse_args(argv)
    found = scan(history=not args.files)
    for finding in found:
        print(finding)
    where = "tracked files" if args.files else "tracked files and git history"
    print(f"{len(found)} secret{'s' if len(found) != 1 else ''} found in {where}." if found else f"No secrets in {where}.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
