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


def test_library_page_filters_across_pages_without_reading_results(tmp_path):
    from test_product import _paid_job, customer_id, service_for

    from unrender.product.library import ChartLibrary

    service = service_for(tmp_path, initial_credits=50)
    owner = customer_id(service)
    other = customer_id(service, "other@example.test")
    source = _paid_job(service, owner, color="red")
    library = ChartLibrary(service)
    # A schema-valid fixture expanded without creating 30 image files or dispatches.
    with service.database.transaction(immediate=True) as conn:
        row = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (source["id"],)).fetchone())
        for n in range(30):
            row.update(id=f"fixture-{n:02d}", display_name=f"Chart {n:02d}", upload_id=None)
            conn.execute(
                "INSERT INTO jobs ("
                + ",".join(row)
                + ") VALUES ("
                + ",".join("?" for _ in row)
                + ")",
                tuple(row.values()),
            )
    with service.database.transaction(immediate=True) as conn:
        conn.execute("UPDATE jobs SET display_name=? WHERE id=?", ("ÉTÉ", source["id"]))
    assert library.page(owner, search="été")["total"] == 1
    first = library.page(owner)
    second = library.page(owner, page=1)
    assert len(first["items"]) == 24 and len(second["items"]) == 7
    assert first["total"] == 31 and first["counts"]["all"] == 31
    assert not set(j["id"] for j in first["items"]) & set(j["id"] for j in second["items"])
    assert all("result" not in job for job in first["items"])
    assert library.page(owner, search="Chart 00")["total"] == 1
    assert library.page(owner, search="%")["total"] == 0
    assert library.page(owner, status="approved")["total"] == 0
    assert library.page(other)["total"] == 0


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


def test_thumbnail_cache_does_not_bypass_account_or_chart_access(tmp_path, monkeypatch):
    import pytest
    from test_product import _paid_job, customer_id, service_for

    from unrender.product.service import ProductError

    service = service_for(tmp_path)
    user = customer_id(service)
    other = customer_id(service, "other@example.test")
    job = _paid_job(service, user, color="blue")
    calls = 0
    render = service.storage.page_png

    def counted(**kwargs):
        nonlocal calls
        calls += 1
        return render(**kwargs)

    monkeypatch.setattr(service.storage, "page_png", counted)
    first = service.job_source(user_id=user, job_id=job["id"], thumbnail=True)
    assert service.job_source(user_id=user, job_id=job["id"], thumbnail=True) == first
    assert calls == 1
    with pytest.raises(ProductError, match="not found"):
        service.job_source(user_id=other, job_id=job["id"], thumbnail=True)
    with service.database.transaction(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status='failed' WHERE id=?", (job["id"],))
    service.delete_job(user_id=user, job_id=job["id"])
    with pytest.raises(ProductError, match="not found"):
        service.job_source(user_id=user, job_id=job["id"], thumbnail=True)


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


def test_populated_schema15_migration_preserves_credentials_and_jobs(tmp_path):
    from test_product import _paid_job, customer_id, service_for

    service = service_for(tmp_path)
    user = customer_id(service)
    job = _paid_job(service, user, color="green")
    key = service.create_api_key(user_id=user, name="Existing integration")
    with service.database.transaction(immediate=True) as conn:
        conn.execute("ALTER TABLE api_keys DROP COLUMN scope")
        conn.execute("ALTER TABLE api_keys DROP COLUMN expires_at")
        conn.execute("DROP TABLE dispatch_budget")
        conn.execute("UPDATE schema_meta SET version=15")
    service.database.initialize()
    service.database.initialize()  # Restart after migration is idempotent.
    authenticated = service.api_key_user(key["key"])
    assert authenticated["id"] == user
    assert authenticated["api_key_scope"] == "extract"
    assert service.get_job(user_id=user, job_id=job["id"])["status"] == "queued"
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 16
        assert conn.execute("SELECT expires_at FROM api_keys").fetchone()[0] is None
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
