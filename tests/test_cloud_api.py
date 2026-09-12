import re

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from cloud_api.app import create_app
from cloud_api.auth import AuthStore
from cloud_api.email import FakeEmailSender
from tests.test_incremental import FakeLLMProvider, _triple
from tests.test_mcp_server import FakeEmbeddingProvider


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


def test_register_without_cors_config_has_no_cors_headers():
    # Default behaviour (no cors_allowed_origins passed): CORS stays off,
    # same as before this parameter existed -- a browser-based caller gets
    # no Access-Control-Allow-Origin and is blocked by its own browser.
    client = _client()
    resp = client.post(
        "/users/register", json={"email": "d@example.com"}, headers={"Origin": "https://spomory.yliuai.com"}
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_register_allows_configured_cors_origin():
    store = AuthStore(":memory:")
    from cloud_api.app import create_app

    client = pytest.importorskip("fastapi.testclient").TestClient(
        create_app(auth_store=store, cors_allowed_origins=["https://spomory.yliuai.com"])
    )

    preflight = client.options(
        "/users/register",
        headers={
            "Origin": "https://spomory.yliuai.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://spomory.yliuai.com"

    resp = client.post(
        "/users/register", json={"email": "e@example.com"}, headers={"Origin": "https://spomory.yliuai.com"}
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://spomory.yliuai.com"


def test_reregistering_the_same_email_reuses_the_account_not_a_duplicate():
    client = _client()

    first = client.post("/users/register", json={"email": "dup@example.com"})
    second = client.post("/users/register", json={"email": "dup@example.com"})

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["user_id"] == second.json()["user_id"]
    assert first.json()["api_key"] != second.json()["api_key"]

    # Both keys work, and both resolve to the same account -- losing a key
    # and registering again gets you a working replacement, not locked out.
    for resp in (
        client.get("/me", headers={"x-api-key": first.json()["api_key"]}),
        client.get("/me", headers={"x-api-key": second.json()["api_key"]}),
    ):
        assert resp.status_code == 200
        assert resp.json()["user_id"] == first.json()["user_id"]


def test_registration_rate_limited_per_email():
    store = AuthStore(":memory:")
    client = TestClient(create_app(auth_store=store))

    for _ in range(5):
        resp = client.post("/users/register", json={"email": "hammered@example.com"})
        assert resp.status_code == 200

    resp = client.post("/users/register", json={"email": "hammered@example.com"})
    assert resp.status_code == 429


def test_registration_rate_limited_per_ip_across_different_emails():
    store = AuthStore(":memory:")
    client = TestClient(create_app(auth_store=store), client=("203.0.113.5", 12345))

    for i in range(20):
        resp = client.post("/users/register", json={"email": f"ip-flood-{i}@example.com"})
        assert resp.status_code == 200

    resp = client.post("/users/register", json={"email": "ip-flood-20@example.com"})
    assert resp.status_code == 429


def test_registration_rate_limit_is_per_ip_not_global():
    store = AuthStore(":memory:")
    flooder = TestClient(create_app(auth_store=store), client=("203.0.113.9", 12345))
    for i in range(20):
        flooder.post("/users/register", json={"email": f"other-ip-flood-{i}@example.com"})
    assert flooder.post("/users/register", json={"email": "blocked@example.com"}).status_code == 429

    someone_else = TestClient(create_app(auth_store=store), client=("198.51.100.1", 12345))
    resp = someone_else.post("/users/register", json={"email": "unrelated@example.com"})
    assert resp.status_code == 200


def _verified_registration_client() -> tuple[TestClient, FakeEmailSender]:
    store = AuthStore(":memory:")
    email_sender = FakeEmailSender()
    client = TestClient(
        create_app(auth_store=store, email_sender=email_sender, oauth_base_url="https://api.example.com")
    )
    return client, email_sender


def test_email_verified_registration_full_flow():
    client, email_sender = _verified_registration_client()

    resp = client.post("/users/register/request", json={"email": "verified@example.com"})
    assert resp.status_code == 200
    assert len(email_sender.sent) == 1
    to, _subject, body = email_sender.sent[0]
    assert to == "verified@example.com"

    match = re.search(r"https://api\.example\.com/users/register/verify\?token=([\w-]+)", body)
    assert match is not None
    token = match.group(1)

    verify_resp = client.get(f"/users/register/verify?token={token}")
    assert verify_resp.status_code == 200
    key_match = re.search(r"<pre>(mck_[\w-]+)</pre>", verify_resp.text)
    assert key_match is not None
    api_key = key_match.group(1)

    me_resp = client.get("/me", headers={"x-api-key": api_key})
    assert me_resp.status_code == 200


def test_email_verification_token_is_single_use():
    client, email_sender = _verified_registration_client()
    client.post("/users/register/request", json={"email": "onceonly@example.com"})
    token = re.search(r"token=([\w-]+)", email_sender.sent[0][2]).group(1)

    first = client.get(f"/users/register/verify?token={token}")
    assert first.status_code == 200
    second = client.get(f"/users/register/verify?token={token}")
    assert second.status_code == 400


def test_email_verification_unknown_token_rejected():
    client, _ = _verified_registration_client()
    resp = client.get("/users/register/verify?token=not-a-real-token")
    assert resp.status_code == 400


def test_email_verified_registration_does_not_leak_key_before_verification():
    client, email_sender = _verified_registration_client()
    resp = client.post("/users/register/request", json={"email": "noreveal@example.com"})
    assert resp.status_code == 200
    assert "api_key" not in resp.json()
    assert "mck_" not in email_sender.sent[0][2]


def test_email_provider_failure_returns_clean_503_not_a_bare_500():
    # Reproduces the real bug the website team found: Resend rejects
    # sending to reserved placeholder domains like example.com (exactly
    # what every curl example in the docs uses), and that provider-side
    # failure used to propagate as an unhandled exception -- a bare 500
    # with no JSON body -- instead of an actionable error. 503, not 502:
    # this deployment sits behind Cloudflare, which was confirmed in
    # production to silently replace a 502/504 response body with its own
    # generic error page, swallowing the actual detail message.
    class ExplodingEmailSender:
        def send(self, to: str, subject: str, body: str) -> None:
            raise RuntimeError("simulated provider failure (e.g. Resend rejecting example.com)")

    store = AuthStore(":memory:")
    client = TestClient(
        create_app(auth_store=store, email_sender=ExplodingEmailSender(), oauth_base_url="https://api.example.com")
    )

    resp = client.post("/users/register/request", json={"email": "any-address@example.com"})
    assert resp.status_code == 503
    assert "failed to send" in resp.json()["detail"]


def test_register_rejects_unlisted_cors_origin():
    store = AuthStore(":memory:")
    from cloud_api.app import create_app

    client = pytest.importorskip("fastapi.testclient").TestClient(
        create_app(auth_store=store, cors_allowed_origins=["https://spomory.yliuai.com"])
    )

    resp = client.post(
        "/users/register", json={"email": "f@example.com"}, headers={"Origin": "https://evil.example.com"}
    )
    # The route itself has no Origin-based auth, so the request still
    # succeeds server-side -- what CORS actually protects is the browser
    # refusing to hand the response back to unlisted-origin JS, which shows
    # up here as the header simply not being echoed back to that origin.
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def _demo_client() -> TestClient:
    store = AuthStore(":memory:")
    triples = [_triple("张三", "任职于", "某公司")]
    return TestClient(
        create_app(auth_store=store, demo_llm=FakeLLMProvider(triples), demo_embedder=FakeEmbeddingProvider())
    )


def test_demo_endpoint_is_absent_without_llm_and_embedder():
    store = AuthStore(":memory:")
    client = TestClient(create_app(auth_store=store))
    resp = client.post("/demo/try", json={"text": "anything"})
    assert resp.status_code == 404


def test_demo_extracts_entities_and_relations_without_a_query():
    client = _demo_client()
    resp = client.post("/demo/try", json={"text": "张三任职于某公司。"})
    assert resp.status_code == 200
    body = resp.json()
    names = {e["name"] for e in body["entities"]}
    assert names == {"张三", "某公司"}
    assert len(body["relations"]) == 1
    assert body["relations"][0]["predicate"] == "任职于"
    assert body["context"] is None


def test_demo_with_query_also_returns_context():
    client = _demo_client()
    resp = client.post("/demo/try", json={"text": "张三任职于某公司。", "query": "张三在哪工作？"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["context"]
    assert "张三" in body["context"]


def test_demo_never_persists_anything():
    # Same store backs both the demo endpoint and a real registered user --
    # calling /demo/try must not touch that store at all.
    store = AuthStore(":memory:")
    triples = [_triple("张三", "任职于", "某公司")]
    client = TestClient(
        create_app(auth_store=store, demo_llm=FakeLLMProvider(triples), demo_embedder=FakeEmbeddingProvider())
    )
    client.post("/demo/try", json={"text": "张三任职于某公司。"})
    client.post("/demo/try", json={"text": "张三任职于某公司。"})
    # No user/graph tables exist on AuthStore to check directly, but two
    # identical calls producing two responses with different entity ids
    # each time is the observable proof nothing is being reused/persisted
    # across calls -- a persisted store would have deduped the second call
    # against the first.
    r1 = client.post("/demo/try", json={"text": "张三任职于某公司。"}).json()
    r2 = client.post("/demo/try", json={"text": "张三任职于某公司。"}).json()
    assert r1["entities"][0]["id"] != r2["entities"][0]["id"]


def test_demo_rejects_overly_long_text():
    client = _demo_client()
    resp = client.post("/demo/try", json={"text": "x" * 3000})
    assert resp.status_code == 400


def test_demo_rate_limited_per_ip():
    store = AuthStore(":memory:")
    triples = [_triple("张三", "任职于", "某公司")]
    client = TestClient(
        create_app(auth_store=store, demo_llm=FakeLLMProvider(triples), demo_embedder=FakeEmbeddingProvider())
    )
    for _ in range(8):
        resp = client.post("/demo/try", json={"text": "张三任职于某公司。"})
        assert resp.status_code == 200
    resp = client.post("/demo/try", json={"text": "张三任职于某公司。"})
    assert resp.status_code == 429


def test_demo_provider_failure_returns_clean_503():
    class ExplodingLLM:
        def extract_triples(self, text: str) -> list:
            raise RuntimeError("simulated provider outage")

        def generate(self, prompt: str, **kwargs: object) -> str:
            raise NotImplementedError

    store = AuthStore(":memory:")
    client = TestClient(
        create_app(auth_store=store, demo_llm=ExplodingLLM(), demo_embedder=FakeEmbeddingProvider())
    )
    resp = client.post("/demo/try", json={"text": "张三任职于某公司。"})
    assert resp.status_code == 503
