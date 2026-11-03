"""The plan explained in words (spec 3.4: "the model only explains the result in words").

The allocator decides the split; the model writes 2 or 3 plain sentences about it for the human who approves the
order and for the buyer's agent: why these makers, why this split, the total and the delivery date. A grounding check
in code reads every number in those sentences (digits, money, dates and number words) and accepts the text only if
each one is in the plan or the request. Otherwise, or if the model cannot answer, a template written from the plan
is used, so no explanation ever carries a number the plan does not.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from openstall_agents.adapters.llm import LLM, JSONObject, LLMCall, LLMError

MAX_LENGTH = 600  # characters: 2 or 3 sentences

SYSTEM = (
    "You explain an order plan to the person who will approve it, in 2 or 3 short, plain sentences. Say why these "
    "makers (the cheapest valid offers come first), how the quantity is split between them, the total, and the "
    "delivery date. Use only numbers that appear in the facts, written as they are there; add no other number, "
    "percentage, price or date. If the plan is short, say how many units are possible. No lists, no headings."
)

FACTS_OPEN = '<facts kind="plan_explanation">'
FACTS_CLOSE = "</facts>"
_FACTS = re.compile(re.escape(FACTS_OPEN) + r"\s*(\{.*?\})\s*" + re.escape(FACTS_CLOSE), re.S)

# Number words a model might use instead of digits; each is checked like a digit. "One" is left out: it is too
# common a word ("one approval") to read as a number. Words for a multiple are never grounded.
_WORDS = {
    "zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
    "half": -1, "dozen": -1, "double": -1, "twice": -1,
}  # fmt: skip
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Share:
    """One maker's line of the plan."""

    seller_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date


@dataclass(frozen=True)
class PlanFacts:
    """The plan and the request it answers: everything an explanation may mention."""

    shares: tuple[Share, ...]
    requested_quantity: int
    total_quantity: int
    total_cost: Decimal
    complete: bool
    shortfall: int
    max_unit_price: Decimal
    deadline: date
    ship_to: str
    request_text: str = ""


@dataclass(frozen=True)
class Explanation:
    """The words to show, and where they came from: the model, or the template when the model's failed the check."""

    text: str
    source: Literal["model", "template"]
    problem: str | None = None  # why the model's words were not used, if they were not


def explain_plan(plan: PlanFacts, *, llm: LLM) -> Explanation:
    """2 or 3 sentences about the plan: the model's if every number in them is grounded, else the template."""
    try:
        text = " ".join(llm.generate_text(explain_prompt(plan), system=SYSTEM).split())
    except LLMError as error:
        return Explanation(template(plan), "template", f"the model could not answer: {error}")
    if not text:
        return Explanation(template(plan), "template", "the model gave no explanation")
    if len(text) > MAX_LENGTH:
        return Explanation(template(plan), "template", f"the explanation was longer than {MAX_LENGTH} characters")
    stray = ungrounded(text, plan)
    if stray:
        return Explanation(template(plan), "template", f"numbers not in the plan or the request: {', '.join(stray)}")
    return Explanation(text, "model")


def explain_prompt(plan: PlanFacts) -> str:
    facts = {
        "requested_units": plan.requested_quantity,
        "units_planned": plan.total_quantity,
        "complete": plan.complete,
        "units_short": plan.shortfall,
        "total_usd": _money(plan.total_cost),
        "buyer_max_unit_price_usd": _money(plan.max_unit_price),
        "deadline": _day(plan.deadline),
        "ship_to": plan.ship_to,
        "makers": len(plan.shares),
        "shares_cheapest_first": [
            {
                "maker": share.seller_name,
                "units": share.quantity,
                "unit_price_usd": _money(share.unit_price),
                "line_total_usd": _money(share.line_total),
                "delivery_date": _day(share.delivery_date),
            }
            for share in plan.shares
        ],
        "buyer_request_text": plan.request_text,
    }
    body = json.dumps(facts, indent=1, ensure_ascii=False)
    return f"{FACTS_OPEN}\n{body}\n{FACTS_CLOSE}\n\nExplain this plan in 2 or 3 plain sentences."


