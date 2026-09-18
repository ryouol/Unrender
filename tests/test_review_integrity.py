"""A review is a snapshot, including under same-account concurrent writes."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from test_product import csrf_headers, service_for, settings_for

from unrender.product.service import ProductError
from unrender.product.web import create_app


def sample(service):
    session = service.demo_session()
    uid = service.session_user(session["session"])["id"]
    upload = service.prepare_demo_upload(uid)
    job = service.create_job(user_id=uid, upload_id=upload["id"], page_index=0, crop=None)
    assert service.process_one()
    return uid, service.get_job(user_id=uid, job_id=job["id"])


def edited(job, value):
    result = copy.deepcopy(job["result"])
    result["series"][0]["points"][0]["y"] = value
    return result


def save(service, uid, job, value):
    return service.save_correction(
        user_id=uid,
        job_id=job["id"],
        result=edited(job, value),
        expected_revision=job["review_revision"],
    )


def assert_conflict(operation):
    with pytest.raises(ProductError) as caught:
        operation()
    assert (caught.value.code, caught.value.status_code) == ("result_conflict", 409)


def test_stale_save_approve_restore_and_export_cannot_change_latest(tmp_path):
    service = service_for(tmp_path)
    uid, seen = sample(service)
    latest = save(service, uid, seen, 123456)
    assert latest["result_version"] == 2
    assert latest["result_sha256"] != seen["result_sha256"]
    assert_conflict(lambda: save(service, uid, seen, 9.2))
    assert_conflict(
        lambda: service.approve(
            user_id=uid, job_id=seen["id"], expected_revision=seen["review_revision"]
        )
    )
    assert_conflict(
        lambda: service.restore_version(
            user_id=uid, job_id=seen["id"], version=1, expected_revision=seen["review_revision"]
        )
    )
    for output_format in ("json", "csv", "xlsx"):
        assert_conflict(
            lambda output_format=output_format: service.export(
                user_id=uid,
                job_id=seen["id"],
                output_format=output_format,
                expected_revision=seen["review_revision"],
            )
        )
    assert service.get_job(user_id=uid, job_id=seen["id"]) == latest
    assert len(service.job_versions(user_id=uid, job_id=seen["id"])["items"]) == 2
    assert not any(
        e["event"] in {"result_approved", "result_exported"}
        for e in service.job_audit(user_id=uid, job_id=seen["id"])
    )


def test_identical_content_restore_still_invalidates_old_revision(tmp_path):
    service = service_for(tmp_path)
    uid, original = sample(service)
    changed = save(service, uid, original, 123456)
    restored = service.restore_version(
        user_id=uid,
        job_id=original["id"],
        version=1,
        expected_revision=changed["review_revision"],
    )
    assert restored["result"] == original["result"]
    assert restored["result_sha256"] == original["result_sha256"]
    assert restored["result_version"] == 3
    assert restored["review_revision"] != original["review_revision"]
    assert_conflict(
        lambda: service.approve(
            user_id=uid, job_id=original["id"], expected_revision=original["review_revision"]
        )
    )
    event = service.job_audit(user_id=uid, job_id=original["id"])[0]
    assert event["details"]["restored_from_version"] == 1
    assert event["details"]["version"] == 3


def test_two_connections_cannot_both_save_the_same_revision(tmp_path):
    service = service_for(tmp_path)
    uid, seen = sample(service)
    other = service_for(tmp_path)
    barrier = threading.Barrier(2)

    def write(client, value):
        barrier.wait(timeout=5)
        try:
            return save(client, uid, seen, value)
        except ProductError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(write, service, 101)
        b = pool.submit(write, other, 202)
        results = [a.result(timeout=15), b.result(timeout=15)]
    winners = [r for r in results if isinstance(r, dict)]
    losers = [r for r in results if isinstance(r, ProductError)]
    assert len(winners) == len(losers) == 1
    assert losers[0].code == "result_conflict"
    assert service.get_job(user_id=uid, job_id=seen["id"]) == winners[0]
    assert len(service.job_versions(user_id=uid, job_id=seen["id"])["items"]) == 2


def test_save_response_is_its_own_snapshot_even_if_another_write_follows_commit(
    tmp_path, monkeypatch
):
    service = service_for(tmp_path)
    uid, seen = sample(service)
    other = service_for(tmp_path)
    original_transaction = service.database.transaction
    intervened = []

    @contextmanager
    def transaction(**kwargs):
        with original_transaction(**kwargs) as conn:
            yield conn
        if kwargs.get("immediate") and not intervened:
            current = other.get_job(user_id=uid, job_id=seen["id"])
            intervened.append(save(other, uid, current, 202))

    monkeypatch.setattr(service.database, "transaction", transaction)
    returned = save(service, uid, seen, 101)
    assert returned["result"]["series"][0]["points"][0]["y"] == 101
    assert intervened[0]["result"]["series"][0]["points"][0]["y"] == 202
    assert_conflict(
        lambda: service.approve(
            user_id=uid, job_id=seen["id"], expected_revision=returned["review_revision"]
        )
    )


def test_approval_and_export_receipts_bind_exact_snapshot(tmp_path, monkeypatch):
    service = service_for(tmp_path)
    uid, seen = sample(service)
    approved = service.approve(
        user_id=uid, job_id=seen["id"], expected_revision=seen["review_revision"]
    )
    assert approved["result_sha256"] == seen["result_sha256"]
    assert approved["review_revision"] != seen["review_revision"]
    # A view of the old draft cannot silently download an approved export.
    assert_conflict(
        lambda: service.export(
            user_id=uid,
            job_id=seen["id"],
            output_format="json",
            expected_revision=seen["review_revision"],
        )
    )
    # An uncertain approval retry cannot create a second approval event.
    assert_conflict(
        lambda: service.approve(
            user_id=uid, job_id=seen["id"], expected_revision=seen["review_revision"]
        )
    )
    payload, _ = service.export(
        user_id=uid,
        job_id=seen["id"],
        output_format="xlsx",
        expected_revision=approved["review_revision"],
    )
    audit = dict(list(load_workbook(io.BytesIO(payload))["Audit"].values)[1:])
    assert audit["Result version"] == 1
    assert audit["Result SHA-256"] == approved["result_sha256"]
    assert audit["Review revision"] == approved["review_revision"]
    with service.database.connect() as conn:
        raw = conn.execute(
            "SELECT chart_json FROM result_versions WHERE job_id=?", (seen["id"],)
        ).fetchone()[0]
    assert hashlib.sha256(raw.encode()).hexdigest() == approved["result_sha256"]

    original_csv = service._safe_csv

    def edit_during_export(chart, provenance):
        save(service, uid, approved, 123456)
        return original_csv(chart, provenance)

    monkeypatch.setattr(service, "_safe_csv", edit_during_export)
    payload, _ = service.export(
        user_id=uid,
        job_id=seen["id"],
        output_format="csv",
        expected_revision=approved["review_revision"],
    )
    assert b"123456" not in payload
    events = service.job_audit(user_id=uid, job_id=seen["id"])
    assert sum(e["event"] == "result_approved" for e in events) == 1
    for event in events:
        if event["event"] in {"result_approved", "result_exported"}:
            assert event["details"]["version"] == 1
            assert event["details"]["sha256"] == approved["result_sha256"]
            assert event["details"]["review_revision"] == approved["review_revision"]


def test_browser_api_requires_revision_and_rejects_stale_clients(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        assert client.post("/api/auth/demo").status_code == 200
        upload = client.post("/api/uploads/demo", headers=csrf_headers(client)).json()
        created = client.post(
            "/api/jobs",
            headers={**csrf_headers(client), "Idempotency-Key": "review-test"},
            json={"upload_id": upload["id"], "page_index": 0},
        ).json()
        assert app.state.service.process_one()
        url = f"/api/jobs/{created['id']}"
        original = client.get(url).json()
        for endpoint, body in (
            ("result", {"result": original["result"]}),
            ("approve", {}),
            ("restore", {"version": 1}),
        ):
            call = client.patch if endpoint == "result" else client.post
            assert (
                call(f"{url}/{endpoint}", json=body, headers=csrf_headers(client)).status_code
                == 422
            )
        assert client.get(f"{url}/export/json").status_code == 422
        changed = client.patch(
            f"{url}/result",
            headers=csrf_headers(client),
            json={
                "result": edited(original, 123456),
                "expected_revision": original["review_revision"],
            },
        )
        assert changed.status_code == 200
        for endpoint, body in (
            ("result", {"result": original["result"]}),
            ("approve", {}),
            ("restore", {"version": 1}),
        ):
            call = client.patch if endpoint == "result" else client.post
            response = call(
                f"{url}/{endpoint}",
                json={**body, "expected_revision": original["review_revision"]},
                headers=csrf_headers(client),
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "result_conflict"
        stale = client.get(
            f"{url}/export/json", params={"expected_revision": original["review_revision"]}
        )
        assert stale.status_code == 409
        approved = client.post(
            f"{url}/approve",
            json={"expected_revision": changed.json()["review_revision"]},
            headers=csrf_headers(client),
        ).json()
        exported = client.get(
            f"{url}/export/json", params={"expected_revision": approved["review_revision"]}
        )
        assert exported.status_code == 200
        assert exported.headers["X-Unrender-Review-Revision"] == approved["review_revision"]
        assert json.loads(exported.content)["chart"] == approved["result"]


def test_inconsistent_persisted_history_fails_closed(tmp_path):
    service = service_for(tmp_path)
    uid, seen = sample(service)
    with service.database.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET current_result_json=? WHERE id=?",
            (json.dumps(edited(seen, 202)), seen["id"]),
        )
    with pytest.raises(ProductError) as caught:
        service.get_job(user_id=uid, job_id=seen["id"])
    assert caught.value.code == "result_history_inconsistent"
