"""Tests for the operator-only /admin/stats endpoint (website repo's Epic
W11): opt-in mounting, token auth, and that it reports real aggregate data
without ever returning a raw email."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from cloud_api.app import create_app
from cloud_api.auth import AuthStore


def _client(admin_stats_token: str | None = "s3cret") -> tuple[TestClient, AuthStore]:
    store = AuthStore(":memory:")
    return TestClient(create_app(auth_store=store, admin_stats_token=admin_stats_token)), store


def test_route_not_mounted_when_token_unset():
    client, _ = _client(admin_stats_token=None)
    resp = client.get("/admin/stats")
    assert resp.status_code == 404


def test_missing_token_rejected():
    client, _ = _client()
    resp = client.get("/admin/stats")
    assert resp.status_code == 401


def test_wrong_token_rejected():
    client, _ = _client()
    resp = client.get("/admin/stats", headers={"x-admin-token": "wrong"})
    assert resp.status_code == 401


def test_correct_token_returns_real_aggregate_data():
    client, _store = _client()

    client.post("/users/register", json={"email": "a@example.com"})
    client.post("/users/register", json={"email": "b@example.com"})

    resp = client.get("/admin/stats", headers={"x-admin-token": "s3cret"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["users_total"] == 2
    assert sum(day["count"] for day in body["users_by_day"]) == 2
    assert body["registration_funnel"]["accounts_created"] == 2
    assert body["registration_funnel"]["attempts"] >= 2

    # The one thing this endpoint must never do, regardless of how the
    # response shape evolves later: leak a raw email anywhere in the body.
    assert "a@example.com" not in resp.text
    assert "b@example.com" not in resp.text


def test_demo_attempts_are_counted_by_day():
    from tests.test_incremental import FakeLLMProvider
    from tests.test_mcp_server import FakeEmbeddingProvider

    store = AuthStore(":memory:")
    client = TestClient(
        create_app(
            auth_store=store,
            admin_stats_token="s3cret",
            demo_llm=FakeLLMProvider([]),
            demo_embedder=FakeEmbeddingProvider(),
        )
    )

    client.post("/demo/try", json={"text": "hello"})
    client.post("/demo/try", json={"text": "world"})

    resp = client.get("/admin/stats", headers={"x-admin-token": "s3cret"})
    assert resp.status_code == 200
    assert sum(day["count"] for day in resp.json()["demo_attempts_by_day"]) == 2


def test_registration_funnel_reflects_email_verification_flow():
    import re

    from cloud_api.email import FakeEmailSender

    store = AuthStore(":memory:")
    email_sender = FakeEmailSender()
    client = TestClient(
        create_app(
            auth_store=store,
            admin_stats_token="s3cret",
            email_sender=email_sender,
            oauth_base_url="https://api.example.com",
        )
    )

    client.post("/users/register/request", json={"email": "verify-me@example.com"})
    token = re.search(r"token=([\w-]+)", email_sender.sent[0][2]).group(1)
    client.get(f"/users/register/verify?token={token}")

    resp = client.get("/admin/stats", headers={"x-admin-token": "s3cret"})
    funnel = resp.json()["registration_funnel"]
    assert funnel["verification_emails_sent"] == 1
    assert funnel["verification_emails_clicked"] == 1
    assert funnel["accounts_created"] == 1
