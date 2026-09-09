from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _login(username: str, password: str) -> str:
    resp = client.post("/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_success():
    token = _login("investigator1", "investigate123")
    assert token


def test_login_failure():
    resp = client.post("/auth/login", data={"username": "investigator1", "password": "wrong"})
    assert resp.status_code == 401


def test_protected_route_requires_token():
    resp = client.get("/address/1SomeAddress/risk")
    assert resp.status_code == 401


def test_address_risk_with_valid_token():
    token = _login("investigator1", "investigate123")
    resp = client.get(
        "/address/1SomeAddress/risk", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == "1SomeAddress"
    assert 0.0 <= body["risk_score"] <= 1.0


def test_alerts_endpoint():
    token = _login("analyst1", "analyst123")
    resp = client.get("/alerts?threshold=0.0&limit=5", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_graph_endpoint():
    token = _login("investigator1", "investigate123")
    resp = client.get(
        "/graph/1SomeAddress?depth=1", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["center"] == "1SomeAddress"


def test_audit_log_is_admin_only():
    investigator_token = _login("investigator1", "investigate123")
    resp = client.get(
        "/audit/logs", headers={"Authorization": f"Bearer {investigator_token}"}
    )
    assert resp.status_code == 403

    admin_token = _login("admin", "admin123")
    resp = client.get("/audit/logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
