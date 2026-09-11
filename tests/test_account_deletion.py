"""Destructive account operations preserve tenant isolation and in-flight work."""

from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_library import chart_for
from test_product import csrf_headers, customer_id, png_bytes, service_for, settings_for

from unrender.product.extractors import ExtractionError
from unrender.product.library import ChartLibrary
from unrender.product.lifecycle import AccountLifecycle
from unrender.product.service import ProductError, timestamp
from unrender.product.web import create_app

PASSWORD = "a long original password"


def authenticated_owner(service):
    session = service.register("owner@example.com", PASSWORD)
    owner = service.session_user(session["session"])["id"]
    service.reauthenticate_password(
        user_id=owner, session_token=session["session"], password=PASSWORD
    )
    return owner, session


def test_delete_account_removes_owned_records_and_revokes_every_credential(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, session = authenticated_owner(service)
    other = customer_id(service, "other@example.com")
    other_chart = chart_for(service, other)
    key = service.create_api_key(user_id=owner, name="Delete this key")["key"]
    second_session = service.authenticate("owner@example.com", PASSWORD)
    project = ChartLibrary(service).create_project(owner, "Delete this project")
    queued = chart_for(service, owner)
    ChartLibrary(service).update_chart(owner, queued["id"], {"project_id": project["id"]})
    service.prepare_upload(user_id=owner, filename="unused.png", content=png_bytes())
    with service.database.transaction() as conn:
        conn.execute(
            "INSERT INTO google_identities(subject,user_id,created_at) VALUES (?,?,?)",
            ("verified-test-subject", owner, timestamp()),
        )
        paths = [
            Path(row[0])
            for row in conn.execute(
                "SELECT source_path FROM jobs WHERE user_id=? UNION ALL "
                "SELECT storage_path FROM uploads WHERE user_id=?",
                (owner, owner),
            )
        ]
    result = AccountLifecycle(service).delete_account(owner, session["session"])
    assert result == {"status": "deleted", "charts_deleted": 1, "projects_deleted": 1}
    assert service.session_user(session["session"]) is None
    assert service.session_user(second_session["session"]) is None
    assert service.api_key_user(key) is None
    assert all(not path.exists() for path in paths)
    with service.database.connect() as conn:
        assert conn.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone() is None
        assert service._database_row_count(conn, owner) == 0
        assert (
            conn.execute("SELECT 1 FROM google_identities WHERE user_id=?", (owner,)).fetchone()
            is None
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert service.account(other)["credits"] == 2
    assert service.job_source(user_id=other, job_id=other_chart["id"])


def test_account_delete_waits_for_provider_settlement(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, session = authenticated_owner(service)
    job = chart_for(service, owner)
    entered, release = Event(), Event()

    def blocked_provider(image):
        entered.set()
        assert release.wait(5)
        raise ExtractionError("provider_unavailable", "simulated provider failure")

    service.extractor = SimpleNamespace(extract=blocked_provider)
    worker = Thread(target=service.process_one)
    worker.start()
    try:
        assert entered.wait(3)
        with pytest.raises(ProductError) as error:
            AccountLifecycle(service).delete_account(owner, session["session"])
        assert error.value.code == "account_busy"
        assert service.session_user(session["session"]) is not None
        assert service.job_source(user_id=owner, job_id=job["id"])
        service.cancel(user_id=owner, job_id=job["id"])
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert service.get_job(user_id=owner, job_id=job["id"])["status"] == "cancelled"
    assert service.account(owner)["credits"] == 2
    assert (
        AccountLifecycle(service).delete_account(owner, session["session"])["status"] == "deleted"
    )
    assert not service.process_one()


def test_account_delete_waits_for_live_staging_then_removes_expired_source(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, session = authenticated_owner(service)
    path = service.storage.root / "staging" / "expired-source"
    path.parent.mkdir(parents=True, exist_ok=True)
    reservation = service._reserve_storage_bytes(
        user_id=owner, byte_count=4, kind="staging", storage_path=path
    )
    path.write_bytes(b"test")
    with pytest.raises(ProductError) as error:
        AccountLifecycle(service).delete_account(owner, session["session"])
    assert error.value.code == "account_busy"
    with service.database.transaction() as conn:
        conn.execute("UPDATE storage_reservations SET expires_at='2000-01-01T00:00:00Z'")
    AccountLifecycle(service).delete_account(owner, session["session"])
    assert not path.exists()
    with pytest.raises(ProductError, match="reservation expired"):
        service._resize_storage_reservation(
            user_id=owner, reservation=reservation, byte_count=4, kind="staging", storage_path=path
        )


def test_failed_account_file_cleanup_cannot_touch_recreated_account(tmp_path, monkeypatch):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, session = authenticated_owner(service)
    job = chart_for(service, owner)
    old_source = Path(service._job_row(user_id=owner, job_id=job["id"])["source_path"])
    delete = service.storage.delete

    def fail_delete(path):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(service.storage, "delete", fail_delete)
    assert (
        AccountLifecycle(service).delete_account(owner, session["session"])["status"]
        == "deletion_queued"
    )
    assert old_source.exists()
    assert service.session_user(session["session"]) is None
    new_owner, new_session = authenticated_owner(service)
    new_chart = chart_for(service, new_owner)
    assert new_owner != owner
    monkeypatch.setattr(service.storage, "delete", delete)
    service.drain_deletion_queue()
    assert not old_source.exists()
    assert service.session_user(new_session["session"]) is not None
    assert service.job_source(user_id=new_owner, job_id=new_chart["id"])


def test_account_delete_rolls_back_credential_revocation_if_queue_cannot_commit(
    tmp_path, monkeypatch
):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, session = authenticated_owner(service)
    job = chart_for(service, owner)
    key = service.create_api_key(user_id=owner, name="Keep on rollback")["key"]

    def fail_queue(*args, **kwargs):
        raise RuntimeError("simulated transaction failure")

    monkeypatch.setattr(service, "_queue_deletion", fail_queue)
    with pytest.raises(RuntimeError):
        AccountLifecycle(service).delete_account(owner, session["session"])
    assert service.session_user(session["session"]) is not None
    assert service.api_key_user(key) is not None
    assert service.get_job(user_id=owner, job_id=job["id"])["status"] == "queued"
    assert service.account(owner)["credits"] == 2


def test_account_delete_http_requires_csrf_fresh_self_auth_and_explicit_confirmation(tmp_path):
    app = create_app(settings_for(tmp_path, seed_demo_account=False))
    with TestClient(app) as client:
        client.post("/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD})
        headers = csrf_headers(client)
        url = "/api/auth/delete-account"
        assert client.post(url, json={"confirmation": "DELETE"}).status_code == 403
        assert client.post(url, headers=headers, json={"confirmation": "DELETE"}).status_code == 403
        assert client.post(url, headers=headers, json={"confirmation": "yes"}).status_code == 422
        owner = client.get("/api/me").json()["id"]
        session = client.cookies["unrender_session"]
        other = customer_id(app.state.service, "other@example.com")
        with pytest.raises(ProductError):
            AccountLifecycle(app.state.service).delete_account(other, session)
        app.state.service.reauthenticate_password(
            user_id=owner, session_token=session, password=PASSWORD
        )
        assert client.get("/api/account/deletion-summary").json()["charts"] == 0
        response = client.post(url, headers=headers, json={"confirmation": "DELETE"})
        assert response.status_code == 200
        assert "unrender_session" not in client.cookies
        assert "unrender_csrf" not in client.cookies
        assert client.get("/api/me").status_code == 401
        assert app.state.service.account(other)["credits"] == 3


def test_committed_account_deletion_reports_pending_cleanup_when_operations_lock_is_busy(
    tmp_path,
    monkeypatch,
):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, session = authenticated_owner(service)
    job = chart_for(service, owner)
    path = Path(service._job_row(user_id=owner, job_id=job["id"])["source_path"])
    drain = service.drain_deletion_queue

    def locked(**kwargs):
        raise TimeoutError("operations lock unavailable")

    monkeypatch.setattr(service, "drain_deletion_queue", locked)
    result = AccountLifecycle(service).delete_account(owner, session["session"])
    assert result["status"] == "deletion_queued"
    assert service.session_user(session["session"]) is None
    assert path.exists()
    monkeypatch.setattr(service, "drain_deletion_queue", drain)
    service.drain_deletion_queue()
    assert not path.exists()
