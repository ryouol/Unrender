from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
import stripe
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image

from unrender.product import admin
from unrender.product.config import Settings
from unrender.product.database import Database
from unrender.product.extractors import (
    ExtractionError,
    ExtractionOutput,
    ModalExtractor,
    ReplayExtractor,
)
from unrender.product.security import hash_password, password_needs_rehash, verify_password
from unrender.product.service import ProductError, ProductService
from unrender.product.storage import InvalidUpload, Storage
from unrender.product.web import CSRF_COOKIE, create_app
from unrender.schema.chart_schema import ChartData

STATIC_DIR = Path(__file__).parents[1] / "unrender" / "product" / "static"


def settings_for(tmp_path: Path, **changes: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": tmp_path / "data",
        "environment": "test",
        "base_url": "http://testserver",
        "extractor_backend": "replay",
        "worker_enabled": False,
        "allow_registration": True,
        "seed_demo_account": True,
        "initial_credits": 3,
        "rate_limit_per_minute": 1000,
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def service_for(tmp_path: Path, **changes: object) -> ProductService:
    settings = settings_for(tmp_path, **changes)
    service = ProductService(
        settings=settings,
        database=Database(settings.database_path),
        storage=Storage(settings),
        extractor=ReplayExtractor(STATIC_DIR),
        static_dir=STATIC_DIR,
    )
    service.initialize()
    return service


def customer_id(service: ProductService, email: str = "customer@example.com") -> str:
    session = service.register(email, "customer password is long enough")
    user = service.session_user(session["session"])
    assert user is not None
    return str(user["id"])


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE)}


def register_and_create_api_key(
    client: TestClient,
    *,
    email: str = "api@example.com",
) -> str:
    registered = client.post(
        "/api/auth/register",
        json={"email": email, "password": "api customer password is long enough"},
    )
    assert registered.status_code == 201
    created = client.post(
        "/api/keys",
        headers=csrf_headers(client),
        json={"name": "integration"},
    )
    assert created.status_code == 201
    return str(created.json()["key"])


def png_bytes(*, color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (160, 100), color=color).save(output, format="PNG")
    return output.getvalue()


def test_configuration_rejects_unsafe_production_and_live_billing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="http://example.com",
            extractor_backend="modal",
            seed_demo_account=False,
        ).validate()
    with pytest.raises(ValueError, match="Replay"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="https://example.com",
            seed_demo_account=False,
        ).validate()
    with pytest.raises(ValueError, match="MODAL_REVISION"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="https://example.com",
            extractor_backend="modal",
            seed_demo_account=False,
            allow_registration=False,
            worker_enabled=True,
            modal_model_path="approved/unrender-model",
        ).validate()
    with pytest.raises(ValueError, match="ALLOW_REGISTRATION"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="https://example.com",
            extractor_backend="modal",
            seed_demo_account=False,
            modal_model_path="approved/unrender-model",
            modal_model_revision="0123456789abcdef0123456789abcdef01234567",
        ).validate()
    with pytest.raises(ValueError, match="MODEL must be"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="https://example.com",
            extractor_backend="modal",
            seed_demo_account=False,
            allow_registration=False,
            worker_enabled=True,
            modal_model_revision="0123456789abcdef0123456789abcdef01234567",
        ).validate()
    settings_for(
        tmp_path,
        environment="production",
        base_url="https://example.com",
        extractor_backend="modal",
        seed_demo_account=False,
        allow_registration=False,
        modal_model_path="approved/unrender-model",
        modal_model_revision="0123456789abcdef0123456789abcdef01234567",
        modal_provider_release="a" * 64,
        worker_enabled=True,
    ).validate()
    with pytest.raises(ValueError, match="PROVIDER_RELEASE"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="https://example.com",
            extractor_backend="modal",
            seed_demo_account=False,
            allow_registration=False,
            worker_enabled=True,
            modal_model_path="approved/unrender-model",
            modal_model_revision="0123456789abcdef0123456789abcdef01234567",
        ).validate()
    with pytest.raises(ValueError, match="WORKER_ENABLED"):
        settings_for(
            tmp_path,
            environment="production",
            base_url="https://example.com",
            extractor_backend="modal",
            seed_demo_account=False,
            allow_registration=False,
            worker_enabled=False,
            modal_model_path="approved/unrender-model",
            modal_model_revision="0123456789abcdef0123456789abcdef01234567",
        ).validate()
    with pytest.raises(ValueError, match="test-mode"):
        settings_for(
            tmp_path,
            stripe_secret_key="sk_live_forbidden",
            stripe_webhook_secret="whsec_test",
            stripe_price_id="price_test",
        ).validate()
    with pytest.raises(ValueError, match="secret, webhook secret, and price"):
        settings_for(tmp_path, stripe_secret_key="sk_test_partial").validate()
    with pytest.raises(ValueError, match="without a path"):
        settings_for(tmp_path, base_url="https://example.com/unrender").validate()
    with pytest.raises(ValueError, match="MAX_USER_STORAGE_BYTES"):
        settings_for(
            tmp_path,
            max_upload_bytes=1024,
            max_user_storage_bytes=512,
        ).validate()
    with pytest.raises(ValueError, match="Tenant upload limits"):
        settings_for(tmp_path, max_unattached_uploads=0).validate()


