import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from cloud_api.app import create_app
from cloud_api.auth import AuthStore


def _client(rate_limit_per_key: int = 1000) -> TestClient:
    store = AuthStore(":memory:")
    return TestClient(create_app(auth_store=store, rate_limit_per_key=rate_limit_per_key))


def test_register_then_call_protected_endpoint():
    client = _client()

    resp = client.post("/users/register", json={"email": "a@example.com"})
    assert resp.status_code == 200
    api_key = resp.json()["api_key"]
    assert api_key.startswith("mck_")

    resp = client.get("/me", headers={"x-api-key": api_key})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == client.app.state.auth_store._conn.execute(
        "SELECT id FROM users"
    ).fetchone()[0]


def test_invalid_api_key_rejected():
    client = _client()
    resp = client.get("/me", headers={"x-api-key": "not-a-real-key"})
    assert resp.status_code == 401


def test_revoked_key_immediately_stops_working():
    client = _client()
    store: AuthStore = client.app.state.auth_store

    resp = client.post("/users/register", json={"email": "b@example.com"})
    api_key = resp.json()["api_key"]

    resp = client.get("/me", headers={"x-api-key": api_key})
    assert resp.status_code == 200

    user = store.authenticate(api_key)
    store.revoke_key(user.api_key_id)

    resp = client.get("/me", headers={"x-api-key": api_key})
    assert resp.status_code == 401


def test_quota_exceeded_returns_429():
    client = _client(rate_limit_per_key=2)
    resp = client.post("/users/register", json={"email": "c@example.com"})
    api_key = resp.json()["api_key"]

    for _ in range(2):
        resp = client.get("/me", headers={"x-api-key": api_key})
        assert resp.status_code == 200

    resp = client.get("/me", headers={"x-api-key": api_key})
    assert resp.status_code == 429
