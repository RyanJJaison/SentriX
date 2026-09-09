from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _token(username: str, password: str) -> str:
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def _auth(username="analyst1", password="analyst123") -> dict:
    return {"Authorization": f"Bearer {_token(username, password)}"}


def test_status_endpoint():
    r = client.get("/traffic/status", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["event_count"] > 0
    assert body["transaction_count"] >= 5
    assert body["window_seconds"] == 60
    assert isinstance(body["tshark_available"], bool)


def test_anomalies_endpoint_sorted_and_bounded():
    r = client.get("/traffic/anomalies?limit=10", headers=_auth())
    assert r.status_code == 200
    items = r.json()
    assert items
    scores = [i["anomaly_score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert all(0.0 <= i["confidence"] <= 1.0 for i in items)


def test_anomalies_min_score_filter():
    r = client.get("/traffic/anomalies?min_score=0.99", headers=_auth())
    assert r.status_code == 200
    assert all(i["anomaly_score"] >= 0.99 for i in r.json())


def test_transaction_correlation():
    r = client.get("/traffic/tx-suspicious-001/correlation", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["entity_id"] == "tx-suspicious-001"
    assert body["entity_type"] == "transaction"
    assert set(body["features"]) == {
        "broadcast_timing",
        "burst_activity",
        "peer_concentration",
        "propagation_irregularity",
    }
    assert body["factors"] and all(f["explanation"] for f in body["factors"])
    assert body["propagation"]["peer_count"] >= 1


def test_propagation_endpoint():
    r = client.get("/traffic/tx-normal-001/propagation", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["txid"] == "tx-normal-001"
    assert body["peers"]
    assert body["peers"][0]["delay_ms"] == 0.0


def test_peer_correlation_via_same_route():
    r = client.get("/traffic/peer-sus-01/correlation", headers=_auth())
    assert r.status_code == 200
    assert r.json()["entity_type"] == "peer"


def test_unknown_entity_is_404():
    r = client.get("/traffic/tx-does-not-exist/correlation", headers=_auth())
    assert r.status_code == 404


def test_malformed_id_is_422():
    r = client.get("/traffic/..%2Fetc/correlation", headers=_auth())
    assert r.status_code in (404, 422)
    r2 = client.get("/traffic/bad id/correlation", headers=_auth())
    assert r2.status_code == 422