def test_runtime_lock_includes_the_production_provider_client() -> None:
    lock = (STATIC_DIR.parents[2] / "requirements-app.lock").read_text(encoding="utf-8")
    assert "\nmodal==" in lock


def test_modal_release_handshake_rejects_drift_and_records_approved_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = json.loads(
        (STATIC_DIR / "demo" / "budget-quarter-result.json").read_text(encoding="utf-8")
    )
    release = "a" * 64
    response = {
        "json": fixture["result"],
        "raw": fixture["raw"],
        "provider_release": "b" * 64,
    }
    remote = SimpleNamespace(remote=lambda *_: response)
    modal = SimpleNamespace(
        Function=SimpleNamespace(from_name=lambda *_: remote),
    )
    monkeypatch.setitem(sys.modules, "modal", modal)
    extractor = ModalExtractor(
        settings_for(
            tmp_path,
            extractor_backend="modal",
            modal_model_path="approved/unrender-model",
            modal_model_revision="1" * 40,
            modal_provider_release=release,
        )
    )
    with pytest.raises(ExtractionError, match="approved deployment"):
        extractor.extract(png_bytes())

    response["provider_release"] = release
    output = extractor.extract(png_bytes())
    assert output.model_version.endswith(f"+provider:{release[:12]}")


def test_passwords_are_salted_and_verified() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)
    assert first.split("$")[3] == "5"
    assert not password_needs_rehash(first)


def test_login_opportunistically_upgrades_legacy_scrypt_parameters(tmp_path: Path) -> None:
    service = service_for(tmp_path, seed_demo_account=False)
    user_id = service.provision_user("legacy@example.com", "legacy password is long enough")
    salt = b"legacy-salt-1234"
    derived = hashlib.scrypt(b"legacy password is long enough", salt=salt, n=2**14, r=8, p=1)
    legacy = "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode("ascii")
    legacy += "$" + base64.urlsafe_b64encode(derived).decode("ascii")
    with service.database.transaction(immediate=True) as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (legacy, user_id))

    service.authenticate("legacy@example.com", "legacy password is long enough")

    with service.database.connect() as conn:
        upgraded = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    assert upgraded["password_hash"].split("$")[3] == "5"
    assert not password_needs_rehash(upgraded["password_hash"])


def test_operator_can_provision_when_public_registration_is_closed(tmp_path: Path) -> None:
    service = service_for(tmp_path, allow_registration=False, seed_demo_account=False)
    with pytest.raises(ProductError, match="closed"):
        service.register("blocked@example.com", "a sufficiently long password")
    user_id = service.provision_user(
        "invited@example.com", "an operator supplied password", credits=7
    )
    assert service.account(user_id)["credits"] == 7
    with service.database.connect() as conn:
        ledger = conn.execute(
            "SELECT reason FROM credit_ledger WHERE user_id=?", (user_id,)
        ).fetchone()
    assert ledger["reason"] == "operator_grant"
    session = service.authenticate("invited@example.com", "an operator supplied password")
    assert service.session_user(session["session"])["id"] == user_id


def test_cancel_wins_atomic_race_with_worker_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = service_for(tmp_path)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id, filename="customer-chart.png", content=png_bytes(color="blue")
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    fixture = json.loads(
        (STATIC_DIR / "demo" / "budget-quarter-result.json").read_text(encoding="utf-8")
    )
    service.extractor = SimpleNamespace(
        extract=lambda _: ExtractionOutput(
            chart=ChartData.model_validate(fixture["result"]),
            raw="atomic completion test",
            extractor="test",
            model_version="test-pinned",
        )
    )

    original_transaction = service.database.transaction
    completion_waiting = threading.Event()
    allow_completion = threading.Event()
    transaction_count = 0
    count_lock = threading.Lock()

    @contextmanager
    def gated_transaction(*, immediate: bool = False) -> Iterator[object]:
        nonlocal transaction_count
        with count_lock:
            transaction_count += 1
            current_count = transaction_count
        if current_count == 4:
            completion_waiting.set()
            assert allow_completion.wait(timeout=5)
        with original_transaction(immediate=immediate) as conn:
            yield conn

    monkeypatch.setattr(service.database, "transaction", gated_transaction)
    worker = threading.Thread(target=service.process_one)
    worker.start()
    assert completion_waiting.wait(timeout=5)
    service.cancel(user_id=user_id, job_id=job["id"])
    allow_completion.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert service.get_job(user_id=user_id, job_id=job["id"])["status"] == "cancelled"
    assert service.account(user_id)["credits"] == 3


def test_cancel_request_wins_when_provider_fails(tmp_path: Path) -> None:
    service = service_for(tmp_path)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id, filename="customer-chart.png", content=png_bytes(color="blue")
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    provider_started = threading.Event()
    provider_release = threading.Event()

    def fail_after_cancel(_: bytes) -> None:
        provider_started.set()
        assert provider_release.wait(timeout=5)
        raise ExtractionError("provider_unavailable", "provider failed")

    service.extractor = SimpleNamespace(extract=fail_after_cancel)
    worker = threading.Thread(target=service.process_one)
    worker.start()
    assert provider_started.wait(timeout=5)
    service.cancel(user_id=user_id, job_id=job["id"])
    provider_release.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert service.get_job(user_id=user_id, job_id=job["id"])["status"] == "cancelled"
    assert service.account(user_id)["credits"] == 3


