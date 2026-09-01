"""Product use cases and invariants, independent from HTTP transport."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from unrender.product.config import Settings
from unrender.product.database import Database
from unrender.product.extractors import ExtractionError, Extractor
from unrender.product.security import (
    api_key,
    hash_password,
    normalize_email,
    random_token,
    token_hash,
    verify_password,
)
from unrender.product.storage import InvalidUpload, Storage
from unrender.schema.chart_schema import CHART_TYPES, ChartData
from unrender.schema.json_to_csv import chart_to_csv

_SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
_NUMERIC_CELL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat().replace("+00:00", "Z")


def public_job(row: sqlite3.Row, *, include_result: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": row["id"],
        "source_name": row["source_name"],
        "source_mime": row["source_mime"],
        "page_index": row["page_index"],
        "crop": json.loads(row["crop_json"]) if row["crop_json"] else None,
        "status": row["status"],
        "progress_stage": row["progress_stage"],
        "attempt": row["attempt"],
        "extractor": row["extractor"],
        "model_version": row["model_version"],
        "error": (
            {"code": row["error_code"], "message": row["error_message"]}
            if row["error_code"]
            else None
        ),
        "approved_at": row["approved_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_result:
        result["result"] = (
            json.loads(row["current_result_json"]) if row["current_result_json"] else None
        )
        result["original_result"] = (
            json.loads(row["original_result_json"]) if row["original_result_json"] else None
        )
    return result


class ProductError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ProductService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        storage: Storage,
        extractor: Extractor,
        static_dir: Path,
    ):
        self.settings = settings
        self.database = database
        self.storage = storage
        self.extractor = extractor
        self.static_dir = static_dir
        self._dummy_password_hash = hash_password("unrender timing defense password")

    def initialize(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.database.initialize()
        if self.settings.seed_demo_account:
            self._ensure_demo_user()
        self.recover_interrupted_jobs()

    def _id(self) -> str:
        return str(uuid.uuid4())

    def _audit(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str | None,
        event_type: str,
        job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO audit_events(id,user_id,job_id,event_type,details_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                self._id(),
                user_id,
                job_id,
                event_type,
                json.dumps(details or {}, separators=(",", ":")),
                timestamp(),
            ),
        )

    def _change_credits(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        delta: int,
        reason: str,
        idempotency_key: str,
    ) -> int:
        existing = conn.execute(
            "SELECT balance_after FROM credit_ledger WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return int(existing["balance_after"])
        user = conn.execute("SELECT credit_balance FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise ProductError("user_not_found", "Account no longer exists", 404)
        balance = int(user["credit_balance"]) + delta
        if balance < 0:
            raise ProductError("credits_required", "This extraction needs one chart credit", 402)
        conn.execute("UPDATE users SET credit_balance=? WHERE id=?", (balance, user_id))
        conn.execute(
            "INSERT INTO credit_ledger("
            "id,user_id,delta,balance_after,reason,idempotency_key,created_at"
            ") "
            "VALUES (?,?,?,?,?,?,?)",
            (self._id(), user_id, delta, balance, reason, idempotency_key, timestamp()),
        )
        return balance

    def _create_user(self, email: str, password: str, *, initial_credits: int) -> str:
        user_id = self._id()
        now = timestamp()
        try:
            normalized_email = normalize_email(email)
            password_hash = hash_password(password)
        except ValueError as exc:
            raise ProductError("invalid_account", str(exc), 422) from exc
        try:
            with self.database.transaction(immediate=True) as conn:
                conn.execute(
                    "INSERT INTO users(id,email,password_hash,credit_balance,created_at) "
                    "VALUES (?,?,?,?,?)",
                    (user_id, normalized_email, password_hash, 0, now),
                )
                if initial_credits:
                    self._change_credits(
                        conn,
                        user_id=user_id,
                        delta=initial_credits,
                        reason="welcome_allowance",
                        idempotency_key=f"welcome:{user_id}",
                    )
                self._audit(conn, user_id=user_id, event_type="account_created")
        except sqlite3.IntegrityError as exc:
            raise ProductError("email_in_use", "An account already uses that email", 409) from exc
        return user_id

    def register(self, email: str, password: str) -> dict[str, str]:
        if not self.settings.allow_registration:
            raise ProductError("registration_closed", "Account registration is closed", 403)
        user_id = self._create_user(email, password, initial_credits=self.settings.initial_credits)
        return self.create_session(user_id)

    def _ensure_demo_user(self) -> str:
        with self.database.connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE email='demo@unrender.local'").fetchone()
        if row:
            return str(row["id"])
        return self._create_user(
            "demo@unrender.local",
            random_token(24),
            initial_credits=max(self.settings.initial_credits, 3),
        )

    def authenticate(self, email: str, password: str) -> dict[str, str]:
        try:
            normalized = normalize_email(email)
        except ValueError:
            normalized = ""
        with self.database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (normalized,)).fetchone()
        candidate_hash = user["password_hash"] if user else self._dummy_password_hash
        password_matches = verify_password(password, candidate_hash)
        if not user or not password_matches:
            raise ProductError("invalid_credentials", "Email or password is incorrect", 401)
        return self.create_session(str(user["id"]))

    def demo_session(self) -> dict[str, str]:
        if not self.settings.seed_demo_account:
            raise ProductError("demo_disabled", "The sample account is disabled", 404)
        return self.create_session(self._ensure_demo_user())

    def _is_free_demo_fixture(self, source_sha256: str) -> bool:
        """The exact saved fixture is free because replay performs no paid inference."""
        source = self.static_dir / "demo" / "budget-quarter.webp"
        if self.settings.extractor_backend != "replay" or not source.exists():
            return False
        return hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256

    def create_session(self, user_id: str) -> dict[str, str]:
        session_token = random_token()
        csrf_token = random_token(24)
        now = utcnow()
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO sessions(id,user_id,token_hash,csrf_hash,expires_at,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    self._id(),
                    user_id,
                    token_hash(session_token),
                    token_hash(csrf_token),
                    timestamp(now + timedelta(hours=self.settings.session_ttl_hours)),
                    timestamp(now),
                ),
            )
            self._audit(conn, user_id=user_id, event_type="session_created")
        return {"session": session_token, "csrf": csrf_token}

    def session_user(self, session_token: str | None) -> sqlite3.Row | None:
        if not session_token:
            return None
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id "
                "WHERE sessions.token_hash=? AND sessions.expires_at>?",
                (token_hash(session_token), timestamp()),
            ).fetchone()

    def verify_csrf(self, session_token: str | None, csrf_token: str | None) -> bool:
        if not session_token or not csrf_token:
            return False
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT csrf_hash FROM sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(session_token), timestamp()),
            ).fetchone()
        return bool(row and row["csrf_hash"] == token_hash(csrf_token))

    def logout(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT user_id FROM sessions WHERE token_hash=?", (token_hash(session_token),)
            ).fetchone()
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(session_token),))
            if row:
                self._audit(conn, user_id=row["user_id"], event_type="session_revoked")

    def account(self, user_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise ProductError("user_not_found", "Account not found", 404)
        return {
            "id": user["id"],
            "email": user["email"],
            "credits": user["credit_balance"],
            "billing_configured": self.settings.billing_configured,
            "credit_pack_size": self.settings.credit_pack_size,
            "demo_mode": self.settings.extractor_backend == "replay",
            "api_docs_available": self.settings.environment != "production",
        }

    def prepare_upload(self, *, user_id: str, filename: str, content: bytes) -> dict[str, Any]:
        inspection = self.storage.inspect(content)
        upload_id = self._id()
        safe_name = Path(filename or "chart").name[:180]
        path = self.storage.save_upload(user_id=user_id, upload_id=upload_id, content=content)
        now = utcnow()
        try:
            with self.database.transaction() as conn:
                conn.execute(
                    "INSERT INTO uploads("
                    "id,user_id,original_name,mime_type,storage_path,byte_size,sha256,"
                    "page_count,created_at,expires_at"
                    ") "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        upload_id,
                        user_id,
                        safe_name,
                        inspection.mime_type,
                        str(path),
                        inspection.byte_size,
                        inspection.sha256,
                        inspection.page_count,
                        timestamp(now),
                        timestamp(now + timedelta(hours=self.settings.upload_ttl_hours)),
                    ),
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    event_type="upload_prepared",
                    details={"upload_id": upload_id, "mime": inspection.mime_type},
                )
        except Exception:
            self.storage.delete(path)
            raise
        return {
            "id": upload_id,
            "name": safe_name,
            "mime_type": inspection.mime_type,
            "page_count": inspection.page_count,
            "expires_at": timestamp(now + timedelta(hours=self.settings.upload_ttl_hours)),
        }

    def prepare_demo_upload(self, user_id: str) -> dict[str, Any]:
        source = self.static_dir / "demo" / "budget-quarter.webp"
        if not source.exists():
            raise ProductError("demo_fixture_missing", "The sample source is unavailable", 500)
        return self.prepare_upload(
            user_id=user_id,
            filename="budget-quarter-sample.webp",
            content=source.read_bytes(),
        )

    def upload(self, *, user_id: str, upload_id: str) -> sqlite3.Row:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM uploads WHERE id=? AND user_id=? AND expires_at>?",
                (upload_id, user_id, timestamp()),
            ).fetchone()
        if not row:
            raise ProductError("upload_not_found", "Upload expired or was not found", 404)
        return row

    def upload_preview(self, *, user_id: str, upload_id: str, page_index: int) -> bytes:
        row = self.upload(user_id=user_id, upload_id=upload_id)
        try:
            return self.storage.page_png(
                source=Path(row["storage_path"]),
                mime_type=row["mime_type"],
                page_index=page_index,
                max_edge=1600,
            )
        except InvalidUpload as exc:
            raise ProductError("invalid_page", str(exc), 400) from exc

    def create_job(
        self,
        *,
        user_id: str,
        upload_id: str,
        page_index: int,
        crop: dict[str, float] | None,
    ) -> dict[str, Any]:
        upload = self.upload(user_id=user_id, upload_id=upload_id)
        if not 0 <= page_index < int(upload["page_count"]):
            raise ProductError("invalid_page", "Selected page does not exist")
        if crop:
            try:
                values = {key: float(crop[key]) for key in ("x", "y", "width", "height")}
                if not (
                    0 <= values["x"] < 1
                    and 0 <= values["y"] < 1
                    and 0.05 <= values["width"] <= 1
                    and 0.05 <= values["height"] <= 1
                    and values["x"] + values["width"] <= 1.000001
                    and values["y"] + values["height"] <= 1.000001
                ):
                    raise ValueError
                crop = values
            except (KeyError, TypeError, ValueError) as exc:
                raise ProductError("invalid_crop", "Crop must stay within the source") from exc
        job_id = self._id()
        source_path = self.storage.copy_to_job(
            user_id=user_id,
            job_id=job_id,
            source=Path(upload["storage_path"]),
        )
        now = timestamp()
        credit_cost = 0 if self._is_free_demo_fixture(str(upload["sha256"])) else 1
        try:
            with self.database.transaction(immediate=True) as conn:
                if credit_cost:
                    self._change_credits(
                        conn,
                        user_id=user_id,
                        delta=-credit_cost,
                        reason="job_reserved",
                        idempotency_key=f"job:{job_id}:reserve:1",
                    )
                conn.execute(
                    "INSERT INTO jobs("
                    "id,user_id,upload_id,source_name,source_mime,source_path,"
                    "source_sha256,page_index,crop_json,status,progress_stage,"
                    "reservation_active,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,'queued','Waiting for extraction',?,?,?)",
                    (
                        job_id,
                        user_id,
                        upload_id,
                        upload["original_name"],
                        upload["mime_type"],
                        str(source_path),
                        upload["sha256"],
                        page_index,
                        json.dumps(crop, separators=(",", ":")) if crop else None,
                        credit_cost,
                        now,
                        now,
                    ),
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="job_queued",
                    details={
                        "page_index": page_index,
                        "cropped": bool(crop),
                        "credits_reserved": credit_cost,
                    },
                )
        except Exception:
            self.storage.delete(source_path)
            raise
        return self.get_job(user_id=user_id, job_id=job_id)

    def list_jobs(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        return [public_job(row, include_result=False) for row in rows]

    def _job_row(self, *, user_id: str, job_id: str) -> sqlite3.Row:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
        if not row:
            raise ProductError("job_not_found", "Extraction not found", 404)
        return row

    def get_job(self, *, user_id: str, job_id: str) -> dict[str, Any]:
        return public_job(self._job_row(user_id=user_id, job_id=job_id))

    def job_source(self, *, user_id: str, job_id: str) -> bytes:
        row = self._job_row(user_id=user_id, job_id=job_id)
        try:
            return self.storage.page_png(
                source=Path(row["source_path"]),
                mime_type=row["source_mime"],
                page_index=int(row["page_index"]),
                crop=json.loads(row["crop_json"]) if row["crop_json"] else None,
                max_edge=2200,
            )
        except InvalidUpload as exc:
            raise ProductError("source_unavailable", str(exc), 422) from exc

    def job_audit(self, *, user_id: str, job_id: str) -> list[dict[str, Any]]:
        self._job_row(user_id=user_id, job_id=job_id)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT event_type,details_json,created_at FROM audit_events "
                "WHERE job_id=? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        return [
            {
                "event": row["event_type"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_correction(
        self, *, user_id: str, job_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            chart = ChartData.model_validate(result)
            self._validate_product_chart(chart)
        except (TypeError, ValueError) as exc:
            raise ProductError("invalid_result", "The edited table is not valid", 422) from exc
        encoded = chart.model_dump_json()
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            if row["status"] not in {"review", "approved"}:
                raise ProductError("job_not_editable", "Wait for extraction before editing", 409)
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS value FROM result_versions WHERE job_id=?",
                (job_id,),
            ).fetchone()["value"]
            now = timestamp()
            conn.execute(
                "INSERT INTO result_versions("
                "id,job_id,user_id,version,source,chart_json,created_at"
                ") "
                "VALUES (?,?,?,?,?,?,?)",
                (self._id(), job_id, user_id, version, "correction", encoded, now),
            )
            conn.execute(
                "UPDATE jobs SET current_result_json=?,status='review',"
                "approved_at=NULL,updated_at=? "
                "WHERE id=?",
                (encoded, now, job_id),
            )
            self._audit(
                conn,
                user_id=user_id,
                job_id=job_id,
                event_type="result_corrected",
                details={"version": version},
            )
        return self.get_job(user_id=user_id, job_id=job_id)

    def _validate_product_chart(self, chart: ChartData) -> None:
        if chart.chart_type not in CHART_TYPES or not 1 <= len(chart.series) <= 50:
            raise ValueError("Unsupported chart structure")
        point_count = sum(len(series.points) for series in chart.series)
        if not 1 <= point_count <= 10_000:
            raise ValueError("Unsupported number of chart values")
        text_values = [
            chart.title,
            chart.x_axis.label,
            chart.x_axis.unit,
            chart.y_axis.label,
            chart.y_axis.unit,
            *(series.name for series in chart.series),
        ]
        if any(value is not None and len(value) > 500 for value in text_values):
            raise ValueError("Chart labels are too long")
        for series in chart.series:
            for point in series.points:
                if not math.isfinite(point.y):
                    raise ValueError("Chart values must be finite")
                if isinstance(point.x, str) and len(point.x) > 500:
                    raise ValueError("Chart labels are too long")
        if len(chart.model_dump_json()) > 1_000_000:
            raise ValueError("Chart result is too large")

    def approve(self, *, user_id: str, job_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT status,current_result_json FROM jobs WHERE id=? AND user_id=?",
                (job_id, user_id),
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            if row["status"] != "review" or not row["current_result_json"]:
                raise ProductError("job_not_approvable", "Review the result before approval", 409)
            now = timestamp()
            conn.execute(
                "UPDATE jobs SET status='approved',"
                "progress_stage='Approved for export',approved_at=?,updated_at=? "
                "WHERE id=?",
                (now, now, job_id),
            )
            self._audit(conn, user_id=user_id, job_id=job_id, event_type="result_approved")
        return self.get_job(user_id=user_id, job_id=job_id)

    def cancel(self, *, user_id: str, job_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            if row["status"] == "queued":
                now = timestamp()
                conn.execute(
                    "UPDATE jobs SET status='cancelled',progress_stage='Cancelled',"
                    "cancel_requested=1,reservation_active=0,updated_at=? WHERE id=?",
                    (now, job_id),
                )
                if row["reservation_active"]:
                    self._change_credits(
                        conn,
                        user_id=user_id,
                        delta=1,
                        reason="job_cancelled_refund",
                        idempotency_key=f"job:{job_id}:refund:{row['attempt']}",
                    )
                self._audit(conn, user_id=user_id, job_id=job_id, event_type="job_cancelled")
            elif row["status"] == "running":
                conn.execute(
                    "UPDATE jobs SET cancel_requested=1,"
                    "progress_stage='Cancellation requested',updated_at=? WHERE id=?",
                    (timestamp(), job_id),
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="job_cancellation_requested",
                )
            else:
                raise ProductError(
                    "job_not_cancellable", "This extraction cannot be cancelled", 409
                )
        return self.get_job(user_id=user_id, job_id=job_id)

    def reprocess(self, *, user_id: str, job_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            if row["status"] not in {"review", "approved", "failed", "cancelled"}:
                raise ProductError("job_busy", "This extraction is already in progress", 409)
            attempt = int(row["attempt"]) + 1
            credit_cost = 0 if self._is_free_demo_fixture(row["source_sha256"]) else 1
            if credit_cost:
                self._change_credits(
                    conn,
                    user_id=user_id,
                    delta=-credit_cost,
                    reason="job_reprocess_reserved",
                    idempotency_key=f"job:{job_id}:reserve:{attempt}",
                )
            now = timestamp()
            conn.execute(
                "UPDATE jobs SET status='queued',progress_stage='Waiting for extraction',"
                "attempt=?,cancel_requested=0,reservation_active=?,error_code=NULL,"
                "error_message=NULL,approved_at=NULL,updated_at=? WHERE id=?",
                (attempt, credit_cost, now, job_id),
            )
            self._audit(
                conn,
                user_id=user_id,
                job_id=job_id,
                event_type="job_requeued",
                details={"attempt": attempt, "credits_reserved": credit_cost},
            )
        return self.get_job(user_id=user_id, job_id=job_id)

    def apply_billing_event(
        self,
        *,
        event_id: str,
        event_type: str,
        user_id: str,
        credits: int,
        payload_sha256: str,
    ) -> bool:
        """Apply a verified Stripe event once, even after retries or reordering."""
        if not event_id or len(event_id) > 255 or not payload_sha256:
            raise ProductError("billing_event_invalid", "Billing event is incomplete", 422)
        if event_type != "checkout.session.completed":
            return False
        if credits != self.settings.credit_pack_size:
            raise ProductError("billing_event_invalid", "Credit pack does not match", 422)
        with self.database.transaction(immediate=True) as conn:
            existing = conn.execute(
                "SELECT event_type,payload_sha256 FROM billing_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if existing:
                if (
                    existing["event_type"] != event_type
                    or existing["payload_sha256"] != payload_sha256
                ):
                    raise ProductError(
                        "billing_event_conflict", "Billing event replay did not match", 409
                    )
                return False
            user = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise ProductError("billing_user_missing", "Billing account was not found", 422)
            conn.execute(
                "INSERT INTO billing_events(event_id,event_type,payload_sha256,processed_at) "
                "VALUES (?,?,?,?)",
                (event_id, event_type, payload_sha256, timestamp()),
            )
            self._change_credits(
                conn,
                user_id=user_id,
                delta=credits,
                reason="stripe_credit_pack",
                idempotency_key=f"stripe:{event_id}",
            )
            self._audit(
                conn,
                user_id=user_id,
                event_type="credits_purchased",
                details={"stripe_event_id": event_id, "credits": credits},
            )
        return True

    def export(self, *, user_id: str, job_id: str, output_format: str) -> tuple[bytes, str]:
        row = self._job_row(user_id=user_id, job_id=job_id)
        if row["status"] not in {"review", "approved"} or not row["current_result_json"]:
            raise ProductError("result_unavailable", "No reviewed result is available", 409)
        chart = ChartData.model_validate_json(row["current_result_json"])
        if output_format == "json":
            payload = chart.model_dump_json(indent=2).encode("utf-8")
            mime = "application/json"
        elif output_format == "csv":
            payload = self._safe_csv(chart).encode("utf-8")
            mime = "text/csv; charset=utf-8"
        elif output_format == "xlsx":
            payload = self._xlsx(chart, row)
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise ProductError("invalid_export", "Use csv, json, or xlsx")
        with self.database.transaction() as conn:
            self._audit(
                conn,
                user_id=user_id,
                job_id=job_id,
                event_type="result_exported",
                details={"format": output_format, "approved": row["status"] == "approved"},
            )
        return payload, mime

    @staticmethod
    def _spreadsheet_cell(value: str) -> str:
        stripped = value.lstrip()
        if not stripped or not stripped.startswith(_SPREADSHEET_FORMULA_PREFIXES):
            return value
        if _NUMERIC_CELL.fullmatch(stripped):
            return value
        return "'" + value

    def _safe_csv(self, chart: ChartData) -> str:
        source = io.StringIO(chart_to_csv(chart))
        output = io.StringIO()
        writer = csv.writer(output)
        for row in csv.reader(source):
            writer.writerow([self._spreadsheet_cell(value) for value in row])
        return output.getvalue()

    def _xlsx(self, chart: ChartData, row: sqlite3.Row) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Extracted data"
        for values in csv.reader(io.StringIO(self._safe_csv(chart))):
            sheet.append(values)
        meta = workbook.create_sheet("Audit")
        meta.append(["Field", "Value"])
        meta.append(["Source", self._spreadsheet_cell(row["source_name"])])
        meta.append(["Job ID", row["id"]])
        meta.append(["Model", self._spreadsheet_cell(row["model_version"] or "unknown")])
        meta.append(["Status", row["status"]])
        meta.append(["Approved at", row["approved_at"] or "Not approved"])
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    def delete_job(self, *, user_id: str, job_id: str) -> None:
        row = self._job_row(user_id=user_id, job_id=job_id)
        if row["status"] in {"queued", "running"}:
            raise ProductError("job_busy", "Cancel the extraction before deleting it", 409)
        with self.database.transaction(immediate=True) as conn:
            self._audit(
                conn,
                user_id=user_id,
                event_type="job_deleted",
                details={"deleted_job_id": job_id},
            )
            conn.execute("DELETE FROM jobs WHERE id=? AND user_id=?", (job_id, user_id))
        self.storage.delete(row["source_path"])

    def create_api_key(self, *, user_id: str, name: str) -> dict[str, str]:
        clean_name = name.strip()[:80]
        if not clean_name:
            raise ProductError("invalid_key_name", "Name the API key")
        secret, prefix, digest = api_key()
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO api_keys(id,user_id,name,prefix,key_hash,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (self._id(), user_id, clean_name, prefix, digest, timestamp()),
            )
            self._audit(
                conn,
                user_id=user_id,
                event_type="api_key_created",
                details={"name": clean_name, "prefix": prefix},
            )
        return {"key": secret, "prefix": prefix, "name": clean_name}

    def list_api_keys(self, *, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id,name,prefix,created_at,last_used_at,revoked_at FROM api_keys "
                "WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_api_key(self, *, user_id: str, key_id: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT id,name,prefix,created_at,last_used_at,revoked_at FROM api_keys "
                "WHERE id=? AND user_id=?",
                (key_id, user_id),
            ).fetchone()
            if not row:
                raise ProductError("api_key_not_found", "API key not found", 404)
            if row["revoked_at"] is None:
                revoked_at = timestamp()
                conn.execute(
                    "UPDATE api_keys SET revoked_at=? WHERE id=? AND user_id=?",
                    (revoked_at, key_id, user_id),
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    event_type="api_key_revoked",
                    details={"prefix": row["prefix"]},
                )
            else:
                revoked_at = row["revoked_at"]
        return {**dict(row), "revoked_at": revoked_at}

    def api_key_user(self, secret: str | None) -> sqlite3.Row | None:
        if not secret or not secret.startswith("unr_"):
            return None
        digest = token_hash(secret)
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT users.*,api_keys.id AS api_key_id FROM api_keys "
                "JOIN users ON users.id=api_keys.user_id "
                "WHERE api_keys.key_hash=? AND api_keys.revoked_at IS NULL",
                (digest,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE api_keys SET last_used_at=? WHERE id=?",
                    (timestamp(), row["api_key_id"]),
                )
        return row

    def claim_next_job(self) -> sqlite3.Row | None:
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            changed = conn.execute(
                "UPDATE jobs SET status='running',progress_stage='Preparing source',updated_at=? "
                "WHERE id=? AND status='queued'",
                (timestamp(), row["id"]),
            ).rowcount
            if changed != 1:
                return None
            self._audit(conn, user_id=row["user_id"], job_id=row["id"], event_type="job_started")
            return conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()

    def process_one(self) -> bool:
        row = self.claim_next_job()
        if not row:
            return False
        job_id = str(row["id"])
        try:
            if row["cancel_requested"]:
                self._finish_cancelled(row)
                return True
            with self.database.transaction() as conn:
                conn.execute(
                    "UPDATE jobs SET progress_stage='Reading chart',updated_at=? WHERE id=?",
                    (timestamp(), job_id),
                )
            image = self.storage.page_png(
                source=Path(row["source_path"]),
                mime_type=row["source_mime"],
                page_index=int(row["page_index"]),
                crop=json.loads(row["crop_json"]) if row["crop_json"] else None,
            )
            with self.database.transaction() as conn:
                conn.execute(
                    "UPDATE jobs SET progress_stage='Extracting table',updated_at=? WHERE id=?",
                    (timestamp(), job_id),
                )
            output = self.extractor.extract(image)
            self._validate_product_chart(output.chart)
            current = self._job_row(user_id=row["user_id"], job_id=job_id)
            if current["cancel_requested"]:
                self._finish_cancelled(current)
                return True
            encoded = output.chart.model_dump_json()
            now = timestamp()
            with self.database.transaction(immediate=True) as conn:
                version = conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 AS value "
                    "FROM result_versions WHERE job_id=?",
                    (job_id,),
                ).fetchone()["value"]
                source = "extraction" if version == 1 else "reprocess"
                conn.execute(
                    "INSERT INTO result_versions("
                    "id,job_id,user_id,version,source,chart_json,created_at"
                    ") "
                    "VALUES (?,?,?,?,?,?,?)",
                    (self._id(), job_id, row["user_id"], version, source, encoded, now),
                )
                conn.execute(
                    "UPDATE jobs SET status='review',progress_stage='Ready for review',"
                    "reservation_active=0,extractor=?,model_version=?,raw_result=?,"
                    "original_result_json=COALESCE(original_result_json,?),"
                    "current_result_json=?,error_code=NULL,error_message=NULL,updated_at=? "
                    "WHERE id=?",
                    (
                        output.extractor,
                        output.model_version,
                        output.raw[:1_000_000],
                        encoded,
                        encoded,
                        now,
                        job_id,
                    ),
                )
                self._audit(
                    conn,
                    user_id=row["user_id"],
                    job_id=job_id,
                    event_type="extraction_completed",
                    details={
                        "version": version,
                        "extractor": output.extractor,
                        "model": output.model_version,
                    },
                )
        except ExtractionError as exc:
            self._finish_failed(row, exc.code, str(exc))
        except (InvalidUpload, ValueError) as exc:
            self._finish_failed(row, "source_invalid", str(exc))
        except Exception:
            self._finish_failed(
                row,
                "internal_error",
                "The extraction failed unexpectedly. The reserved credit was returned.",
            )
        return True

    def _finish_failed(self, row: sqlite3.Row, code: str, message: str) -> None:
        with self.database.transaction(immediate=True) as conn:
            current = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            if not current or current["status"] not in {"running", "queued"}:
                return
            if current["reservation_active"]:
                self._change_credits(
                    conn,
                    user_id=current["user_id"],
                    delta=1,
                    reason="job_failed_refund",
                    idempotency_key=f"job:{current['id']}:refund:{current['attempt']}",
                )
            conn.execute(
                "UPDATE jobs SET status='failed',progress_stage='Needs attention',"
                "reservation_active=0,error_code=?,error_message=?,updated_at=? "
                "WHERE id=?",
                (code, message[:500], timestamp(), current["id"]),
            )
            self._audit(
                conn,
                user_id=current["user_id"],
                job_id=current["id"],
                event_type="extraction_failed",
                details={"code": code},
            )

    def _finish_cancelled(self, row: sqlite3.Row) -> None:
        with self.database.transaction(immediate=True) as conn:
            current = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            if not current or current["status"] not in {"running", "queued"}:
                return
            if current["reservation_active"]:
                self._change_credits(
                    conn,
                    user_id=current["user_id"],
                    delta=1,
                    reason="job_cancelled_refund",
                    idempotency_key=f"job:{current['id']}:refund:{current['attempt']}",
                )
            conn.execute(
                "UPDATE jobs SET status='cancelled',progress_stage='Cancelled',"
                "reservation_active=0,updated_at=? WHERE id=?",
                (timestamp(), current["id"]),
            )
            self._audit(
                conn,
                user_id=current["user_id"],
                job_id=current["id"],
                event_type="job_cancelled",
            )

    def recover_interrupted_jobs(self) -> int:
        with self.database.transaction(immediate=True) as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE status='running'").fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE jobs SET status='queued',"
                    "progress_stage='Recovered after restart',updated_at=? WHERE id=?",
                    (timestamp(), row["id"]),
                )
                self._audit(
                    conn,
                    user_id=row["user_id"],
                    job_id=row["id"],
                    event_type="job_recovered",
                )
        return len(rows)

    def cleanup_expired(self) -> dict[str, int]:
        now = timestamp()
        cutoff = timestamp(utcnow() - timedelta(days=self.settings.retention_days))
        upload_paths: list[str] = []
        job_paths: list[str] = []
        with self.database.transaction(immediate=True) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            expired_uploads = conn.execute(
                "SELECT storage_path FROM uploads WHERE expires_at<=?", (now,)
            ).fetchall()
            upload_paths = [row["storage_path"] for row in expired_uploads]
            conn.execute("DELETE FROM uploads WHERE expires_at<=?", (now,))
            expired_jobs = conn.execute(
                "SELECT source_path FROM jobs "
                "WHERE updated_at<? AND status NOT IN ('queued','running')",
                (cutoff,),
            ).fetchall()
            job_paths = [row["source_path"] for row in expired_jobs]
            conn.execute(
                "DELETE FROM jobs WHERE updated_at<? AND status NOT IN ('queued','running')",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM rate_limits WHERE window_start<?",
                (int(utcnow().timestamp()) - 3600,),
            )
        for path in upload_paths + job_paths:
            self.storage.delete(path)
        return {"uploads": len(upload_paths), "jobs": len(job_paths)}

    def rate_limit(self, bucket_key: str) -> bool:
        window = int(utcnow().timestamp()) // 60 * 60
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT request_count FROM rate_limits WHERE bucket_key=? AND window_start=?",
                (bucket_key, window),
            ).fetchone()
            count = int(row["request_count"]) + 1 if row else 1
            if row:
                conn.execute(
                    "UPDATE rate_limits SET request_count=? WHERE bucket_key=? AND window_start=?",
                    (count, bucket_key, window),
                )
            else:
                conn.execute(
                    "INSERT INTO rate_limits(bucket_key,window_start,request_count) VALUES (?,?,?)",
                    (bucket_key, window, count),
                )
        return count <= self.settings.rate_limit_per_minute
