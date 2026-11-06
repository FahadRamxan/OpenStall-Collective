"""The judges' docs stay true to the code (prompt 49): every link and anchor in them leads somewhere, every command
they give names a script and flags that exist, the versions they ask for are the project's own, and every button the
walkthrough tells a judge to press is in the web app. The walkthrough itself runs in a browser in
apps/web/e2e/live-demo.spec.ts."""

import json
import re
import tomllib
from pathlib import Path

import pytest

from openstall_paypal.products import PRODUCTS, STATE_WORDS

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", ROOT / "docs" / "judges.md", ROOT / "apps" / "web" / "README.md"]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```")

# The labels the walkthrough tells a judge to look for or press, word for word as the web app shows them.
UI_LABELS = [
    "Run the story",
    "Run the demo request",
    "Open its approval page",
    "Requested by an AI agent",
    "Approve and pay with PayPal",
    "Simulated PayPal (test mode)",
    "Watch it happen on the live demo",
    "Each maker has been told about her share, in her own language.",
    "Tracking on PayPal",
    "Reset demo",
    "Your demo phone",
    "Attach the sample voice note",
    "Attach the sample photo",
    "Your listing so far",
    "Asking now",
    "Your limits",
    "Your listing is live",
    "Open your stall",
    "Confirm delivery",
    "Check its signature",
    "Check a trust passport",
    "Check the signature",
    "Put it back",
    "The order heals itself",
    "Approve the top-up",
    "Try to break it",
    "Try every attack",
    "Demand Radar tip",
    "Buy with simulated PayPal",
    "Run it with an AI agent",
    "Order complete",
    "Dispute this parcel at PayPal",
    "API online",
    "API offline",
]


def text_outside_code(path: Path) -> list[str]:
    """The document's lines, without fenced code blocks."""
    lines, fenced = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces as hyphens."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    return {slug(line.lstrip("#")) for line in text_outside_code(path) if re.match(r"^#{1,6} ", line)}


def links(path: Path) -> list[str]:
    return [target for line in text_outside_code(path) for target in LINK.findall(line)]


@pytest.mark.parametrize("doc", DOCS, ids=lambda doc: str(doc.relative_to(ROOT)))
def test_every_link_leads_to_a_file_and_every_anchor_to_a_heading(doc: Path) -> None:
    broken = []
    for target in links(doc):
        if re.match(r"^[a-z]+:", target):  # https:, mailto:
            continue
        path_part, _, anchor = target.partition("#")
        file = (doc.parent / path_part).resolve() if path_part else doc
        if not file.exists():
            broken.append(f"{target}: no such file")
        elif anchor and file.suffix == ".md" and anchor not in anchors(file):
            broken.append(f"{target}: no heading for #{anchor}")
    assert broken == []


def scripts_named(text: str) -> set[str]:
    return set(re.findall(r"python (scripts/[\w/]+\.py)", text))


def test_every_script_a_judge_runs_exists_with_the_flags_given() -> None:
    text = "\n".join(doc.read_text(encoding="utf-8") for doc in DOCS)
    named = scripts_named(text)
    assert {"scripts/seed_demo.py", "scripts/try_mcp.py", "scripts/run_demo_request.py"} <= named
    for script in named:
        source = (ROOT / script).read_text(encoding="utf-8")
        for flags in re.findall(rf"python {re.escape(script)}((?: --[\w-]+)+)", text):
            for flag in flags.split():
                assert f'"{flag}"' in source, f"{script} has no {flag}"


def test_the_quick_start_starts_the_app_it_names() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "uvicorn openstall_api.main:app --port 8000" in readme
    assert (ROOT / "apps" / "api" / "openstall_api" / "main.py").read_text(encoding="utf-8").count("app = FastAPI(") == 1
    assert "cp .env.example .env" in readme
    assert "OPENSTALL_MODE=fake" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_the_versions_asked_for_are_the_projects_own() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    python = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    node = json.loads((ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
    assert python == ">=3.11" and "Python 3.11 or newer" in readme
    assert node == "^24.15.0 || >=26.0.0" and "Node 24.15 or newer (or 26; not 25)" in readme


def test_every_button_the_walkthrough_names_is_in_the_web_app() -> None:
    walkthrough = (ROOT / "docs" / "judges.md").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "apps" / "web" / "src").rglob("*.tsx")
        if not path.name.endswith(".test.tsx")
    ).replace("&apos;", "'")
    missing_in_doc = [label for label in UI_LABELS if label not in walkthrough]
    missing_in_app = [label for label in UI_LABELS if label not in source]
    assert (missing_in_doc, missing_in_app) == ([], [])


def test_the_walkthrough_is_the_one_the_browser_test_follows() -> None:
    spec = (ROOT / "apps" / "web" / "e2e" / "live-demo.spec.ts").read_text(encoding="utf-8")
    for step in ("Run the demo request", "Open its approval page", "Approve and pay with PayPal", "courier receipt"):
        assert step in spec


def test_the_readme_s_paypal_products_table_is_the_code_s() -> None:
    """Row for row, products.py's (prompt 53): a product's state changes in one place, and /status, the doctor and the
    README all say the same."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("| Product | How far it has got |") :].split("\n\n", 1)[0].splitlines()

    assert table[2:] == [f"| {product.name} | {STATE_WORDS[product.state]} |" for product in PRODUCTS]