def test_provider_failures_emit_privacy_safe_operational_fields(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = service_for(tmp_path, seed_demo_account=False)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id,
        filename="customer-private-name.png",
        content=png_bytes(color="purple"),
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)

    def fail_provider(_: bytes) -> None:
        raise ExtractionError("provider_unavailable", "secret upstream detail")

    service.extractor = SimpleNamespace(extract=fail_provider)
    with caplog.at_level("INFO", logger="unrender.product"):
        assert service.process_one()

    failed = next(record for record in caplog.records if record.message == "provider_call_failed")
    assert failed.event_name == "provider_call_failed"
    assert failed.error_code == "provider_unavailable"
    assert failed.job_id == job["id"]
    assert isinstance(failed.duration_ms, int)
    rendered = " ".join(record.getMessage() for record in caplog.records)
    assert "customer-private-name" not in rendered
    assert "secret upstream detail" not in rendered


def test_reprocess_failure_and_cancel_preserve_approved_result(tmp_path: Path) -> None:
    service = service_for(tmp_path)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id, filename="customer-chart.png", content=png_bytes(color="blue")
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    fixture = json.loads(
        (STATIC_DIR / "demo" / "budget-quarter-result.json").read_text(encoding="utf-8")
    )
    service.extractor = SimpleNamespace(
        extract=lambda _: ExtractionOutput(
            chart=ChartData.model_validate(fixture["result"]),
            raw="approved result preservation test",
            extractor="test",
            model_version="test-pinned",
        )
    )
    assert service.process_one()
    approved = service.approve(user_id=user_id, job_id=job["id"])
    approved_result = approved["result"]
    approved_at = approved["approved_at"]
    assert service.account(user_id)["credits"] == 2

    service.reprocess(user_id=user_id, job_id=job["id"])

    def fail_provider(_: bytes) -> None:
        raise ExtractionError("provider_unavailable", "provider failed")

    service.extractor = SimpleNamespace(extract=fail_provider)
    assert service.process_one()
    after_failure = service.get_job(user_id=user_id, job_id=job["id"])
    assert after_failure["status"] == "approved"
    assert after_failure["approved_at"] == approved_at
    assert after_failure["result"] == approved_result
    assert after_failure["error"]["code"] == "provider_unavailable"
    assert service.account(user_id)["credits"] == 2

    service.reprocess(user_id=user_id, job_id=job["id"])
    after_cancel = service.cancel(user_id=user_id, job_id=job["id"])
    assert after_cancel["status"] == "approved"
    assert after_cancel["approved_at"] == approved_at
    assert after_cancel["result"] == approved_result
    assert service.account(user_id)["credits"] == 2


def test_admin_cli_prompts_for_password_and_creates_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "operator-data"
    monkeypatch.setenv("UNRENDER_DATA_DIR", str(data_dir))
    monkeypatch.setenv("UNRENDER_ENV", "test")
    monkeypatch.setenv("UNRENDER_BASE_URL", "http://testserver")
    monkeypatch.setenv("UNRENDER_SEED_DEMO", "false")
    monkeypatch.setenv("UNRENDER_ALLOW_REGISTRATION", "false")
    monkeypatch.setattr(
        "sys.argv", ["unrender-admin", "create-user", "operator@example.com", "--credits", "4"]
    )
    passwords = iter(["an operator supplied password", "an operator supplied password"])
    monkeypatch.setattr(admin.getpass, "getpass", lambda _: next(passwords))

    admin.main()

    assert capsys.readouterr().out.startswith("Created account ")
    with Database(data_dir / "unrender.sqlite3").connect() as conn:
        row = conn.execute(
            "SELECT email, credit_balance FROM users WHERE email=?", ("operator@example.com",)
        ).fetchone()
    assert dict(row) == {"email": "operator@example.com", "credit_balance": 4}


def test_storage_validates_magic_pdf_limits_and_crop(tmp_path: Path) -> None:
    storage = Storage(settings_for(tmp_path, max_pdf_pages=1))
    with pytest.raises(InvalidUpload, match="PNG, JPEG, WebP, or PDF"):
        storage.inspect(b"not-an-image")

    document = pymupdf.open()
    document.new_page()
    document.new_page()
    pdf = document.tobytes()
    document.close()
    with pytest.raises(InvalidUpload, match="limit is 1"):
        storage.inspect(pdf)

    image = png_bytes()
    inspection = storage.inspect(image)
    source = storage.save_upload(user_id="user", upload_id="upload", content=image)
    cropped = storage.page_png(
        source=source,
        mime_type=inspection.mime_type,
        page_index=0,
        crop={"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
    )
    assert cropped.startswith(b"\x89PNG")
    with pytest.raises(InvalidUpload, match="within"):
        storage.page_png(
            source=source,
            mime_type=inspection.mime_type,
            page_index=0,
            crop={"x": 0.8, "y": 0.1, "width": 0.5, "height": 0.5},
        )


def test_database_and_customer_sources_are_private_on_disk(tmp_path: Path) -> None:
    service = service_for(tmp_path, seed_demo_account=False)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id,
        filename="private.png",
        content=png_bytes(),
    )
    row = service.upload(user_id=user_id, upload_id=upload["id"])

    assert stat.S_IMODE(service.settings.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(service.settings.storage_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(service.settings.database_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(row["storage_path"]).stat().st_mode) == 0o600


def test_schema_v2_upgrades_to_storage_quota_and_idempotency_state(tmp_path: Path) -> None:
    database = Database(tmp_path / "migration" / "unrender.sqlite3")
    database.initialize()
    with database.connect() as conn:
        conn.execute("DROP TABLE api_idempotency")
        conn.execute("ALTER TABLE jobs DROP COLUMN source_byte_size")
        conn.execute("ALTER TABLE pending_deletions DROP COLUMN user_id")
        conn.execute("ALTER TABLE pending_deletions DROP COLUMN byte_size")
        conn.execute("UPDATE schema_meta SET version=2")

    database.initialize()
    with database.connect() as conn:
        version = conn.execute("SELECT version FROM schema_meta").fetchone()["version"]
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        deletion_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(pending_deletions)")
        }
        idempotency = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_idempotency'"
        ).fetchone()
    assert version == 4
    assert "source_byte_size" in job_columns
    assert {"user_id", "byte_size"} <= deletion_columns
    assert idempotency is not None


