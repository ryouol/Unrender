from __future__ import annotations

import csv
import io
import json
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
from unrender.product.extractors import ReplayExtractor
from unrender.product.security import hash_password, verify_password
from unrender.product.service import ProductError, ProductService
from unrender.product.storage import InvalidUpload, Storage
from unrender.product.web import CSRF_COOKIE, create_app

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


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE)}


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


def test_passwords_are_salted_and_verified() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


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
    assert sheet["B2"].value == "-9.2"


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


def test_interrupted_running_job_is_recovered_without_double_charge(tmp_path: Path) -> None:
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
    assert service.account(user_id)["credits"] == 0


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
        key_response = client.post(
            "/api/keys",
            headers=csrf_headers(client),
            json={"name": "test integration"},
        )
        assert key_response.status_code == 201
        secret = key_response.json()["key"]
        api_result = client.get(
            f"/api/v1/extractions/{job_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert api_result.status_code == 200
        assert api_result.json()["id"] == job_id
        keys = client.get("/api/keys")
        assert keys.status_code == 200
        key_id = keys.json()["items"][0]["id"]
        assert "key_hash" not in keys.json()["items"][0]
        revoked = client.delete(f"/api/keys/{key_id}", headers=csrf_headers(client))
        assert revoked.status_code == 200
        assert revoked.json()["revoked_at"]
        assert (
            client.get(
                f"/api/v1/extractions/{job_id}",
                headers={"Authorization": f"Bearer {secret}"},
            ).status_code
            == 401
        )


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
