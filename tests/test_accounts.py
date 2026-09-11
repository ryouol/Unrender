"""Public signup, email ownership, recovery, and durable account regressions."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from test_product import STATIC_DIR, png_bytes, service_for, settings_for

from unrender.product.database import SCHEMA_VERSION, Database
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


def verify_existing_email(service, deliveries):
    service.request_account_email("owner@example.com", purpose="verify")
    service.complete_account_email(deliveries[-1][-1], purpose="verify", password=PASSWORD)


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


def production_settings(tmp_path):
    return replace(
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


def test_production_signup_requires_zero_spend_and_explicit_email_policy(tmp_path):
    settings = production_settings(tmp_path)
    settings.validate()
    with pytest.raises(ValueError, match="email and billing disabled"):
        replace(settings, require_email_verification=False).validate()
    with pytest.raises(ValueError, match="zero credits"):
        replace(settings, initial_credits=3).validate()
    with pytest.raises(ValueError, match="verified email"):
        replace(settings, smtp_password="").validate()


def password_only_production_settings(tmp_path):
    return replace(
        production_settings(tmp_path),
        require_email_verification=False,
        smtp_host="",
        smtp_username="",
        smtp_password="",
        email_from="",
    )


@pytest.mark.parametrize(
    "field",
    [
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "email_from",
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_price_id",
    ],
)
def test_password_only_production_rejects_even_partial_email_or_billing(tmp_path, field):
    settings = password_only_production_settings(tmp_path)
    settings.validate()
    with pytest.raises(ValueError, match="email and billing disabled"):
        replace(settings, **{field: "configured"}).validate()
    with pytest.raises(ValueError, match="zero credits"):
        replace(settings, initial_credits=1).validate()


def test_password_signup_production_session_restart_and_zero_spend(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Password signup or zero-credit uploads must not send email or infer")

    monkeypatch.setattr("unrender.product.mail.send_account_email", forbidden)
    monkeypatch.setattr("unrender.product.extractors.ModalExtractor.extract", forbidden)
    settings = password_only_production_settings(tmp_path)
    with TestClient(create_app(settings), base_url=settings.base_url) as client:
        response = client.post(
            "/api/auth/register", json={"email": "Owner@Example.com", "password": PASSWORD}
        )
        assert response.status_code == 201
        assert response.json() == {"ok": True}
        cookie = response.headers.get_list("set-cookie")[0]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        account = client.get("/api/me").json()
        assert account["email"] == "owner@example.com"
        assert account["credits"] == 0 and account["email_verified"] is False
        assert account["billing_configured"] is False
        csrf = {"X-CSRF-Token": client.cookies["unrender_csrf"]}
        blocked = client.post(
            "/api/uploads",
            headers=csrf,
            files={"file": ("chart.png", png_bytes(), "image/png")},
        )
        assert blocked.status_code == 402
        assert client.post("/api/auth/logout", headers=csrf).status_code == 200
        assert client.get("/api/me").status_code == 401
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )
        session = client.cookies["unrender_session"]
        with client.app.state.service.database.connect() as conn:
            for table in (
                "account_challenges",
                "credit_ledger",
                "uploads",
                "jobs",
                "provider_attempts",
            ):
                assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            row = conn.execute("SELECT account_active,email_verified FROM users").fetchone()
            assert tuple(row) == (1, 0)
    with TestClient(create_app(settings), base_url=settings.base_url) as reopened:
        reopened.cookies.set("unrender_session", session)
        assert reopened.get("/api/me").json()["id"] == account["id"]
        assert (
            reopened.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )


@pytest.mark.parametrize("legacy_operator_account", [False, True])
def test_later_email_enablement_cannot_recover_unverified_active_workspace(
    tmp_path, monkeypatch, legacy_operator_account
):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    service = service_for(tmp_path, initial_credits=0, seed_demo_account=False)
    if legacy_operator_account:
        user_id = service.provision_user("owner@example.com", PASSWORD)
        session = service.create_session(user_id)
        with service.database.transaction() as conn:
            # Schema 9 operator provisioning set this flag without sending email.
            conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
            conn.execute("ALTER TABLE users DROP COLUMN account_active")
            conn.execute("ALTER TABLE account_challenges DROP COLUMN email_proof")
            conn.execute("UPDATE schema_meta SET version=9")
    else:
        session = service.register("owner@example.com", PASSWORD)
        user_id = service.session_user(session["session"])["id"]
    emailed = service_for(
        tmp_path,
        initial_credits=0,
        seed_demo_account=False,
        require_email_verification=True,
        smtp_host="smtp.example.com",
        smtp_username="test",
        smtp_password="test",
        email_from="test@example.com",
    )
    assert emailed.authenticate("owner@example.com", PASSWORD)["session"]
    assert emailed.session_user(session["session"])["id"] == user_id
    assert emailed.account(user_id)["email_verified"] is False
    emailed.request_account_email("owner@example.com", purpose="reset")
    assert deliveries == []
    emailed.request_account_email("owner@example.com", purpose="verify")
    token = deliveries[-1][-1]
    with pytest.raises(ProductError, match="password you chose"):
        emailed.complete_account_email(token, purpose="verify", password=NEW_PASSWORD)
    assert emailed.account(user_id)["email_verified"] is False
    emailed.complete_account_email(token, purpose="verify", password=PASSWORD)
    assert emailed.account(user_id)["email_verified"] is True
    # A new minute avoids coupling the ownership test to the recipient rate limit.
    monkeypatch.setattr(emailed, "rate_limit", lambda *args, **kwargs: True)
    emailed.request_account_email("owner@example.com", purpose="reset")
    emailed.complete_account_email(deliveries[-1][-1], purpose="reset", password=NEW_PASSWORD)
    assert emailed.session_user(session["session"]) is None
    assert emailed.authenticate("owner@example.com", NEW_PASSWORD)["session"]


@pytest.mark.parametrize("activate_during_hash", [False, True])
def test_email_reset_rechecks_activation_before_commit(tmp_path, monkeypatch, activate_during_hash):
    from unrender.product import service as service_module

    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    settings = email_settings(tmp_path)
    service = service_for(
        tmp_path,
        **{
            name: getattr(settings, name)
            for name in (
                "require_email_verification",
                "smtp_host",
                "smtp_username",
                "smtp_password",
                "email_from",
            )
        },
    )
    service.register("owner@example.com", PASSWORD)
    service.request_account_email("owner@example.com", purpose="reset")
    token = deliveries[-1][-1]
    original_hash = service_module.hash_password

    def activate():
        with service.database.transaction(immediate=True) as conn:
            conn.execute("UPDATE users SET account_active=1")

    def racing_hash(password):
        result = original_hash(password)
        activate()
        return result

    if activate_during_hash:
        monkeypatch.setattr(service_module, "hash_password", racing_hash)
    else:
        activate()
        monkeypatch.setattr(service_module, "hash_password", lambda _: pytest.fail("reached KDF"))
    with pytest.raises(ProductError) as caught:
        service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)
    assert caught.value.code == "invalid_account_link"
    assert service.authenticate("owner@example.com", PASSWORD)["session"]


@pytest.mark.parametrize("verified", [False, True])
def test_operator_recovery_preserves_mailbox_verification(tmp_path, verified):
    service = service_for(tmp_path)
    session = service.register("owner@example.com", PASSWORD)
    user_id = service.session_user(session["session"])["id"]
    with service.database.transaction() as conn:
        conn.execute("UPDATE users SET email_verified=? WHERE id=?", (verified, user_id))
    link = service.operator_account_link("owner@example.com")
    assert "mode=invite" not in link
    token = parse_qs(urlsplit(link).fragment)["token"][0]
    service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)
    assert service.account(user_id)["email_verified"] is verified
    assert service.session_user(session["session"]) is None
    assert service.authenticate("owner@example.com", NEW_PASSWORD)["session"]


def test_password_only_workspace_grant_persistence_and_tenant_isolation(tmp_path):
    service = service_for(tmp_path, initial_credits=0, seed_demo_account=False)
    first = service.register("owner@example.com", PASSWORD)
    owner = service.session_user(first["session"])["id"]
    other = service.session_user(service.register("other@example.com", PASSWORD)["session"])["id"]
    service.grant_credits("owner@example.com", credits=2, reference="approved-budget")
    service.grant_credits("owner@example.com", credits=2, reference="approved-budget")
    assert service.account(owner)["credits"] == 2
    upload = service.prepare_upload(
        user_id=owner,
        filename="chart.webp",
        content=(STATIC_DIR / "demo" / "budget-quarter.webp").read_bytes(),
    )
    job = service.create_job(user_id=owner, upload_id=upload["id"], page_index=0, crop=None)
    assert service.process_one()
    service.approve(user_id=owner, job_id=job["id"])
    expected = service.export(user_id=owner, job_id=job["id"], output_format="json")
    service.logout(first["session"])
    reopened = service_for(tmp_path, initial_credits=0, seed_demo_account=False)
    assert reopened.session_user(first["session"]) is None
    assert (
        reopened.session_user(reopened.authenticate("owner@example.com", PASSWORD)["session"])["id"]
        == owner
    )
    assert reopened.export(user_id=owner, job_id=job["id"], output_format="json") == expected
    assert reopened.account(owner)["email_verified"] is False
    assert reopened.list_jobs(other) == []
    for operation in (
        lambda: reopened.get_job(user_id=other, job_id=job["id"]),
        lambda: reopened.job_source(user_id=other, job_id=job["id"]),
        lambda: reopened.export(user_id=other, job_id=job["id"], output_format="json"),
    ):
        with pytest.raises(ProductError) as caught:
            operation()
        assert caught.value.status_code == 404


def test_v8_migration_preserves_existing_accounts(tmp_path):
    service = service_for(tmp_path)
    account = service.register("old@example.com", PASSWORD)
    user_id = service.session_user(account["session"])["id"]
    with service.database.transaction() as conn:
        conn.execute("DROP TABLE account_challenges")
        conn.execute('ALTER TABLE users DROP COLUMN "email_verified"')
        conn.execute('ALTER TABLE users DROP COLUMN "account_active"')
        conn.execute("UPDATE schema_meta SET version=8")
    service.database.initialize()
    assert service.session_user(account["session"])["id"] == user_id
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT account_active,email_verified FROM users").fetchone()[:] == (
            1,
            0,
        )


@pytest.mark.parametrize("crash_after", range(5))
def test_v9_activation_migration_is_atomic_and_preserves_access(tmp_path, crash_after):
    service = service_for(tmp_path, initial_credits=0)
    account = service.register("legacy@example.com", PASSWORD)
    user_id = service.session_user(account["session"])["id"]
    invitation = service.invite_user("pending@example.com")
    token = parse_qs(urlsplit(invitation).fragment)["token"][0]
    with service.database.transaction() as conn:
        conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
        conn.execute("ALTER TABLE users DROP COLUMN account_active")
        conn.execute("ALTER TABLE account_challenges DROP COLUMN email_proof")
        conn.execute("UPDATE schema_meta SET version=9")
    mutations = 0

    def fault():
        nonlocal mutations
        mutations += 1
        if mutations == crash_after:
            raise RuntimeError("injected activation migration crash")

    service.database._migration_fault_hook = fault
    if crash_after:
        with pytest.raises(RuntimeError, match="activation migration crash"):
            service.database.initialize()
        with service.database.connect() as conn:
            assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 9
            assert "account_active" not in Database._columns(conn, "users")
            assert "email_proof" not in Database._columns(conn, "account_challenges")
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM account_challenges").fetchone()[0] == 1
    service.database._migration_fault_hook = None
    service.database.initialize()
    service.database.initialize()
    assert service.session_user(account["session"])["id"] == user_id
    assert service.authenticate("legacy@example.com", PASSWORD)["session"]
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_key_check").fetchone() is None
        states = {
            row["email"]: tuple(row)[1:]
            for row in conn.execute("SELECT email,account_active,email_verified FROM users")
        }
        assert states == {"legacy@example.com": (1, 0), "pending@example.com": (0, 0)}
        assert conn.execute("SELECT email_proof FROM account_challenges").fetchone()[0] == 0
        pending_id = conn.execute(
            "SELECT id FROM users WHERE email='pending@example.com'"
        ).fetchone()[0]
    with pytest.raises(ProductError, match="Complete account setup"):
        service.create_session(pending_id)
    with pytest.raises(ProductError, match="Active account not found"):
        service.grant_credits("pending@example.com", credits=1, reference="premature-grant")
    service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)
    assert service.authenticate("pending@example.com", NEW_PASSWORD)["session"]
    assert service.account(pending_id)["email_verified"] is False


def test_new_signup_never_inherits_v9_verified_email_default(tmp_path):
    from unrender.product.database import SCHEMA

    settings = settings_for(tmp_path, initial_credits=0)
    database = Database(settings.database_path)
    settings.data_dir.mkdir(parents=True)
    legacy_schema = (
        SCHEMA.replace(
            "    account_active INTEGER NOT NULL DEFAULT 0 CHECK (account_active IN (0,1)),\n", ""
        )
        .replace("    email_proof INTEGER NOT NULL DEFAULT 0 CHECK (email_proof IN (0,1)),\n", "")
        .replace(
            "email_verified INTEGER NOT NULL DEFAULT 0", "email_verified INTEGER NOT NULL DEFAULT 1"
        )
    )
    with database.connect() as conn:
        conn.executescript(legacy_schema)
        conn.execute("INSERT INTO schema_meta VALUES (9)")
    service = service_for(tmp_path, initial_credits=0)
    registered = service.register("new@example.com", PASSWORD)
    account = service.session_user(registered["session"])
    assert account["email_verified"] == 0 and account["account_active"] == 1


@pytest.mark.parametrize("legacy_verification", [False, True])
def test_pending_email_account_can_complete_its_proven_challenge(
    tmp_path, monkeypatch, legacy_verification
):
    deliveries = []
    monkeypatch.setattr(
        "unrender.product.mail.send_account_email", lambda *args: deliveries.append(args)
    )
    with TestClient(create_app(email_settings(tmp_path))) as client:
        client.post("/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD})
        service = client.app.state.service
        purpose = "verify" if legacy_verification else "reset"
        if legacy_verification:
            with service.database.transaction() as conn:
                conn.execute("ALTER TABLE users DROP COLUMN account_active")
                conn.execute("ALTER TABLE account_challenges DROP COLUMN email_proof")
                conn.execute("UPDATE schema_meta SET version=9")
            service.database.initialize()
        else:
            service.request_account_email("owner@example.com", purpose="reset")
        service.complete_account_email(deliveries[-1][-1], purpose=purpose, password=PASSWORD)
        account = service.session_user(
            service.authenticate("owner@example.com", PASSWORD)["session"]
        )
        assert account["email_verified"] == 1 and account["account_active"] == 1


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
    verify_existing_email(service, deliveries)
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
        verify_existing_email(service, deliveries)
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
    verify_existing_email(service, deliveries)
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
    verify_existing_email(service, deliveries)
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
    verify_existing_email(service, deliveries)
    deliveries.clear()
    for _ in range(7):
        service.request_account_email("owner@example.com", purpose="reset")
    assert len(deliveries) == 5
    with service.database.transaction() as conn:
        conn.execute("UPDATE account_challenges SET expires_at='2000-01-01'")
    service.request_account_email("owner@example.com", purpose="reset")
    assert len(deliveries) == 6
    with service.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_challenges").fetchone()[0] == 1


def test_logout_remains_available_after_login_rate_limit(tmp_path, fixed_rate_window):
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


@pytest.mark.parametrize("known", [True, False])
def test_account_attempt_limit_normalizes_identity_before_password_work(
    tmp_path, monkeypatch, known, fixed_rate_window
):
    import unrender.product.service as service_module

    app = create_app(settings_for(tmp_path, seed_demo_account=False, auth_rate_limit_per_minute=2))
    with TestClient(app) as client:
        if known:
            app.state.service.provision_user("owner@example.com", PASSWORD)
        app.state.service.provision_user("other@example.com", PASSWORD)
        original = service_module.verify_password
        checked = []

        def verify(password, encoded):
            checked.append(True)
            return original(password, encoded)

        monkeypatch.setattr(service_module, "verify_password", verify)
        for email in ("Owner@Example.com", " owner@example.com "):
            assert (
                client.post(
                    "/api/auth/login", json={"email": email, "password": "wrong password"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 429
        )
        assert len(checked) == 2
        assert (
            client.post(
                "/api/auth/login", json={"email": "other@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )


def test_global_auth_capacity_applies_with_valid_session_and_rotated_accounts(
    tmp_path, fixed_rate_window
):
    app = create_app(
        settings_for(tmp_path, seed_demo_account=False, global_auth_rate_limit_per_minute=2)
    )
    with TestClient(app) as client:
        user_id = app.state.service.provision_user("owner@example.com", PASSWORD)
        session = app.state.service.create_session(user_id)
        client.cookies.set("unrender_session", session["session"])
        for email in ("unknown1@example.com", "unknown2@example.com"):
            assert (
                client.post(
                    "/api/auth/login", json={"email": email, "password": PASSWORD}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 429
        )
        assert (
            client.post("/api/auth/logout", headers={"X-CSRF-Token": session["csrf"]}).status_code
            == 200
        )


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


@pytest.mark.parametrize("state", ["unknown", "expired", "consumed"])
def test_invalid_reset_links_reject_before_password_hashing(tmp_path, monkeypatch, state):
    service = service_for(tmp_path)
    service.provision_user("owner@example.com", PASSWORD)
    link = service.operator_account_link("owner@example.com")
    token = parse_qs(urlsplit(link).fragment)["token"][0]
    if state == "unknown":
        token = "unknown-reset-token"
    elif state == "expired":
        with service.database.transaction() as conn:
            conn.execute("UPDATE account_challenges SET expires_at='2000-01-01'")
    else:
        service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)

    def forbidden_hash(_):
        pytest.fail("An invalid reset link reached password hashing")

    monkeypatch.setattr("unrender.product.service.hash_password", forbidden_hash)
    with pytest.raises(ProductError) as caught:
        service.complete_account_email(token, purpose="reset", password=PASSWORD)
    assert caught.value.code == "invalid_account_link"


@pytest.mark.parametrize("change", ["expire", "reissue", "consume"])
def test_reset_revalidates_challenge_after_password_work(tmp_path, monkeypatch, change):
    from unrender.product import service as service_module

    service = service_for(tmp_path)
    service.provision_user("owner@example.com", PASSWORD)
    link = service.operator_account_link("owner@example.com")
    token = parse_qs(urlsplit(link).fragment)["token"][0]
    with pytest.raises(ProductError) as invalid_password:
        service.complete_account_email(token, purpose="reset", password="short")
    assert invalid_password.value.code == "invalid_password"
    original_hash = service_module.hash_password
    winner_password = "the concurrent winning password"

    def hash_with_concurrent_change(password):
        result = original_hash(password)
        if change == "expire":
            with service.database.connect() as conn:
                conn.execute("PRAGMA busy_timeout=50")
                conn.execute("UPDATE account_challenges SET expires_at='2000-01-01'")
                conn.commit()
        elif change == "reissue":
            service.operator_account_link("owner@example.com")
        else:
            with monkeypatch.context() as concurrent:
                concurrent.setattr(service_module, "hash_password", original_hash)
                service.complete_account_email(token, purpose="reset", password=winner_password)
        return result

    monkeypatch.setattr(service_module, "hash_password", hash_with_concurrent_change)
    with pytest.raises(ProductError) as caught:
        service.complete_account_email(token, purpose="reset", password=NEW_PASSWORD)
    assert caught.value.code == "invalid_account_link"
    current_password = winner_password if change == "consume" else PASSWORD
    assert service.authenticate("owner@example.com", current_password)["session"]


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