def test_tenant_upload_quota_and_bandwidth_limit_leave_no_orphan_files(
    tmp_path: Path,
) -> None:
    content = png_bytes()
    service = service_for(
        tmp_path,
        seed_demo_account=False,
        max_upload_bytes=len(content) + 100,
        max_user_storage_bytes=(len(content) * 2) + 100,
        max_unattached_uploads=1,
        max_upload_bytes_per_minute=len(content) * 10,
    )
    user_id = customer_id(service)
    first = service.prepare_upload(user_id=user_id, filename="first.png", content=content)
    service.create_job(user_id=user_id, upload_id=first["id"], page_index=0, crop=None)
    with pytest.raises(ProductError, match="storage limit"):
        service.prepare_upload(user_id=user_id, filename="second.png", content=content)
    with service.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM uploads").fetchone()["count"] == 1
        assert conn.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"] == 1
    assert len(service.storage.object_paths()) == 2

    limited = service_for(
        tmp_path / "bandwidth",
        seed_demo_account=False,
        max_upload_bytes=len(content) + 100,
        max_user_storage_bytes=len(content) * 20,
        max_unattached_uploads=5,
        max_upload_bytes_per_minute=len(content),
    )
    limited_user = customer_id(limited, "bandwidth@example.com")
    limited.prepare_upload(user_id=limited_user, filename="first.png", content=content)
    with pytest.raises(ProductError, match="bandwidth"):
        limited.prepare_upload(user_id=limited_user, filename="second.png", content=content)
    assert len(limited.storage.object_paths()) == 1


def test_saved_sample_runs_free_through_review_approval_and_exports(tmp_path: Path) -> None:
    service = service_for(tmp_path)
    session = service.demo_session()
    user = service.session_user(session["session"])
    assert user is not None
    user_id = str(user["id"])
    starting_credits = service.account(user_id)["credits"]

    upload = service.prepare_demo_upload(user_id)
    job = service.create_job(
        user_id=user_id,
        upload_id=upload["id"],
        page_index=0,
        crop=None,
    )
    assert service.account(user_id)["credits"] == starting_credits
    assert job["status"] == "queued"
    assert service.process_one()

    job = service.get_job(user_id=user_id, job_id=job["id"])
    assert job["status"] == "review"
    assert job["model_version"] == "verified-fixture/synthetic-v1-0002906"
    corrected = job["result"]
    corrected["title"] = "Budget by quarter — reviewed"
    job = service.save_correction(user_id=user_id, job_id=job["id"], result=corrected)
    assert job["result"]["title"].endswith("reviewed")
    versions = service.job_versions(user_id=user_id, job_id=job["id"])
    assert [item["version"] for item in versions] == [2, 1]
    assert versions[0]["source"] == "correction"
    assert versions[1]["source"] == "extraction"
    job = service.approve(user_id=user_id, job_id=job["id"])
    assert job["status"] == "approved"

    csv_payload, csv_mime = service.export(user_id=user_id, job_id=job["id"], output_format="csv")
    json_payload, _ = service.export(user_id=user_id, job_id=job["id"], output_format="json")
    xlsx_payload, _ = service.export(user_id=user_id, job_id=job["id"], output_format="xlsx")
    assert csv_mime.startswith("text/csv")
    assert b"Q3 2016" in csv_payload
    assert json.loads(json_payload)["title"].endswith("reviewed")
    assert xlsx_payload.startswith(b"PK")
    events = [item["event"] for item in service.job_audit(user_id=user_id, job_id=job["id"])]
    assert "extraction_completed" in events
    assert "result_corrected" in events
    assert "result_approved" in events
    assert events.count("result_exported") == 3