def ungrounded(text: str, plan: PlanFacts) -> list[str]:
    """The numbers in the text that are in neither the plan nor the request, as written there."""
    allowed = _allowed(plan)
    stray: list[str] = []
    lowered = text.lower()
    for match in _NUMBER.finditer(lowered):
        written = match.group().rstrip(".,")
        # A percentage is never grounded: the facts hold none, so the model worked it out itself.
        percent = re.match(r"\s*(%|per ?cent)", lowered[match.end() :])
        if percent or _value(written) not in allowed:
            stray.append(written + ("%" if percent else ""))
    for match in _WORD.finditer(lowered):
        word = match.group()
        if word in _WORDS and _WORDS[word] not in allowed:
            stray.append(word)
    return stray


def template(plan: PlanFacts) -> str:
    """The explanation written from the plan alone: what to show whenever the model's words fail the check."""
    by = _day(plan.deadline)
    if not plan.shares:
        return f"No maker can supply any of the {plan.requested_quantity} units by {by}."
    shares = _join([f"{s.seller_name} {s.quantity} at ${_money(s.unit_price)}" for s in plan.shares])
    makers = "1 maker" if len(plan.shares) == 1 else f"{len(plan.shares)} makers"
    if plan.complete:
        return (
            f"The {plan.requested_quantity} units are split across {makers}, cheapest valid offer first: {shares}. "
            f"The total is ${_money(plan.total_cost)}, and every share is due by {by}."
        )
    return (
        f"Only {plan.total_quantity} of the {plan.requested_quantity} units can be made by {by}: {shares}, "
        f"${_money(plan.total_cost)} in all. The other {plan.shortfall} have no valid offer."
    )


def fake_explanation_reply(call: LLMCall) -> str | None:
    """Fake mode's explainer: the story told in its own words from the facts, the same on every run. None for any
    request that is not an explanation."""
    match = _FACTS.search(call.prompt)
    if call.kind != "text" or match is None:
        return None
    facts: dict[str, Any] = json.loads(match.group(1))
    shares = facts["shares_cheapest_first"]
    if not shares:
        return f"No maker has a valid offer for any of the {facts['requested_units']} units by {facts['deadline']}."
    names = _join([share["maker"] for share in shares])
    split = _join([str(share["units"]) for share in shares])
    if facts["complete"]:
        return (
            f"{names} made the cheapest valid offers, so the {facts['requested_units']} units go to them in that "
            f"order: {split}. Together that is ${facts['total_usd']}, all delivered by {facts['deadline']}."
        )
    return (
        f"Only {names} can deliver by {facts['deadline']}, so {facts['units_planned']} of the "
        f"{facts['requested_units']} units are possible: {split}, ${facts['total_usd']} in all."
    )


def _allowed(plan: PlanFacts) -> set[Decimal]:
    numbers: set[Decimal] = {
        Decimal(plan.requested_quantity),
        Decimal(plan.total_quantity),
        Decimal(plan.shortfall),
        Decimal(len(plan.shares)),
        plan.total_cost,
        plan.max_unit_price,
    }
    days = {plan.deadline}
    for share in plan.shares:
        numbers |= {Decimal(share.quantity), share.unit_price, share.line_total}
        days.add(share.delivery_date)
    for day in days:
        numbers |= {Decimal(day.day), Decimal(day.year), Decimal(day.month)}
    numbers |= {_value(found) for found in _NUMBER.findall(plan.request_text)} - {None}
    return {number.normalize() for number in numbers if number is not None}


def _value(written: str) -> Decimal | None:
    try:
        return Decimal(written.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def _day(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def _join(items: Sequence[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def facts_json(plan: PlanFacts) -> JSONObject:
    """The facts as the model saw them, for tests and the log."""
    match = _FACTS.search(explain_prompt(plan))
    assert match is not None
    return json.loads(match.group(1))  # type: ignore[no-any-return]
