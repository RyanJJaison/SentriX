from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _token(username: str, password: str) -> str:
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_requires_authentication():
    for path in ("/traffic/status", "/traffic/anomalies", "/traffic/tx-normal-001/correlation"):
        assert client.get(path).status_code == 401


def test_all_analyst_roles_allowed():
    for username, password in [
        ("admin", "admin123"),
        ("investigator1", "investigate123"),
        ("analyst1", "analyst123"),
    ]:
        headers = {"Authorization": f"Bearer {_token(username, password)}"}
        assert client.get("/traffic/anomalies", headers=headers).status_code == 200


def test_invalid_token_rejected():
    r = client.get("/traffic/status", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_traffic_requests_are_audit_logged():
    analyst = {"Authorization": f"Bearer {_token('analyst1', 'analyst123')}"}
    client.get("/traffic/anomalies", headers=analyst)

    admin = {"Authorization": f"Bearer {_token('admin', 'admin123')}"}
    logs = client.get("/audit/logs?limit=200", headers=admin).json()
    assert any(e["path"] == "/traffic/anomalies" for e in logs)
