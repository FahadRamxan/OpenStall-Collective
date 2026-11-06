"""The APIMatic cross-check (prompt 53): paypal-plan.md, the gateway's SDK calls and the installed SDK agree, and each
kind of drift between them is found."""

from pathlib import Path

import pytest

from openstall_paypal.crosscheck import (
    REPO,
    PlannedCall,
    code_calls,
    cross_check,
    planned_calls,
    planned_commit,
    sdk_problems,
)
from openstall_paypal.products import PRODUCTS, STATE_WORDS

PLAN = REPO / "paypal-plan.md"
GATEWAY = Path(__file__).resolve().parents[1] / "openstall_paypal"


def test_the_plan_the_code_and_the_installed_sdk_agree() -> None:
    findings = cross_check()

    assert [finding.check for finding in findings] == [
        "Every SDK call has its row in the plan",
        "Each call passes the keywords the plan says",
        "The installed SDK has every planned operation",
        "The plan, the pin and the installed SDK are one commit",
    ]
    assert [(finding.check, finding.ok) for finding in findings if not finding.ok] == []
    assert findings[0].detail == "6 operations, each called and each in the plan"


def test_the_operations_table_is_read_with_each_row_s_parameters_and_keywords() -> None:
    planned = planned_calls(PLAN.read_text(encoding="utf-8"))

    assert planned["orders.create_order"] == PlannedCall(
        "orders.create_order", frozenset({"body"}), frozenset({"pay_pal_request_id", "prefer"})
    )
    assert planned["orders.authorize_order"].keywords == {"pay_pal_request_id", "prefer", "body"}
    assert planned["orders.get_order"] == PlannedCall("orders.get_order", frozenset({"id_"}), frozenset())
    # "no `pay_pal_request_id`, no `prefer`" is read as no keywords: the route takes neither.
    assert planned["orders.create_order_tracking"].keywords == frozenset()
    assert planned["orders.create_order_tracking"].positional == {"id_", "body"}


def plan_without(row_start: str) -> str:
    return "\n".join(line for line in PLAN.read_text(encoding="utf-8").splitlines() if not line.startswith(row_start))


def test_a_call_the_plan_does_not_list_is_found(tmp_path: Path) -> None:
    plan = tmp_path / "paypal-plan.md"
    plan.write_text(plan_without("| `payments.void_payment`"), encoding="utf-8")

    [rows, *_] = cross_check(plan_path=plan)

    assert not rows.ok
    assert rows.detail == "called but not in the plan: payments.void_payment"


def test_a_planned_call_the_code_never_makes_is_found(tmp_path: Path) -> None:
    code = tmp_path / "gateway.py"
    code.write_text(
        (GATEWAY / "sandbox.py").read_text(encoding="utf-8").replace("client.payments.void_payment(", "void("),
        encoding="utf-8",
    )

    [rows, *_] = cross_check(code_dir=tmp_path)

    assert (rows.ok, rows.detail) == (False, "in the plan but never called: payments.void_payment")


def test_a_keyword_the_plan_does_not_promise_is_found(tmp_path: Path) -> None:
    (tmp_path / "gateway.py").write_text(
        "def go(self):\n"
        "    self.sdk.client.orders.get_order('5O1', pay_pal_request_id='x')\n"
        "    self.sdk.client.orders.create_order(body, prefer='return=representation')\n",
        encoding="utf-8",
    )

    keywords = cross_check(code_dir=tmp_path)[1]

    assert not keywords.ok
    assert keywords.detail == (
        "orders.create_order passes prefer, the plan says pay_pal_request_id, prefer; "
        "orders.get_order passes pay_pal_request_id, the plan says none"
    )


def test_code_calls_reads_each_call_s_keywords_and_ignores_other_clients() -> None:
    found = code_calls(
        [
            "self.sdk.client.payments.void_payment(hold, pay_pal_request_id='k', prefer='p')\n"
            "self.client.post('/v1/payments/payouts', {}, idempotency_key='k')\n"
            "orders.create_order(body)\n"  # not through the SDK's client
        ]
    )

    assert found == {"payments.void_payment": [frozenset({"pay_pal_request_id", "prefer"})]}


def test_an_operation_or_keyword_the_sdk_lacks_is_found() -> None:
    problems = sdk_problems(
        [
            PlannedCall("orders.ship_it", frozenset(), frozenset()),
            PlannedCall("orders.get_order", frozenset({"id_"}), frozenset({"pay_pal_request_id"})),
            PlannedCall("orders.create_order", frozenset({"body"}), frozenset({"body"})),
        ]
    )

    assert problems == [
        "the SDK has no orders.ship_it",
        "orders.get_order takes no pay_pal_request_id",
        "orders.create_order's body is not keyword-only, as the plan says",
    ]


def test_a_plan_checked_against_another_sdk_commit_is_found(tmp_path: Path) -> None:
    plan = tmp_path / "paypal-plan.md"
    text = PLAN.read_text(encoding="utf-8")
    pinned = planned_commit(text)
    assert pinned is not None and len(pinned) == 40
    plan.write_text(text.replace(pinned, "0" * 40), encoding="utf-8")

    commit = cross_check(plan_path=plan)[3]

    assert not commit.ok
    assert commit.detail.startswith(f"plan {'0' * 40}, pyproject.toml {pinned}, installed {pinned[:7]}")


def test_no_plan_is_a_finding_not_an_error(tmp_path: Path) -> None:
    [finding] = cross_check(plan_path=tmp_path / "paypal-plan.md")

    assert (finding.ok, finding.detail) == (False, "paypal-plan.md was not found next to the code")


# The PayPal products table (prompt 53)


def test_each_product_says_how_far_it_has_got_and_why() -> None:
    assert len({product.name for product in PRODUCTS}) == len(PRODUCTS)
    for product in PRODUCTS:
        assert product.state in STATE_WORDS and product.evidence and product.used_for
        if product.state == "proven":
            assert "November 3" in product.evidence, product.key  # proven means run on the sandbox, on a day
        if product.state == "not built":
            assert (product.calls, product.code) == ((), ""), product.key
            assert f"Prompt {product.prompts}" in product.evidence, product.key
        else:
            assert product.code, product.key


@pytest.mark.parametrize("product", [product for product in PRODUCTS if product.code], ids=lambda p: p.key)
def test_each_built_product_names_files_that_exist(product: object) -> None:
    code = getattr(product, "code")
    first = code.split(", ")[0]
    folder = (REPO / first).parent
    for name in code.split(", "):
        path = REPO / name if "/" in name else folder / name
        assert path.is_file(), path


def test_the_simulated_products_are_the_rails_the_sandbox_cannot_pay() -> None:
    assert {product.key for product in PRODUCTS if product.state == "simulated"} == {"venmo", "hyperwallet"}
