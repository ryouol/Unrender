"""Private projects preserve source provenance and enforce ownership and capacity."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_product import csrf_headers, customer_id, png_bytes, service_for, settings_for

from unrender.product.database import SCHEMA_VERSION
from unrender.product.library import MAX_PROJECTS, ChartLibrary
from unrender.product.service import ProductError, timestamp
from unrender.product.web import create_app


def chart_for(service, user_id, *, upload=None):
    upload = upload or service.prepare_upload(
        user_id=user_id, filename="original.png", content=png_bytes()
    )
    return service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)


def test_project_metadata_is_private_and_preserves_source(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, other = customer_id(service), customer_id(service, "other@example.com")
    library = ChartLibrary(service)
    project = library.create_project(owner, "Research")
    foreign = library.create_project(other, "Private")
    job = chart_for(service, owner)
    changed = library.update_chart(
        owner, job["id"], {"display_name": "Revenue, 2026", "project_id": project["id"]}
    )
    assert changed["display_name"] == "Revenue, 2026"
    assert changed["source_name"] == "original.png"
    assert changed["status"] == job["status"]
    assert library.get_project(owner, project["id"])["chart_count"] == 1
    assert library.get_project(owner, project["id"])["active_count"] == 1
    assert library.rename_project(owner, project["id"], "Annual review")["name"] == "Annual review"
    for operation in (
        lambda: library.get_project(other, project["id"]),
        lambda: library.rename_project(other, project["id"], "Stolen"),
        lambda: library.update_chart(other, job["id"], {"display_name": "Stolen"}),
        lambda: library.update_chart(owner, job["id"], {"project_id": foreign["id"]}),
    ):
        with pytest.raises(ProductError) as error:
            operation()
        assert error.value.status_code == 404
    assert [p["name"] for p in library.list_projects(other)["items"]] == ["Private"]
    assert library.update_chart(owner, job["id"], {"project_id": None})["project_id"] is None
    assert library.get_project(owner, project["id"])["chart_count"] == 0
    assert service.account(owner)["credits"] == 2


def test_project_capacity_and_names_are_bounded(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner = customer_id(service)
    library = ChartLibrary(service)
    for name in (" ", "x" * 81, "a\nb", "\u202efake"):
        with pytest.raises(ProductError) as error:
            library.create_project(owner, name)
        assert error.value.status_code == 422
    with service.database.transaction(immediate=True) as conn:
        conn.executemany(
            "INSERT INTO projects(id,user_id,name,created_at,updated_at) VALUES (?,?,?,?,?)",
            [(str(i), owner, str(i), timestamp(), timestamp()) for i in range(MAX_PROJECTS)],
        )
    assert len(library.list_projects(owner)["items"]) == MAX_PROJECTS
    with pytest.raises(ProductError) as error:
        library.create_project(owner, "Over capacity")
    assert error.value.code == "project_limit"


def test_library_routes_require_session_csrf_and_reject_unknown_fields(tmp_path):
    app = create_app(settings_for(tmp_path, seed_demo_account=False))
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401
        client.post(
            "/api/auth/register",
            json={"email": "owner@example.com", "password": "a long original password"},
        )
        assert client.post("/api/projects", json={"name": "Research"}).status_code == 403
        headers = csrf_headers(client)
        project = client.post("/api/projects", headers=headers, json={"name": "Research"})
        assert project.status_code == 201
        project_id = project.json()["id"]
        assert (
            client.patch(
                f"/api/projects/{project_id}", headers=headers, json={"name": "Renamed"}
            ).json()["name"]
            == "Renamed"
        )
        assert (
            client.post(
                "/api/projects", headers=headers, json={"name": "X", "user_id": "other"}
            ).status_code
            == 422
        )
        owner = client.get("/api/me").json()["id"]
        job = chart_for(app.state.service, owner)
        assert (
            client.patch(
                f"/api/jobs/{job['id']}", headers=headers, json={"display_name": None}
            ).status_code
            == 422
        )
        renamed = client.patch(
            f"/api/jobs/{job['id']}",
            headers=headers,
            json={"display_name": "A chart", "project_id": project_id},
        )
        assert renamed.status_code == 200
        assert client.get("/api/jobs").json()["items"][0]["display_name"] == "A chart"


@pytest.mark.parametrize("fault_after", [1, 2, 3, 4])
def test_library_migration_is_atomic_and_preserves_existing_work(tmp_path, fault_after):
    service = service_for(tmp_path, seed_demo_account=False)
    owner = customer_id(service)
    job = chart_for(service, owner)
    source = Path(service._job_row(user_id=owner, job_id=job["id"])["source_path"]).read_bytes()
    with service.database.transaction(immediate=True) as conn:
        conn.execute("DROP INDEX jobs_project_idx")
        conn.execute("ALTER TABLE jobs DROP COLUMN project_id")
        conn.execute("ALTER TABLE jobs DROP COLUMN display_name")
        conn.execute("DROP TABLE projects")
        conn.execute("UPDATE schema_meta SET version=11")
    count = 0

    def crash():
        nonlocal count
        count += 1
        if count == fault_after:
            raise RuntimeError("simulated crash")

    service.database._migration_fault_hook = crash
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.database.initialize()
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 11
        assert "project_id" not in service.database._columns(conn, "jobs")
    service.database._migration_fault_hook = None
    service.database.initialize()
    migrated = service.get_job(user_id=owner, job_id=job["id"])
    assert migrated["display_name"] == migrated["source_name"] == "original.png"
    assert migrated["project_id"] is None
    assert service.account(owner)["credits"] == 2
    assert (
        Path(service._job_row(user_id=owner, job_id=job["id"])["source_path"]).read_bytes()
        == source
    )
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_delete_project_can_keep_active_charts_or_reject_stale_destructive_confirmation(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner = customer_id(service)
    library = ChartLibrary(service)
    project = library.create_project(owner, "Keep my charts")
    job = chart_for(service, owner)
    library.update_chart(owner, job["id"], {"project_id": project["id"]})
    for expected_count, error_code in ((0, "project_changed"), (1, "project_busy")):
        with pytest.raises(ProductError) as error:
            library.delete_project(
                owner, project["id"], mode="delete_charts", expected_chart_count=expected_count
            )
        assert error.value.code == error_code
    result = library.delete_project(
        owner, project["id"], mode="keep_charts", expected_chart_count=None
    )
    assert result == {"status": "deleted", "charts_deleted": 0, "charts_kept": 1}
    kept = service.get_job(user_id=owner, job_id=job["id"])
    assert kept["project_id"] is None and kept["status"] == "queued"
    assert service.job_source(user_id=owner, job_id=job["id"])


def test_delete_project_preserves_other_project_shared_source_and_retries_cleanup(
    tmp_path, monkeypatch
):
    service = service_for(tmp_path, seed_demo_account=False)
    owner = customer_id(service)
    other = customer_id(service, "other@example.com")
    library = ChartLibrary(service)
    project = library.create_project(owner, "Delete this")
    upload = service.prepare_upload(user_id=owner, filename="shared.png", content=png_bytes())
    first, second = (
        chart_for(service, owner, upload=upload),
        chart_for(service, owner, upload=upload),
    )
    for job in (first, second):
        service.cancel(user_id=owner, job_id=job["id"])
    library.update_chart(owner, first["id"], {"project_id": project["id"]})
    with pytest.raises(ProductError) as error:
        library.delete_project(other, project["id"], mode="delete_charts", expected_chart_count=1)
    assert error.value.status_code == 404
    source = Path(service._job_row(user_id=owner, job_id=first["id"])["source_path"])
    delete = service.storage.delete

    def fail_delete(path):
        raise OSError("simulated storage outage")

    monkeypatch.setattr(service.storage, "delete", fail_delete)
    result = library.delete_project(
        owner, project["id"], mode="delete_charts", expected_chart_count=1
    )
    assert result == {"status": "deletion_queued", "charts_deleted": 1, "charts_kept": 0}
    assert library.list_projects(owner)["items"] == []
    with pytest.raises(ProductError):
        service.get_job(user_id=owner, job_id=first["id"])
    assert service.upload_preview(user_id=owner, upload_id=upload["id"], page_index=0)
    assert service.job_source(user_id=owner, job_id=second["id"])
    assert source.exists()
    monkeypatch.setattr(service.storage, "delete", delete)
    service.drain_deletion_queue()
    assert not source.exists()


def test_project_delete_transaction_cannot_remove_only_some_charts(tmp_path, monkeypatch):
    service = service_for(tmp_path, seed_demo_account=False)
    owner = customer_id(service)
    library = ChartLibrary(service)
    project = library.create_project(owner, "Atomic removal")
    jobs = [chart_for(service, owner), chart_for(service, owner)]
    for job in jobs:
        service.cancel(user_id=owner, job_id=job["id"])
        library.update_chart(owner, job["id"], {"project_id": project["id"]})
    queue = service._queue_deletion
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("simulated queue failure")
        return queue(*args, **kwargs)

    monkeypatch.setattr(service, "_queue_deletion", fail_second)
    with pytest.raises(RuntimeError):
        library.delete_project(owner, project["id"], mode="delete_charts", expected_chart_count=2)
    assert library.get_project(owner, project["id"])["chart_count"] == 2
    for job in jobs:
        assert service.job_source(user_id=owner, job_id=job["id"])


def test_discard_upload_revokes_preview_without_deleting_chart_owned_sources(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner, other = customer_id(service), customer_id(service, "other@example.com")
    upload = service.prepare_upload(user_id=owner, filename="discard.png", content=png_bytes())
    job = chart_for(service, owner, upload=upload)
    with pytest.raises(ProductError) as error:
        service.discard_upload(user_id=other, upload_id=upload["id"])
    assert error.value.status_code == 404
    assert service.discard_upload(user_id=owner, upload_id=upload["id"])
    with pytest.raises(ProductError):
        service.upload_preview(user_id=owner, upload_id=upload["id"], page_index=0)
    assert service.get_job(user_id=owner, job_id=job["id"])["status"] == "queued"
    assert service.job_source(user_id=owner, job_id=job["id"])
