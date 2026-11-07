"""The PayPal ops agent (prompt 55): OpenStall's records checked against PayPal through PayPal's own MCP server (test
mode's stand-in here), differences said plainly, and an agent that answers in words from the read tools and can never
call one that writes."""

import asyncio
from datetime import date

import pytest
import respx
from fastapi.testclient import TestClient

from openstall_agents.buyer_agent import AgentTurn, ToolCall
from openstall_api import paypal_ops
from openstall_api.adapters import get_registry
from openstall_api.main import app
from openstall_api.models import Order, OrderPart
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order

client = TestClient(app)
TODAY = date(2026, 11, 3)


@pytest.fixture
def reserved(db):
    """The story's order at simulated PayPal, approved and reserved, and Priya paid on (simulated) proof."""
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    assert client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve").status_code == 200
    priya = next(part for part in db.get(Order, DEMO_ORDER_ID).parts if part.seller_id == "s_priya")
    assert client.post(f"/api/dev/parts/{priya.id}/proof").status_code == 200
    db.expire_all()
    return db


def test_the_ops_agent_is_offered_the_tools_that_read_and_never_one_that_writes(db):
    response = client.get("/api/paypal/ops/tools")

    assert response.status_code == 200
    body = response.json()
    assert body["server"] == "Test mode's stand-in for PayPal's MCP server"
    tools = {tool["name"]: tool for tool in body["tools"]}
    assert {name for name, tool in tools.items() if tool["offered"]} == {
        "get_order",
        "list_disputes",
        "get_dispute",
        "get_shipment_tracking",
        "list_transactions",
    }
    for name in ("pay_order", "create_refund", "accept_dispute_claim"):
        assert tools[name] == {"name": name, "reads": False, "offered": False}


def test_the_latest_order_checked_with_paypal_agrees_line_by_line(reserved):
    response = client.post("/api/paypal/ops/check")

    assert response.status_code == 200
    check = response.json()
    assert (check["order_id"], check["agrees"]) == (DEMO_ORDER_ID, True)
    assert check["paypal_order_id"].startswith("FAKE-")
    findings = {finding["check"]: finding for finding in check["findings"]}
    assert findings["The order's status"] == {
        "check": "The order's status",
        "ok": True,
        "ours": "partly shipped",
        "paypal": "COMPLETED",  # PayPal shows an authorized order as COMPLETED
    }
    assert (findings["The amount"]["ours"], findings["The amount"]["paypal"]) == ("$815.00", "$815.00")
    assert findings["The authorization holding the money"]["paypal"].endswith(" CREATED")
    assert findings["Priya's capture"]["ok"] is True
    assert findings["Priya's tracking"] == {
        "check": "Priya's tracking",
        "ok": True,
        "ours": findings["Priya's tracking"]["ours"],
        "paypal": "on the order",
    }
    assert findings["Disputes"]["paypal"] == "none"


def test_a_difference_from_paypal_is_said_plainly(reserved):
    priya = next(part for part in reserved.get(Order, DEMO_ORDER_ID).parts if part.seller_id == "s_priya")
    priya.capture_id = "CAPTURE-PAYPAL-NEVER-MADE"
    reserved.commit()

    check = client.post("/api/paypal/ops/check").json()

    assert check["agrees"] is False
    [capture] = [finding for finding in check["findings"] if finding["check"] == "Priya's capture"]
    assert (capture["ok"], capture["paypal"]) == (False, "no such capture")


def test_an_order_paypal_has_never_seen_is_said_so(db):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()

    check = client.post("/api/paypal/ops/check", params={"order_id": DEMO_ORDER_ID}).json()

    assert check["agrees"] is False
    assert check["findings"] == [
        {"check": "The order at PayPal", "ok": False, "ours": "not sent to PayPal yet", "paypal": "nothing"}
    ]


def test_the_ops_agent_answers_from_what_paypal_said(reserved):
    response = client.post("/api/paypal/ops/ask", json={"question": "Is the latest order's money still held at PayPal?"})

    assert response.status_code == 200
    answer = response.json()
    assert answer["agent"] == "Test mode's stand-in for the ops agent"
    assert [step["tool"] for step in answer["steps"]] == ["get_order", "list_disputes"]
    assert answer["answer"].startswith("PayPal says order FAKE-")
    assert "is COMPLETED, for $815.00: authorization" in answer["answer"]
    assert "with 1 capture ($176.00 taken)" in answer["answer"]
    assert answer["answer"].endswith("0 disputes are open at PayPal.")
    assert answer["refused"] == []


class Greedy:
    """An agent that tries to refund the payment it just read about."""

    label = "An agent that tries a refund"

    def conversation(self):
        return self

    def begin(self, system, request, tools):
        return AgentTurn(said="", calls=(ToolCall("c1", "create_refund", {"capture_id": "C1"}),))

    def answer(self, results):
        return AgentTurn(said=f"I could not: {results[-1].text}")


def test_a_tool_that_writes_is_refused_before_it_reaches_paypal(reserved, monkeypatch):
    monkeypatch.setattr(paypal_ops, "FakeOpsAgent", Greedy)

    answer = asyncio.run(paypal_ops.ask(get_registry(), "Refund Priya's payment."))

    assert answer.refused == ["create_refund"]
    assert answer.steps[0].ok is False
    assert answer.answer == "I could not: TOOL_REFUSED: create_refund changes something at PayPal; the ops agent only reads"


def test_in_sandbox_mode_the_check_and_the_agent_need_the_demo_token(db, use_settings):
    use_settings(OPENSTALL_MODE="sandbox", DEMO_RUN_TOKEN="made-up-demo-token")

    assert client.post("/api/paypal/ops/check").status_code == 401
    assert client.post("/api/paypal/ops/ask", json={"question": "Any disputes?"}).status_code == 401


def test_without_node_the_sandbox_says_why_paypal_s_server_cannot_start(db, use_settings, monkeypatch):
    use_settings(OPENSTALL_MODE="sandbox", PAYPAL_CLIENT_ID="made-up-id", PAYPAL_CLIENT_SECRET="made-up-secret")
    monkeypatch.setattr("openstall_paypal.paypal_mcp.npx_path", lambda: None)

    with respx.mock(base_url="https://api-m.sandbox.paypal.com") as paypal:
        paypal.post("/v1/oauth2/token").respond(json={"access_token": "TOKEN", "expires_in": 32400})
        response = client.get("/api/paypal/ops/tools")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "PayPal's MCP server could not be reached: NPX_MISSING: PayPal's MCP server runs with Node's npx, which is not "
        "installed here"
    )
