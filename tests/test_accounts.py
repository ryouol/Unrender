"""Public signup, email ownership, recovery, and durable account regressions."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_product import service_for, settings_for

from unrender.product.database import SCHEMA_VERSION
from unrender.product.service import ProductError
from unrender.product.web import create_app

PASSWORD = "a long original password"
NEW_PASSWORD = "a different long password"


def email_settings(tmp_path):
    return settings_for(
        tmp_path,
        require_email_verification=True,
        smtp_host="smtp.example.com",
        smtp_username="user",
        smtp_password="test-only-secret",
        email_from="hello@example.com",
        initial_credits=0,
        auth_rate_limit_per_minute=100,
    )


def test_signup_verify_login_reset_and_restart(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    settings = email_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD}
        )
        assert response.status_code == 201
        assert response.json()["verification_required"]
        assert "unrender_session" not in client.cookies
        token = deliveries[-1][-1]
        service = app.state.service
        with service.database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email='owner@example.com'").fetchone()
            user_id = user["id"]
            assert token not in str(dict(user))
            assert user["credit_balance"] == 0
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/verify-email", json={"token": token, "password": "wrong password"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/auth/verify-email", json={"token": token, "password": PASSWORD}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/auth/verify-email", json={"token": token, "password": PASSWORD}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )
        session = client.cookies["unrender_session"]
        assert client.get("/api/me").json()["email"] == "owner@example.com"
        client.headers["X-CSRF-Token"] = client.cookies["unrender_csrf"]
        key = client.post("/api/keys", json={"name": "before reset"})
        assert key.status_code == 201
        assert (
            client.post(
                "/api/auth/forgot-password", json={"email": "owner@example.com"}
            ).status_code
            == 200
        )
        reset_token = deliveries[-1][-1]
        assert (
            client.post(
                "/api/auth/reset-password", json={"token": reset_token, "password": NEW_PASSWORD}
            ).status_code
            == 200
        )
        assert service.session_user(session) is None
        with service.database.connect() as conn:
            assert conn.execute(
                "SELECT revoked_at FROM api_keys WHERE user_id=?", (user_id,)
            ).fetchone()[0]
        assert client.get("/api/me").status_code == 401
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/reset-password", json={"token": reset_token, "password": NEW_PASSWORD}
            ).status_code
            == 400
        )
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": NEW_PASSWORD}
            ).status_code
            == 200
        )
        assert client.get("/api/me").json()["id"] == user_id


def test_recovery_is_generic_expiring_single_purpose_and_origin_checked(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    app = create_app(email_settings(tmp_path))
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/forgot-password", json={"email": "absent@example.com"}
        ).json() == {"ok": True}
        assert not deliveries
        client.post("/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD})
        token = deliveries[-1][-1]
        assert (
            client.post(
                "/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/auth/verify-email",
                headers={"Origin": "https://attacker.example"},
                json={"token": token, "password": PASSWORD},
            ).status_code
            == 403
        )
        with app.state.service.database.transaction() as conn:
            conn.execute("UPDATE account_challenges SET expires_at='2000-01-01'")
        assert (
            client.post(
                "/api/auth/verify-email", json={"token": token, "password": PASSWORD}
            ).status_code
            == 400
        )


def test_production_signup_requires_email_and_zero_welcome_spend(tmp_path):
    settings = replace(
        email_settings(tmp_path),
        environment="production",
        worker_enabled=True,
        base_url="https://unrender.example",
        extractor_backend="modal",
        seed_demo_account=False,
        modal_model_path="owner/model",
        modal_model_revision="a" * 40,
        modal_model_digest="b" * 64,
        modal_provider_release="c" * 64,
    )
    settings.validate()
    with pytest.raises(ValueError, match="verified email"):
        replace(settings, require_email_verification=False).validate()
    with pytest.raises(ValueError, match="zero credits"):
        replace(settings, initial_credits=3).validate()
    with pytest.raises(ValueError, match="verified email"):
        replace(settings, smtp_password="").validate()


def test_v8_migration_preserves_existing_accounts(tmp_path):
    service = service_for(tmp_path)
    account = service.register("old@example.com", PASSWORD)
    user_id = service.session_user(account["session"])["id"]
    with service.database.transaction() as conn:
        conn.execute("DROP TABLE account_challenges")
        conn.execute('ALTER TABLE users DROP COLUMN "email_verified"')
        conn.execute("UPDATE schema_meta SET version=8")
    service.database.initialize()
    assert service.session_user(account["session"])["id"] == user_id
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT email_verified FROM users").fetchone()[0] == 1


def test_in_flight_old_password_login_cannot_survive_reset(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    service = service_for(
        tmp_path,
        smtp_host="smtp.example.com",
        smtp_username="test",
        smtp_password="test",
        email_from="test@example.com",
    )
    service.register("owner@example.com", PASSWORD)
    service.request_account_email("owner@example.com", purpose="reset")
    token = deliveries[-1][-1]
    original = service.create_session

    def racing_session(user_id, **kwargs):
        service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)
        return original(user_id, **kwargs)

    monkeypatch.setattr(service, "create_session", racing_session)
    with pytest.raises(ProductError, match="Credentials changed"):
        service.authenticate("owner@example.com", PASSWORD)
    monkeypatch.setattr(service, "create_session", original)
    assert service.session_user(service.authenticate("owner@example.com", NEW_PASSWORD)["session"])


def test_in_flight_api_key_creation_cannot_survive_reset(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    settings = replace(email_settings(tmp_path), require_email_verification=False)
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD})
        client.headers["X-CSRF-Token"] = client.cookies["unrender_csrf"]
        service = app.state.service
        service.request_account_email("owner@example.com", purpose="reset")
        token = deliveries[-1][-1]
        original = service.create_api_key

        def racing_key(**kwargs):
            service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)
            return original(**kwargs)

        monkeypatch.setattr(service, "create_api_key", racing_key)
        assert client.post("/api/keys", json={"name": "racing key"}).status_code == 401
        with service.database.connect() as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL").fetchone()[0]
                == 0
            )


def test_verified_account_grant_is_idempotent_and_work_survives_reset(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    service = service_for(
        tmp_path,
        smtp_host="smtp.example.com",
        smtp_username="test",
        smtp_password="test",
        email_from="test@example.com",
        initial_credits=0,
    )
    session = service.register("owner@example.com", PASSWORD)
    user_id = service.session_user(session["session"])["id"]
    service.grant_credits("owner@example.com", credits=2, reference="pilot-001")
    service.grant_credits("owner@example.com", credits=2, reference="pilot-001")
    assert service.account(user_id)["credits"] == 2
    upload = service.prepare_demo_upload(user_id)
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    assert service.process_one()
    service.approve(user_id=user_id, job_id=job["id"])
    expected, _ = service.export(user_id=user_id, job_id=job["id"], output_format="json")
    service.request_account_email("owner@example.com", purpose="reset")
    service.complete_account_email(deliveries[-1][-1], purpose="reset", password=NEW_PASSWORD)
    reopened = service_for(tmp_path)
    account = reopened.authenticate("owner@example.com", NEW_PASSWORD)
    assert reopened.session_user(account["session"])["id"] == user_id
    actual, _ = reopened.export(user_id=user_id, job_id=job["id"], output_format="json")
    assert actual == expected


def test_failed_resend_preserves_delivered_link_and_completion_consumes_siblings(
    tmp_path, monkeypatch
):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args) or True
    )
    service = service_for(
        tmp_path,
        smtp_host="smtp.example.com",
        smtp_username="test",
        smtp_password="test",
        email_from="test@example.com",
    )
    monkeypatch.setattr(service, "rate_limit", lambda *args, **kwargs: True)
    service.register("owner@example.com", PASSWORD)
    service.request_account_email("owner@example.com", purpose="reset")
    delivered = deliveries[-1][-1]
    monkeypatch.setattr("unrender.product.mail.send_account_email", lambda *args: False)
    service.request_account_email("owner@example.com", purpose="reset")
    with service.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_challenges").fetchone()[0] == 1
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args) or True
    )
    service.request_account_email("owner@example.com", purpose="reset")
    sibling = deliveries[-1][-1]
    service.complete_account_email(delivered, purpose="reset", password=NEW_PASSWORD)
    with pytest.raises(ProductError, match="expired or was already used"):
        service.complete_account_email(sibling, purpose="reset", password=PASSWORD)


def test_email_challenges_are_bounded_and_expired_tokens_are_reclaimed(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args) or True
    )
    service = service_for(
        tmp_path,
        smtp_host="smtp.example.com",
        smtp_username="test",
        smtp_password="test",
        email_from="test@example.com",
    )
    monkeypatch.setattr(service, "rate_limit", lambda *args, **kwargs: True)
    service.register("owner@example.com", PASSWORD)
    for _ in range(7):
        service.request_account_email("owner@example.com", purpose="reset")
    assert len(deliveries) == 5
    with service.database.transaction() as conn:
        conn.execute("UPDATE account_challenges SET expires_at='2000-01-01'")
    service.request_account_email("owner@example.com", purpose="reset")
    assert len(deliveries) == 6
    with service.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_challenges").fetchone()[0] == 1


def test_logout_remains_available_after_login_rate_limit(tmp_path):
    settings = settings_for(tmp_path, seed_demo_account=False, auth_rate_limit_per_minute=2)
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": "wrong password"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 429
        )
        response = client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": client.cookies["unrender_csrf"]}
        )
        assert response.status_code == 200
        assert client.get("/api/me").status_code == 401


def test_verification_hashing_releases_writer_and_fences_credential_change(tmp_path, monkeypatch):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    service = service_for(
        tmp_path,
        require_email_verification=True,
        smtp_host="smtp.example.com",
        smtp_username="user",
        smtp_password="test-only-secret",
        email_from="hello@example.com",
        initial_credits=0,
    )
    service.register("race@example.com", PASSWORD)
    service.request_account_email("race@example.com", purpose="verify")
    token = deliveries[-1][-1]
    from unrender.product import service as service_module

    original_verify = service_module.verify_password

    def verify_with_concurrent_change(password, encoded):
        # A separate writer must succeed during KDF work. Changing the generation
        # simulates a credential replacement before the verification commit.
        with service.database.connect() as conn:
            conn.execute("PRAGMA busy_timeout=50")
            conn.execute("UPDATE users SET session_generation=session_generation+1")
            conn.commit()
        return original_verify(password, encoded)

    monkeypatch.setattr(service_module, "verify_password", verify_with_concurrent_change)
    with pytest.raises(ProductError) as caught:
        service.complete_account_email(token, purpose="verify", password=PASSWORD)
    assert caught.value.code == "invalid_account_link"
    with service.database.connect() as conn:
        assert conn.execute("SELECT email_verified FROM users").fetchone()[0] == 0


@pytest.mark.parametrize("mail_path", ["register", "request-verification", "forgot-password"])
def test_slow_account_email_does_not_block_login(tmp_path, monkeypatch, mail_path):
    import threading

    entered = threading.Event()
    release = threading.Event()

    def slow_mail(*args):
        entered.set()
        assert release.wait(timeout=5)
        return True

    monkeypatch.setattr("unrender.product.mail.send_account_email", slow_mail)
    app = create_app(replace(email_settings(tmp_path), max_concurrent_auth_requests=1))
    with TestClient(app) as client:
        app.state.service.provision_user("login@example.com", PASSWORD)
        if mail_path != "register":
            app.state.service.register("mail@example.com", PASSWORD)
        outcomes = []

        def send_mail():
            outcomes.append(
                client.post(
                    f"/api/auth/{mail_path}",
                    json={
                        "email": "mail@example.com",
                        **({"password": PASSWORD} if mail_path == "register" else {}),
                    },
                ).status_code
            )

        thread = threading.Thread(target=send_mail)
        thread.start()
        try:
            assert entered.wait(timeout=5)
            blocked_mail = client.post(
                "/api/auth/forgot-password", json={"email": "another@example.com"}
            )
            assert blocked_mail.status_code == 503
            assert blocked_mail.json()["error"]["code"] == "email_capacity_reached"
            login = client.post(
                "/api/auth/login", json={"email": "login@example.com", "password": PASSWORD}
            )
            assert login.status_code == 200
        finally:
            release.set()
            thread.join(timeout=5)
        assert outcomes == [201 if mail_path == "register" else 200]


def test_cancelled_request_retains_admission_until_thread_finishes():
    import asyncio
    import threading

    from starlette.concurrency import run_in_threadpool

    from unrender.product.web import _run_admitted

    entered = threading.Event()
    release = threading.Event()

    def work():
        entered.set()
        assert release.wait(timeout=5)

    async def scenario():
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        request = asyncio.create_task(_run_admitted(run_in_threadpool(work), slots))
        assert await asyncio.to_thread(entered.wait, 5)
        request.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await request
            assert slots.locked()
        finally:
            release.set()
        await asyncio.wait_for(slots.acquire(), timeout=5)
        slots.release()

    asyncio.run(scenario())
