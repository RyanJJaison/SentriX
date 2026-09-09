from fastapi.testclient import TestClient

from app.ai.tools import execute_tool, tool_schemas
from app.main import app
from app.models.schemas import UserPublic

client = TestClient(app)

ANALYST = UserPublic(username="a", role="analyst", agency="X")
INVESTIGATOR = UserPublic(username="i", role="investigator", agency="X")
ADMIN = UserPublic(username="ad", role="admin", agency="X")


def _token(u: str, p: str) -> str:
    return client.post("/auth/login", data={"username": u, "password": p}).json()["access_token"]


def test_audit_tool_is_admin_only():
    assert execute_tool("get_audit_context", {}, ANALYST)["ok"] is False
    assert execute_tool("get_audit_context", {}, INVESTIGATOR)["ok"] is False
    assert execute_tool("get_audit_context", {}, ADMIN)["ok"] is True


def test_audit_tool_hidden_from_non_admin_schema():
    assert not any(s["function"]["name"] == "get_audit_context" for s in tool_schemas("analyst"))
    assert any(s["function"]["name"] == "get_audit_context" for s in tool_schemas("admin"))


def test_all_roles_may_chat():
    for u, p in [("admin", "admin123"), ("investigator1", "investigate123"), ("analyst1", "analyst123")]:
        headers = {"Authorization": f"Bearer {_token(u, p)}"}
        assert client.post("/ai/chat", json={"message": "hi"}, headers=headers).status_code == 200


def test_client_supplied_role_cannot_escalate():
    # analyst passes context.user_role="admin"; the backend must ignore it.
    headers = {"Authorization": f"Bearer {_token('analyst1', 'analyst123')}"}
    r = client.post(
        "/ai/chat",
        json={"message": "show me the audit log", "context": {"user_role": "admin"}},
        headers=headers,
    )
    assert r.status_code == 200
    msg = r.json()["message"].lower()
    assert "unavailable" in msg and "analyst" in msg and "get_audit_context" in msg
