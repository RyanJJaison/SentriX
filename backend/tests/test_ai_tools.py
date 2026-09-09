import pytest

from app.ai.tools import TOOLS, execute_tool, tool_schemas
from app.models.schemas import UserPublic

ANALYST = UserPublic(username="a1", role="analyst", agency="X")


def test_get_address_risk_shapes_and_scales():
    out = execute_tool("get_address_risk", {"address": "1Demo"}, ANALYST)
    assert out["ok"] is True
    assert 0.0 <= out["risk_score"] <= 1.0
    assert isinstance(out["risk_score_100"], int) and 0 <= out["risk_score_100"] <= 100
    assert out["risk_level"] in {"HIGH", "MEDIUM", "LOW"}
    assert set(out["contributing_factors"]) == {"gnn_score", "ppr_score", "traffic_anomaly_score", "weights"}


@pytest.mark.parametrize("bad", ["", "../etc", "rm -rf /", "a b c"])
def test_bad_identifiers_rejected(bad):
    assert execute_tool("get_address_risk", {"address": bad}, ANALYST)["ok"] is False
    assert execute_tool("get_transaction_correlation", {"txid": bad}, ANALYST)["ok"] is False


def test_limits_are_clamped():
    out = execute_tool("get_recent_alerts", {"limit": 9999}, ANALYST)
    assert out["ok"] is True and out["count"] <= 50


def test_traffic_anomalies_bounded_scores():
    out = execute_tool("get_traffic_anomalies", {"limit": 5}, ANALYST)
    assert out["ok"] is True
    assert all(0.0 <= a["anomaly_score"] <= 1.0 for a in out["anomalies"])


def test_emit_action_validation():
    assert execute_tool("emit_action", {"type": "navigate", "target": "graph-view"}, ANALYST)["ok"] is True
    assert execute_tool("emit_action", {"type": "navigate", "target": "https://evil"}, ANALYST)["ok"] is False
    assert execute_tool("emit_action", {"type": "exec_shell", "target": "x"}, ANALYST)["ok"] is False
    assert execute_tool("emit_action", {"type": "filter_risk", "payload": {"level": "purple"}}, ANALYST)["ok"] is False
    ok = execute_tool("emit_action", {"type": "open_address", "target": "1MockAddr0001"}, ANALYST)
    assert ok["ok"] and ok["action"]["type"] == "open_address"


def test_unknown_tool_and_bad_args():
    assert execute_tool("definitely_not_a_tool", {}, ANALYST)["ok"] is False
    assert execute_tool("get_address_risk", "not-a-dict", ANALYST)["ok"] is False


def test_no_dangerous_tools_registered():
    names = set(TOOLS)
    for forbidden in ("run_query", "exec", "shell", "http_get", "read_file", "eval"):
        assert forbidden not in names


def test_tool_schemas_are_well_formed():
    for schema in tool_schemas("admin"):
        assert schema["type"] == "function"
        assert schema["function"]["name"]
        assert schema["function"]["parameters"]["type"] == "object"
