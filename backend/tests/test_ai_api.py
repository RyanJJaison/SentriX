from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _token(u: str, p: str) -> str:
    r = client.post("/auth/login", data={"username": u, "password": p})
    assert r.status_code == 200
    return r.json()["access_token"]


def _auth(u="analyst1", p="analyst123") -> dict:
    return {"Authorization": f"Bearer {_token(u, p)}"}


def test_status_requires_auth_and_reports_mock():
    assert client.get("/ai/status").status_code == 401
    body = client.get("/ai/status", headers=_auth()).json()
    assert body["enabled"] is True
    assert body["provider"] == "mock"
    assert body["has_api_key"] is False


def test_chat_requires_auth():
    assert client.post("/ai/chat", json={"message": "hi"}).status_code == 401


def test_general_knowledge_answer():
    r = client.post("/ai/chat", json={"message": "What is a UTXO?"}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert "UTXO" in body["message"] or "Unspent" in body["message"]
    assert body["provider"] == "mock"
    assert body["conversation_id"]


def test_context_aware_address_risk():
    r = client.post(
        "/ai/chat",
        json={
            "message": "Why is this address risky?",
            "context": {"selected_address": "1MockAddr0016"},
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert "/100" in body["message"]
    assert any(level in body["message"] for level in ("HIGH", "MEDIUM", "LOW"))
    assert any(s["type"] == "get_address_risk" for s in body["sources"])


def test_navigation_action():
    r = client.post("/ai/chat", json={"message": "open the graph view"}, headers=_auth())
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert {"type": "navigate", "target": "graph-view"} in [
        {"type": a["type"], "target": a["target"]} for a in actions
    ]
    assert "Opening" in r.json()["message"]


def test_conversation_continuity_and_clear():
    first = client.post("/ai/chat", json={"message": "Summarise my dashboard"}, headers=_auth()).json()
    cid = first["conversation_id"]
    second = client.post(
        "/ai/chat",
        json={"message": "what next?", "conversation_id": cid},
        headers=_auth(),
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == cid
    assert client.post(f"/ai/conversations/{cid}/clear", headers=_auth()).status_code == 204


def test_message_validation():
    assert client.post("/ai/chat", json={"message": ""}, headers=_auth()).status_code == 422
    assert client.post("/ai/chat", json={"message": "x" * 4001}, headers=_auth()).status_code == 422


def test_chat_is_audit_logged():
    client.post("/ai/chat", json={"message": "hello"}, headers=_auth())
    logs = client.get("/audit/logs?limit=200", headers=_auth("admin", "admin123")).json()
    assert any(e["path"] == "/ai/chat" for e in logs)
