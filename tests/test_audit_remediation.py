"""Integration regressions for the September platform audit."""

from fastapi.testclient import TestClient

from test_product import settings_for

from unrender.product.web import create_app


def test_readiness_does_not_spend_public_admission_capacity(tmp_path):
    settings = settings_for(tmp_path, global_rate_limit_per_minute=3)
    with TestClient(create_app(settings)) as client:
        assert [client.get("/").status_code for _ in range(3)] == [200] * 3
        assert client.get("/").status_code == 429
        assert client.get("/health/ready").status_code == 200
        assert client.get("/health/live").status_code == 200
        assert client.get("/").status_code == 429


def test_dispatch_budget_survives_chart_deletion_and_refunds_denied_job(tmp_path):
    from test_product import _paid_job, customer_id, service_for

    from unrender.product.dispatch_budget import status
    from unrender.product.service import timestamp

    service = service_for(tmp_path, max_provider_dispatches_per_day=1)
    user = customer_id(service)
    first = _paid_job(service, user, color="purple")
    claim = service.claim_next_job("first")
    assert service._begin_provider_dispatch(claim)
    assert not service._begin_provider_dispatch(claim)
    with service.database.connect() as conn:
        assert conn.execute("SELECT used FROM dispatch_budget").fetchone()[0] == 1
    assert service._finish_failed_claim(claim, "provider_failed", "charged failure")
    service.delete_job(user_id=user, job_id=first["id"])
    second = _paid_job(service, user, color="blue")
    claim = service.claim_next_job("second")
    assert not service._begin_provider_dispatch(claim)
    assert (
        service.get_job(user_id=user, job_id=second["id"])["error"]["code"]
        == "provider_daily_limit"
    )
    assert service.account(user)["credits"] == 2
    with service.database.connect() as conn:
        assert status(conn, timestamp()[:10], 1)["remaining_dispatches"] == 0


def test_dispatch_allowance_is_atomic_and_handles_clock_and_pause(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from test_product import service_for

    from unrender.product.dispatch_budget import reserve_dispatch

    service = service_for(tmp_path)

    def reserve(_):
        with service.database.transaction(immediate=True) as conn:
            return reserve_dispatch(conn, "2026-09-23", 3)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 3
    with service.database.transaction(immediate=True) as conn:
        assert not reserve_dispatch(conn, "2026-09-22", 3)
        conn.execute("UPDATE dispatch_budget SET paused=1")
        assert not reserve_dispatch(conn, "2026-09-24", 3)
        conn.execute("UPDATE dispatch_budget SET paused=0")
        assert reserve_dispatch(conn, "2026-09-24", 3)


def test_read_only_and_expired_api_keys_cannot_dispatch(tmp_path):
    from test_product import customer_id, service_for

    from unrender.product.web import create_app

    service = service_for(tmp_path)
    user = customer_id(service)
    key = service.create_api_key(user_id=user, name="Read only", scope="read", expires_in_days=1)
    with TestClient(create_app(service.settings)) as client:
        response = client.post(
            "/api/v1/extractions",
            headers={"Authorization": "Bearer " + key["key"]},
            files={"file": ("chart.png", b"png", "image/png")},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "api_key_scope"
    assert service.api_key_user(key["key"]) is not None
    with service.database.transaction(immediate=True) as conn:
        conn.execute("UPDATE api_keys SET expires_at='2000-01-01T00:00:00Z'")
    assert service.api_key_user(key["key"]) is None


def test_unverified_password_trial_does_not_mint_dispatch_credits(tmp_path):
    from test_product import service_for

    service = service_for(tmp_path, require_verified_trial=True, require_email_verification=False)
    service.register("unverified@example.test", "Disposable long password")
    with service.database.connect() as conn:
        row = conn.execute(
            "SELECT credit_balance FROM users WHERE email='unverified@example.test'"
        ).fetchone()
    assert row["credit_balance"] == 0


def test_expired_keys_allow_replacement_at_active_and_retained_limits(tmp_path):
    from test_product import customer_id, service_for

    service = service_for(tmp_path, max_active_api_keys_per_user=1, max_api_key_records_per_user=1)
    user = customer_id(service)
    old = service.create_api_key(user_id=user, name="Old")
    with service.database.transaction(immediate=True) as conn:
        conn.execute("UPDATE api_keys SET expires_at='2000-01-01T00:00:00Z'")
    new = service.create_api_key(user_id=user, name="Replacement")
    assert service.api_key_user(old["key"]) is None
    assert service.api_key_user(new["key"]) is not None
