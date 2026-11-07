"""The PayPal ops agent in a terminal (prompt 55): in test mode it reaches the stand-in for PayPal's MCP server, sorts
its tools into offered, read-only and never called, and checks an order line by line."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "paypal_ops.py"
_spec = importlib.util.spec_from_file_location("paypal_ops_script", SCRIPT)
assert _spec is not None and _spec.loader is not None
paypal_ops_script = importlib.util.module_from_spec(_spec)
sys.modules["paypal_ops_script"] = paypal_ops_script
_spec.loader.exec_module(paypal_ops_script)


def test_tools_names_the_server_and_sorts_its_tools(capsys: pytest.CaptureFixture[str]) -> None:
    assert paypal_ops_script.main(["tools"]) == 0

    printed = capsys.readouterr().out
    assert printed.startswith("Test mode's stand-in for PayPal's MCP server: 8 tools")
    assert "  get_order                        offered" in printed
    assert "  create_refund                    writes: never called" in printed


def test_check_says_when_no_order_has_reached_paypal(db, capsys: pytest.CaptureFixture[str]) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="404"):
        paypal_ops_script.main(["check"])
