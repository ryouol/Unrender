"""Exercise Google redirects, linking, native sessions, and destructive-action proof."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from test_product import csrf_headers, settings_for

from unrender.product import google_oauth
from unrender.product.service import ProductError
from unrender.product.web import create_app

PASSWORD = "a long original password"
INTENT = "browserIntentWithEnoughEntropy123"


@pytest.fixture
def app(tmp_path, monkeypatch):
    settings = settings_for(
        tmp_path,
        base_url="http://localhost",
        initial_credits=0,
        seed_demo_account=False,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="test-secret",
        auth_rate_limit_per_minute=1000,
        global_auth_rate_limit_per_minute=1000,
    )
    monkeypatch.setattr(
        google_oauth,
        "exchange_code",
        lambda *a, **kw: {
            "sub": "google-owner",
            "email": "owner@gmail.com",
            "email_verified": True,
        },
    )
    return create_app(settings)


def callback(client, start):
    query = parse_qs(urlsplit(start.headers["location"]).query)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://localhost/auth/google/callback"]
    response = client.get(
        "/auth/google/callback",
        params={"state": query["state"][0], "code": "test-code"},
        follow_redirects=False,
    )
    return response, query["state"][0]


def signin(client, *, complete=True):
    response = callback(
        client, client.get("/auth/google/start", params={"intent": INTENT}, follow_redirects=False)
    )[0]
    if complete and response.headers["location"] == "/app":
        assert (
            client.post(
                "/api/auth/google/complete", json={"intent": INTENT}, headers=csrf_headers(client)
            ).status_code
            == 200
        )
    return response


@pytest.mark.parametrize("credits", [0, 3])
def test_google_signup_returning_login_welcome_credit_and_completion(app, credits):
    app = create_app(replace(app.state.settings, initial_credits=credits))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/public-config").json()["google_available"] is True
        assert client.get("/auth/google/start", follow_redirects=False).status_code == 422
        assert signin(client, complete=False).headers["location"] == "/app"
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/jobs").status_code == 401
        assert (
            client.post(
                "/api/auth/reauthenticate",
                json={"password": PASSWORD},
                headers=csrf_headers(client),
            ).status_code
            == 401
        )
        assert client.post("/api/auth/google/complete", json={"intent": INTENT}).status_code == 403
        assert (
            client.post(
                "/api/auth/google/complete",
                json={"intent": "wrongIntentWithEnoughLength"},
                headers=csrf_headers(client),
            ).status_code
            == 403
        )
        complete = client.post(
            "/api/auth/google/complete", json={"intent": INTENT}, headers=csrf_headers(client)
        )
        assert complete.status_code == 200
        user = client.get("/api/me").json()
        assert complete.json()["principal_marker"] == user["principal_marker"]
        assert user["credits"] == credits and user["google_connected"] and not user["has_password"]
        assert user["email_verified"]
        assert (
            client.post(
                "/api/auth/google/complete", json={"intent": INTENT}, headers=csrf_headers(client)
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@gmail.com", "password": "!"}
            ).status_code
            == 401
        )
        app.state.service.grant_credits("owner@gmail.com", credits=2, reference="test-grant")
        client.post("/api/auth/logout", headers=csrf_headers(client))
        assert signin(client).headers["location"] == "/app"
        returned = client.get("/api/me").json()
        assert returned["id"] == user["id"] and returned["credits"] == credits + 2
        with app.state.service.database.connect() as conn:
            welcome = conn.execute(
                "SELECT delta,balance_after,idempotency_key FROM credit_ledger "
                "WHERE reason='welcome_allowance'"
            ).fetchall()
            assert [tuple(row) for row in welcome] == (
                [(credits, credits, f"welcome:{user['id']}")] if credits else []
            )
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0


@pytest.mark.parametrize("credits", [0, 3])
def test_google_never_links_by_email_and_explicit_password_link_preserves_account(app, credits):
    app = create_app(replace(app.state.settings, initial_credits=credits))
    service = app.state.service
    with TestClient(app, base_url="http://localhost") as client:
        service.register("owner@gmail.com", PASSWORD)
        service.grant_credits("owner@gmail.com", credits=2, reference="existing-owner")
        response = signin(client)
        assert response.headers["location"] == "/login?google=google_link_required"
        assert client.get("/api/me").status_code == 401
        client.post("/api/auth/login", json={"email": "owner@gmail.com", "password": PASSWORD})
        before = client.get("/api/me").json()
        assert not before["email_verified"]
        assert (
            client.post(
                "/api/auth/google/link", json={"password": "wrong"}, headers=csrf_headers(client)
            ).status_code
            == 401
        )
        start = client.post(
            "/api/auth/google/link", json={"password": PASSWORD}, headers=csrf_headers(client)
        )
        assert start.status_code == 200
        query = parse_qs(urlsplit(start.json()["url"]).query)
        response = client.get(
            "/auth/google/callback",
            params={"state": query["state"][0], "code": "test"},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/app?settings=account&connected=1"
        after = client.get("/api/me").json()
        assert after["id"] == before["id"] and after["credits"] == credits + 2
        assert after["google_connected"] and after["has_password"] and after["email_verified"]
        client.post("/api/auth/logout", headers=csrf_headers(client))
        assert signin(client).headers["location"] == "/app"
        assert client.get("/api/me").json()["id"] == before["id"]


def test_one_use_state_browser_binding_cancellation_and_no_secret_errors(app, monkeypatch):
    with (
        TestClient(app, base_url="http://localhost") as client,
        TestClient(app, base_url="http://localhost") as stranger,
    ):
        start = client.get("/auth/google/start", params={"intent": INTENT}, follow_redirects=False)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        bad = stranger.get(
            "/auth/google/callback",
            params={"state": state, "code": "secret"},
            follow_redirects=False,
        )
        assert bad.headers["location"] == "/login?google=google_expired"
        good, _ = callback(client, start)
        assert good.headers["location"] == "/app"
        replay = client.get(
            "/auth/google/callback",
            params={"state": state, "code": "secret"},
            follow_redirects=False,
        )
        assert replay.headers["location"] == "/login?google=google_expired"
        start = client.get("/auth/google/start", params={"intent": INTENT}, follow_redirects=False)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        cancelled = client.get(
            "/auth/google/callback",
            params={"state": state, "error": "access_denied"},
            follow_redirects=False,
        )
        assert cancelled.headers["location"] == "/login?google=google_cancelled"

        def provider_failure(*args, **kwargs):
            raise RuntimeError("CLIENT_SECRET test-secret TOKEN secret-provider-response")

        monkeypatch.setattr(google_oauth, "exchange_code", provider_failure)
        failed = signin(client)
        assert failed.headers["location"] == "/login?google=google_failed"
        assert "test-secret" not in failed.text + str(failed.headers)


def test_google_reauthentication_requires_connected_subject_and_current_session(app, monkeypatch):
    with TestClient(app, base_url="http://localhost") as client:
        signin(client)
        owner = client.get("/api/me").json()["id"]
        session = client.cookies["unrender_session"]
        with (
            app.state.service.database.connect() as conn,
            pytest.raises(ProductError, match="Confirm your identity"),
        ):
            app.state.service.require_recent_auth(conn, user_id=owner, session_token=session)
        wrong_start = client.get("/auth/google/reauthenticate", follow_redirects=False)
        monkeypatch.setattr(
            google_oauth,
            "exchange_code",
            lambda *a, **kw: {"sub": "someone-else", "email": "other@gmail.com"},
        )
        assert (
            callback(client, wrong_start)[0]
            .headers["location"]
            .endswith("google=google_account_mismatch")
        )
        monkeypatch.setattr(
            google_oauth,
            "exchange_code",
            lambda *a, **kw: {"sub": "google-owner", "email": "owner@gmail.com"},
        )
        response, _ = callback(
            client, client.get("/auth/google/reauthenticate", follow_redirects=False)
        )
        assert response.headers["location"] == "/app?settings=account&reauthenticated=1"
        with app.state.service.database.connect() as conn:
            app.state.service.require_recent_auth(conn, user_id=owner, session_token=session)
        started = client.get("/auth/google/reauthenticate", follow_redirects=False)
        client.post("/api/auth/logout", headers=csrf_headers(client))
        assert callback(client, started)[0].headers["location"] == "/login?google=google_failed"


def test_returning_google_user_can_login_when_new_registration_closes(app):
    with TestClient(app, base_url="http://localhost") as client:
        signin(client)
        user_id = client.get("/api/me").json()["id"]
    settings = replace(app.state.settings, allow_registration=False)
    with TestClient(create_app(settings), base_url="http://localhost") as returning:
        assert signin(returning).headers["location"] == "/app"
        assert returning.get("/api/me").json()["id"] == user_id


@pytest.mark.parametrize("method", ["password", "google"])
def test_signup_welcome_grant_failure_rolls_back_account(app, monkeypatch, method):
    app = create_app(replace(app.state.settings, initial_credits=3))
    with TestClient(app, base_url="http://localhost") as client:
        service = app.state.service
        original = service._change_credits

        def fail_after_grant(*args, **kwargs):
            original(*args, **kwargs)
            raise ProductError("service_capacity_reached", "Capacity reached", 503)

        monkeypatch.setattr(service, "_change_credits", fail_after_grant)
        if method == "google":
            assert signin(client).headers["location"] == "/login?google=google_failed"
        else:
            assert (
                client.post(
                    "/api/auth/register", json={"email": "owner@gmail.com", "password": PASSWORD}
                ).status_code
                == 503
            )
        with service.database.connect() as conn:
            for table in ("users", "credit_ledger", "google_identities", "sessions"):
                assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        monkeypatch.setattr(service, "_change_credits", original)
        if method == "google":
            assert signin(client).headers["location"] == "/app"
        else:
            assert (
                client.post(
                    "/api/auth/register", json={"email": "owner@gmail.com", "password": PASSWORD}
                ).status_code
                == 201
            )
        assert client.get("/api/me").json()["credits"] == 3
        with service.database.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM credit_ledger").fetchone()[0] == 1