def test_demo_sessions_are_isolated_and_cannot_create_customer_data(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        assert client.post("/api/auth/demo").status_code == 200
        first_account = client.get("/api/me").json()
        assert first_account["demo_account"] is True
        first_upload = client.post("/api/uploads/demo", headers=csrf_headers(client))
        first_job = client.post(
            "/api/jobs",
            headers=csrf_headers(client),
            json={"upload_id": first_upload.json()["id"], "page_index": 0},
        )
        assert first_job.status_code == 202
        assert app.state.service.process_one()
        repeated_sample = client.post("/api/uploads/demo", headers=csrf_headers(client))
        assert repeated_sample.status_code == 409

        client.cookies.clear()
        assert client.post("/api/auth/demo").status_code == 200
        second_account = client.get("/api/me").json()
        assert second_account["id"] != first_account["id"]
        assert client.get("/api/jobs").json()["items"] == []
        blocked_upload = client.post(
            "/api/uploads",
            headers=csrf_headers(client),
            files={"file": ("private.png", png_bytes(), "image/png")},
        )
        assert blocked_upload.status_code == 403
        assert (
            client.post("/api/keys", headers=csrf_headers(client), json={"name": "x"}).status_code
            == 403
        )


def test_demo_logout_removes_ephemeral_tenant_and_sources(tmp_path: Path) -> None:
    service = service_for(tmp_path)
    session = service.demo_session()
    user = service.session_user(session["session"])
    assert user is not None
    user_id = str(user["id"])
    upload = service.prepare_demo_upload(user_id)
    service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    assert service.process_one()
    with service.database.connect() as conn:
        paths = [
            Path(row["path"])
            for row in conn.execute(
                "SELECT storage_path AS path FROM uploads WHERE user_id=? "
                "UNION SELECT source_path AS path FROM jobs WHERE user_id=?",
                (user_id, user_id),
            ).fetchall()
        ]
    assert paths and all(path.exists() for path in paths)

    service.logout(session["session"])

    assert service.session_user(session["session"]) is None
    with service.database.connect() as conn:
        assert conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None
        pending = conn.execute("SELECT COUNT(*) AS count FROM pending_deletions").fetchone()
    assert pending["count"] == 0
    assert all(not path.exists() for path in paths)


def test_failed_file_delete_stays_retryable_after_job_row_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = service_for(tmp_path, seed_demo_account=False)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id, filename="delete-me.png", content=png_bytes(color="red")
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    service.cancel(user_id=user_id, job_id=job["id"])
    source_path = Path(service._job_row(user_id=user_id, job_id=job["id"])["source_path"])
    original_delete = service.storage.delete

    def fail_delete(_: str | Path) -> None:
        raise OSError("simulated storage outage")

    monkeypatch.setattr(service.storage, "delete", fail_delete)
    assert service.delete_job(user_id=user_id, job_id=job["id"]) is False
    with pytest.raises(ProductError, match="not found"):
        service.get_job(user_id=user_id, job_id=job["id"])
    assert source_path.exists()
    with service.database.connect() as conn:
        queued = conn.execute(
            "SELECT attempts,last_error FROM pending_deletions WHERE storage_path=?",
            (str(source_path),),
        ).fetchone()
    assert queued["attempts"] == 1
    assert "OSError" in queued["last_error"]

    monkeypatch.setattr(service.storage, "delete", original_delete)
    assert service.drain_deletion_queue() >= 1
    assert not source_path.exists()


def test_retention_cleanup_queues_files_when_storage_is_temporarily_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = service_for(tmp_path, seed_demo_account=False)
    user_id = customer_id(service)
    upload = service.prepare_upload(
        user_id=user_id, filename="expired.png", content=png_bytes(color="orange")
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    service.cancel(user_id=user_id, job_id=job["id"])
    with service.database.transaction(immediate=True) as conn:
        paths = [
            str(row["path"])
            for row in conn.execute(
                "SELECT storage_path AS path FROM uploads WHERE id=? "
                "UNION SELECT source_path AS path FROM jobs WHERE id=?",
                (upload["id"], job["id"]),
            ).fetchall()
        ]
        conn.execute(
            "UPDATE uploads SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (upload["id"],)
        )
        conn.execute("UPDATE jobs SET updated_at='2000-01-01T00:00:00Z' WHERE id=?", (job["id"],))
    original_delete = service.storage.delete

    def fail_retention_delete(_: str | Path) -> None:
        raise OSError("storage unavailable")

    monkeypatch.setattr(service.storage, "delete", fail_retention_delete)

    cleaned = service.cleanup_expired()
    assert cleaned["uploads"] == 1
    assert cleaned["jobs"] == 1
    with service.database.connect() as conn:
        assert conn.execute("SELECT 1 FROM uploads WHERE id=?", (upload["id"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM jobs WHERE id=?", (job["id"],)).fetchone() is None
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM pending_deletions").fetchone()["count"] >= 2
        )
    assert all(Path(path).exists() for path in paths)

    monkeypatch.setattr(service.storage, "delete", original_delete)
    assert service.drain_deletion_queue() >= 2
    assert all(not Path(path).exists() for path in paths)


def test_storage_reconciliation_removes_unowned_crash_file(tmp_path: Path) -> None:
    service = service_for(tmp_path, seed_demo_account=False)
    orphan = service.settings.storage_dir / "jobs" / "orphan" / "crash.tmp"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    assert service.reconcile_storage() == 1
    assert service.drain_deletion_queue() == 1
    assert not orphan.exists()


def test_spreadsheet_exports_neutralize_formula_cells(tmp_path: Path) -> None:
    service = service_for(tmp_path)
    session = service.demo_session()
    user = service.session_user(session["session"])
    assert user is not None
    user_id = str(user["id"])
    upload = service.prepare_demo_upload(user_id)
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    assert service.process_one()
    job = service.get_job(user_id=user_id, job_id=job["id"])
    result = job["result"]
    result["x_axis"]["label"] = "=SUM(A1:A2)"
    result["y_axis"]["label"] = "@external"
    result["series"][0]["points"][0] = {
        "x": "+cmd|' /C calc'!A0",
        "y": -9.2,
    }
    service.save_correction(user_id=user_id, job_id=job["id"], result=result)

    csv_payload, _ = service.export(user_id=user_id, job_id=job["id"], output_format="csv")
    rows = list(csv.reader(io.StringIO(csv_payload.decode("utf-8"))))
    assert rows[0] == ["'=SUM(A1:A2)", "'@external"]
    assert rows[1] == ["'+cmd|' /C calc'!A0", "-9.2"]

    xlsx_payload, _ = service.export(user_id=user_id, job_id=job["id"], output_format="xlsx")
    workbook = load_workbook(io.BytesIO(xlsx_payload), data_only=False)
    sheet = workbook["Extracted data"]
    assert sheet["A1"].value == "'=SUM(A1:A2)"
    assert sheet["A1"].data_type == "s"
    assert sheet["A2"].value == "'+cmd|' /C calc'!A0"
    assert sheet["B2"].value == -9.2
    assert sheet["B2"].data_type == "n"


def test_multi_series_exports_preserve_duplicate_points_and_numeric_cells(tmp_path: Path) -> None:
    service = service_for(tmp_path)
    chart = ChartData.model_validate(
        {
            "chart_type": "multi_line",
            "title": "Repeated categories",
            "x_axis": {"label": "Period", "unit": None},
            "y_axis": {"label": "Value", "unit": None},
            "series": [
                {"name": None, "points": [{"x": "001", "y": 1.25}, {"x": "001", "y": 2.5}]},
                {"name": "Peer", "points": [{"x": 1.0, "y": 3.75}]},
            ],
        }
    )
    csv_rows = list(csv.reader(io.StringIO(service._safe_csv(chart))))
    assert csv_rows == [
        ["series", "Period", "Value"],
        ["series_1", "001", "1.25"],
        ["series_1", "001", "2.5"],
        ["Peer", "1.0", "3.75"],
    ]
    workbook = load_workbook(
        io.BytesIO(
            service._xlsx(
                chart,
                {
                    "source_name": "multi.png",
                    "id": "job-1",
                    "model_version": "test-model",
                    "status": "review",
                    "approved_at": None,
                },  # type: ignore[arg-type]
            )
        )
    )
    sheet = workbook["Extracted data"]
    assert sheet["B2"].value == "001"
    assert sheet["C2"].value == 1.25
    assert sheet["C2"].data_type == "n"


def test_failed_and_cancelled_jobs_refund_once_and_tenants_are_isolated(
    tmp_path: Path,
) -> None:
    service = service_for(tmp_path, seed_demo_account=False, initial_credits=2)
    first = service.register("first@example.com", "first password is long enough")
    second = service.register("second@example.com", "second password is long enough")
    first_user = service.session_user(first["session"])
    second_user = service.session_user(second["session"])
    assert first_user is not None and second_user is not None
    first_id, second_id = str(first_user["id"]), str(second_user["id"])

    upload = service.prepare_upload(
        user_id=first_id, filename="custom.png", content=png_bytes(color="navy")
    )
    failed = service.create_job(user_id=first_id, upload_id=upload["id"], page_index=0, crop=None)
    assert service.account(first_id)["credits"] == 1
    assert service.process_one()
    failed = service.get_job(user_id=first_id, job_id=failed["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "provider_not_configured"
    assert service.account(first_id)["credits"] == 2
    with pytest.raises(ProductError, match="not found"):
        service.get_job(user_id=second_id, job_id=failed["id"])

    queued = service.create_job(user_id=first_id, upload_id=upload["id"], page_index=0, crop=None)
    assert service.account(first_id)["credits"] == 1
    cancelled = service.cancel(user_id=first_id, job_id=queued["id"])
    assert cancelled["status"] == "cancelled"
    assert service.account(first_id)["credits"] == 2
    with pytest.raises(ProductError, match="cannot be cancelled"):
        service.cancel(user_id=first_id, job_id=queued["id"])
    assert service.account(first_id)["credits"] == 2


def test_interrupted_job_has_one_automatic_recovery_then_refunds(tmp_path: Path) -> None:
    service = service_for(tmp_path, seed_demo_account=False, initial_credits=1)
    session = service.register("recover@example.com", "recovery password is long enough")
    user = service.session_user(session["session"])
    assert user is not None
    user_id = str(user["id"])
    upload = service.prepare_upload(
        user_id=user_id, filename="custom.png", content=png_bytes(color="black")
    )
    job = service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)
    claimed = service.claim_next_job()
    assert claimed is not None and claimed["status"] == "running"
    assert service.recover_interrupted_jobs() == 1
    recovered = service.get_job(user_id=user_id, job_id=job["id"])
    assert recovered["status"] == "queued"
    assert recovered["recovery_count"] == 1
    assert service.account(user_id)["credits"] == 0
    assert service.claim_next_job() is not None
    assert service.recover_interrupted_jobs() == 1
    exhausted = service.get_job(user_id=user_id, job_id=job["id"])
    assert exhausted["status"] == "failed"
    assert exhausted["error"]["code"] == "worker_recovery_exhausted"
    assert service.account(user_id)["credits"] == 1


def test_billing_event_is_idempotent_and_detects_conflicting_replay(tmp_path: Path) -> None:
    service = service_for(
        tmp_path,
        seed_demo_account=False,
        initial_credits=0,
        stripe_secret_key="sk_test_local",
        stripe_webhook_secret="whsec_local",
        stripe_price_id="price_local",
    )
    session = service.register("billing@example.com", "billing password is long enough")
    user = service.session_user(session["session"])
    assert user is not None
    user_id = str(user["id"])
    arguments = {
        "event_id": "evt_test_1",
        "event_type": "checkout.session.completed",
        "user_id": user_id,
        "credits": 100,
        "payload_sha256": "abc123",
    }
    assert service.apply_billing_event(**arguments)
    assert not service.apply_billing_event(**arguments)
    assert service.account(user_id)["credits"] == 100
    with pytest.raises(ProductError, match="did not match"):
        service.apply_billing_event(**{**arguments, "payload_sha256": "different"})
    assert service.account(user_id)["credits"] == 100


def test_http_flow_enforces_csrf_origin_headers_and_api_tenancy(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        short_password = client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "too-short"},
        )
        assert short_password.status_code == 422
        oversized = client.post(
            "/api/auth/login",
            headers={"Content-Length": str(22 * 1024 * 1024)},
            content=b"{}",
        )
        assert oversized.status_code == 413
        assert oversized.headers["content-security-policy"].startswith("default-src 'self'")
        assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
        unexpected = client.post(
            "/api/auth/register",
            json={
                "email": "extra@example.com",
                "password": "a sufficiently long password",
                "admin": True,
            },
        )
        assert unexpected.status_code == 422
        response = client.post("/api/auth/demo")
        assert response.status_code == 200
        assert client.get("/").headers["x-frame-options"] == "DENY"
        assert client.post("/api/uploads/demo").status_code == 403
        assert (
            client.post(
                "/api/uploads/demo",
                headers={**csrf_headers(client), "Origin": "https://attacker.example"},
            ).status_code
            == 403
        )

        upload = client.post("/api/uploads/demo", headers=csrf_headers(client))
        assert upload.status_code == 201
        job = client.post(
            "/api/jobs",
            headers=csrf_headers(client),
            json={"upload_id": upload.json()["id"], "page_index": 0},
        )
        assert job.status_code == 202
        assert app.state.service.process_one()
        job_id = job.json()["id"]
        result = client.get(f"/api/jobs/{job_id}").json()
        assert result["status"] == "review"
        assert client.get("/api/me").json()["demo_account"] is True
        assert (
            client.post(
                "/api/uploads",
                headers=csrf_headers(client),
                files={"file": ("private.png", png_bytes(), "image/png")},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/keys",
                headers=csrf_headers(client),
                json={"name": "blocked demo key"},
            ).status_code
            == 403
        )
        assert client.post("/api/billing/checkout", headers=csrf_headers(client)).status_code == 403
        assert client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 200

        registered = client.post(
            "/api/auth/register",
            json={"email": "integration@example.com", "password": "integration password is long"},
        )
        assert registered.status_code == 201
        customer_upload = client.post(
            "/api/uploads",
            headers=csrf_headers(client),
            files={"file": ("customer.png", png_bytes(color="green"), "image/png")},
        )
        assert customer_upload.status_code == 201
        customer_job = client.post(
            "/api/jobs",
            headers=csrf_headers(client),
            json={"upload_id": customer_upload.json()["id"], "page_index": 0},
        )
        assert customer_job.status_code == 202
        customer_job_id = customer_job.json()["id"]
        assert client.get(f"/api/jobs/{job_id}").status_code == 404
        key_response = client.post(
            "/api/keys",
            headers=csrf_headers(client),
            json={"name": "test integration"},
        )
        assert key_response.status_code == 201
        secret = key_response.json()["key"]
        api_result = client.get(
            f"/api/v1/extractions/{customer_job_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert api_result.status_code == 200
        assert api_result.json()["id"] == customer_job_id
        keys = client.get("/api/keys")
        assert keys.status_code == 200
        key_id = keys.json()["items"][0]["id"]
        assert "key_hash" not in keys.json()["items"][0]
        revoked = client.delete(f"/api/keys/{key_id}", headers=csrf_headers(client))
        assert revoked.status_code == 200
        assert revoked.json()["revoked_at"]
        assert (
            client.get(
                f"/api/v1/extractions/{customer_job_id}",
                headers={"Authorization": f"Bearer {secret}"},
            ).status_code
            == 401
        )


def test_api_submission_is_tenant_idempotent_and_conflicts_on_request_drift(
    tmp_path: Path,
) -> None:
    app = create_app(settings_for(tmp_path, seed_demo_account=False))
    with TestClient(app) as client:
        secret = register_and_create_api_key(client)
        headers = {
            "Authorization": f"Bearer {secret}",
            "Idempotency-Key": "extract-2026-0001",
        }
        source = png_bytes(color="green")
        first = client.post(
            "/api/v1/extractions?page_index=0",
            headers=headers,
            files={"file": ("chart.png", source, "image/png")},
        )
        replay = client.post(
            "/api/v1/extractions?page_index=0",
            headers=headers,
            files={"file": ("chart.png", source, "image/png")},
        )
        assert first.status_code == replay.status_code == 202
        assert first.json() == replay.json()
        assert client.get("/api/me").json()["credits"] == 2

        conflict = client.post(
            "/api/v1/extractions?page_index=0",
            headers=headers,
            files={"file": ("different.png", png_bytes(color="red"), "image/png")},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        missing = client.post(
            "/api/v1/extractions?page_index=0",
            headers={"Authorization": f"Bearer {secret}"},
            files={"file": ("chart.png", source, "image/png")},
        )
        assert missing.status_code == 422

        with app.state.service.database.connect() as conn:
            assert conn.execute("SELECT COUNT(*) AS count FROM uploads").fetchone()["count"] == 1
            assert conn.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"] == 1
            assert (
                conn.execute("SELECT COUNT(*) AS count FROM api_idempotency").fetchone()["count"]
                == 1
            )


def test_zero_credit_api_submission_leaves_no_rows_or_files(tmp_path: Path) -> None:
    app = create_app(
        settings_for(
            tmp_path,
            seed_demo_account=False,
            initial_credits=0,
        )
    )
    with TestClient(app) as client:
        secret = register_and_create_api_key(client, email="zero@example.com")
        rejected = client.post(
            "/api/v1/extractions",
            headers={
                "Authorization": f"Bearer {secret}",
                "Idempotency-Key": "zero-credit-0001",
            },
            files={"file": ("chart.png", png_bytes(), "image/png")},
        )
        assert rejected.status_code == 402
        with app.state.service.database.connect() as conn:
            assert conn.execute("SELECT COUNT(*) AS count FROM uploads").fetchone()["count"] == 0
            assert conn.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"] == 0
            assert (
                conn.execute("SELECT COUNT(*) AS count FROM api_idempotency").fetchone()["count"]
                == 0
            )
        assert app.state.service.storage.object_paths() == []


def test_streaming_body_limit_rejects_chunked_payload_before_json_parsing(
    tmp_path: Path,
) -> None:
    app = create_app(settings_for(tmp_path, seed_demo_account=False))

    def oversized_body() -> Iterator[bytes]:
        for _ in range(300):
            yield b"x" * 1024

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            headers={"Content-Type": "application/json"},
            content=oversized_body(),
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_test_mode_checkout_and_signed_webhook_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        settings_for(
            tmp_path,
            seed_demo_account=False,
            initial_credits=0,
            stripe_secret_key="sk_test_local",
            stripe_webhook_secret="whsec_local",
            stripe_price_id="price_local",
        )
    )
    checkout_arguments: dict[str, object] = {}

    def fake_checkout(**kwargs: object) -> SimpleNamespace:
        checkout_arguments.update(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.com/c/pay/cs_test_local")

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_checkout)
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"email": "buyer@example.com", "password": "buyer password is long enough"},
        )
        assert registered.status_code == 201
        account = client.get("/api/me").json()
        checkout = client.post("/api/billing/checkout", headers=csrf_headers(client))
        assert checkout.status_code == 201
        assert checkout.json()["url"].startswith("https://checkout.stripe.com/")
        assert checkout_arguments["payment_method_types"] == ["card"]

        monkeypatch.setattr(
            stripe.checkout.Session,
            "create",
            lambda **_: SimpleNamespace(url="https://attacker.example/cs_test_local"),
        )
        rejected_checkout = client.post("/api/billing/checkout", headers=csrf_headers(client))
        assert rejected_checkout.status_code == 502

        event = {
            "id": "evt_signed_test",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_status": "paid",
                    "client_reference_id": account["id"],
                    "metadata": {"user_id": account["id"], "credits": "100"},
                }
            },
        }
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *_: event)
        first = client.post(
            "/api/billing/webhook",
            content=b"signed-payload",
            headers={"Stripe-Signature": "test-signature"},
        )
        second = client.post(
            "/api/billing/webhook",
            content=b"signed-payload",
            headers={"Stripe-Signature": "test-signature"},
        )
        assert first.json() == {"received": True, "applied": True}
        assert second.json() == {"received": True, "applied": False}
        assert client.get("/api/me").json()["credits"] == 100


