"""The plan in words (prompt 26, spec 3.4): the model explains, code checks every number against the plan and the
request, and a template stands in whenever the check fails."""

from datetime import date
from decimal import Decimal

import pytest

from openstall_agents.adapters import FakeLLM, LLMCall, LLMError
from openstall_agents.explain import (
    FACTS_OPEN,
    MAX_LENGTH,
    SYSTEM,
    PlanFacts,
    Share,
    explain_plan,
    facts_json,
    fake_explanation_reply,
    template,
    ungrounded,
)
from openstall_agents.fake_answers import fake_answer

DUE = date(2026, 12, 10)


def share(name: str, quantity: int, price: str) -> Share:
    return Share(name, quantity, Decimal(price), Decimal(price) * quantity, DUE)


STORY = PlanFacts(
    shares=(share("Priya", 11, "16.00"), share("Amina", 12, "18.00"), share("Lucía", 10, "22.00"), share("Grace", 7, "29.00")),
    requested_quantity=40,
    total_quantity=40,
    total_cost=Decimal("815.00"),
    complete=True,
    shortfall=0,
    max_unit_price=Decimal("30.00"),
    deadline=DUE,
    ship_to="Chicago",
    request_text="40 hand-embroidered cushion covers for corporate gifts",
)
SHORT = PlanFacts(
    shares=(share("Grace", 4, "29.00"), share("Noor", 10, "29.50")),
    requested_quantity=40,
    total_quantity=14,
    total_cost=Decimal("411.00"),
    complete=False,
    shortfall=26,
    max_unit_price=Decimal("30.00"),
    deadline=DUE,
    ship_to="Chicago",
)


class FailingLLM(FakeLLM):
    def generate_text(self, prompt, *, system=None, images=()):
        raise LLMError("the model could not be reached")


def test_fake_modes_explainer_tells_the_story_and_passes_the_check():
    llm = FakeLLM(responder=fake_answer)

    explanation = explain_plan(STORY, llm=llm)

    assert explanation.source == "model"
    assert explanation.text == (
        "Priya, Amina, Lucía and Grace made the cheapest valid offers, so the 40 units go to them in that order: "
        "11, 12, 10 and 7. Together that is $815.00, all delivered by December 10, 2026."
    )
    call = llm.calls[0]
    assert (call.kind, call.system) == ("text", SYSTEM)
    assert FACTS_OPEN in call.prompt


def test_a_made_up_price_is_caught_and_the_template_is_used_instead():
    llm = FakeLLM(replies=["Grace gave a special price of $24.50 a cover, so the 40 cost $815.00."])

    explanation = explain_plan(STORY, llm=llm)

    assert explanation.source == "template"
    assert explanation.problem == "numbers not in the plan or the request: 24.50"
    assert explanation.text == template(STORY)


@pytest.mark.parametrize(
    ("text", "stray"),
    [
        ("Priya makes 11 and Amina 12, about 30% of the order.", ["30%"]),
        ("Grace has 7, or 18 percent.", ["18%"]),
        ("All 40 arrive by December 10, 2026.", []),
        ("All 40 arrive by December 9, 2026.", ["9"]),
        ("The total is $815, due December 10, 2026.", []),
        ("The total is $815.00, roughly $20.38 a unit.", ["20.38"]),
        ("Four makers share the forty units.", []),
        ("Five makers share the forty units.", ["five"]),
        ("Half of them come from Priya and Amina.", ["half"]),
        ("Delivery is in 2027.", ["2027"]),
        ("Grace takes 7 at $29.00 and Lucía 10 at $22.00; 1,200 would be too many.", ["1,200"]),
    ],
)
def test_every_number_and_number_word_must_be_in_the_plan_or_the_request(text, stray):
    assert ungrounded(text, STORY) == stray


def test_the_buyers_own_numbers_count_as_grounded():
    assert ungrounded("They asked for 40 covers for corporate gifts.", STORY) == []


def test_the_template_says_a_complete_plan_and_a_short_one():
    assert template(STORY) == (
        "The 40 units are split across 4 makers, cheapest valid offer first: Priya 11 at $16.00, Amina 12 at $18.00, "
        "Lucía 10 at $22.00 and Grace 7 at $29.00. The total is $815.00, and every share is due by December 10, 2026."
    )
    assert template(SHORT) == (
        "Only 14 of the 40 units can be made by December 10, 2026: Grace 4 at $29.00 and Noor 10 at $29.50, $411.00 "
        "in all. The other 26 have no valid offer."
    )
    nobody = PlanFacts((), 40, 0, Decimal("0.00"), False, 40, Decimal("30.00"), DUE, "Chicago")
    assert template(nobody) == "No maker can supply any of the 40 units by December 10, 2026."
    # The template always passes its own check.
    assert all(ungrounded(template(plan), plan) == [] for plan in (STORY, SHORT, nobody))


def test_fake_modes_explainer_says_a_short_plan_too():
    explanation = explain_plan(SHORT, llm=FakeLLM(responder=fake_answer))

    assert explanation.source == "model"
    assert explanation.text == (
        "Only Grace and Noor can deliver by December 10, 2026, so 14 of the 40 units are possible: 4 and 10, "
        "$411.00 in all."
    )


@pytest.mark.parametrize(
    ("llm", "problem"),
    [
        (FailingLLM(), "the model could not answer: the model could not be reached"),
        (FakeLLM(replies=["   "]), "the model gave no explanation"),
        (FakeLLM(replies=["Priya 11. " * 80]), f"the explanation was longer than {MAX_LENGTH} characters"),
    ],
)
def test_a_model_that_fails_gets_the_template(llm, problem):
    explanation = explain_plan(STORY, llm=llm)

    assert (explanation.source, explanation.problem, explanation.text) == ("template", problem, template(STORY))


def test_the_model_sees_numbers_formatted_once_and_the_same_way():
    facts = facts_json(STORY)

    assert facts["total_usd"] == "815.00"
    assert facts["deadline"] == "December 10, 2026"
    assert facts["shares_cheapest_first"][0] == {
        "maker": "Priya",
        "units": 11,
        "unit_price_usd": "16.00",
        "line_total_usd": "176.00",
        "delivery_date": "December 10, 2026",
    }


def test_the_fake_explainer_answers_only_explanation_requests():
    assert fake_explanation_reply(LLMCall("text", "Summarise this chat.", None, (), None)) is None