def test_rate_limit_excludes_health_checks(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path, rate_limit_per_minute=2))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 429
        assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("filename", ["index.html", "privacy.html", "terms.html"])
def test_static_pages_keep_basic_accessibility_contract(filename: str) -> None:
    soup = BeautifulSoup((STATIC_DIR / filename).read_text(encoding="utf-8"), "html.parser")
    ids = [tag["id"] for tag in soup.find_all(attrs={"id": True})]
    assert len(ids) == len(set(ids))
    assert soup.html is not None and soup.html.get("lang") == "en"
    assert soup.title is not None and soup.title.get_text(strip=True)
    assert soup.find("main") is not None
    assert soup.find("h1") is not None
    for image in soup.find_all("img"):
        assert image.get("alt") is not None
    for button in soup.find_all("button"):
        assert button.get("type") in {"button", "submit", "reset"}
    for field in soup.find_all(["input", "select"]):
        if field.get("type") == "hidden":
            continue
        field_id = field.get("id")
        wrapped = field.find_parent("label") is not None
        referenced = bool(field_id and soup.find("label", attrs={"for": field_id}))
        assert wrapped or referenced, f"Unlabelled field: {field}"
    for dialog in soup.find_all("dialog"):
        label_id = dialog.get("aria-labelledby")
        assert label_id and soup.find(id=label_id)
