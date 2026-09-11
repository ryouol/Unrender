"""Product use cases and invariants, independent from HTTP transport."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import math
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from openpyxl import Workbook

from unrender.product.config import Settings
from unrender.product.database import Database
from unrender.product.extractors import ExtractionError, Extractor
from unrender.product.security import (
    api_key,
    hash_password,
    normalize_email,
    password_needs_rehash,
    random_token,
    token_hash,
    verify_password,
)
from unrender.product.storage import InvalidUpload, StagedUpload, Storage
from unrender.schema.chart_schema import CHART_TYPES, ChartData

_SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
_NUMERIC_CELL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
logger = logging.getLogger("unrender.product")


@dataclass(frozen=True)
class WorkerClaim:
    job_id: str
    user_id: str
    attempt: int
    generation: int
    token: str
    owner: str
    row: sqlite3.Row

    def __getitem__(self, key: str) -> Any:
        return self.row[key]


@dataclass(frozen=True)
class StorageReservation:
    reservation_id: str
    owner_token: str


@dataclass(frozen=True)
class ReservedStagedUpload:
    staged: StagedUpload
    reservation: StorageReservation


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat().replace("+00:00", "Z")


def truncate_utf8(value: object, byte_limit: int) -> str:
    encoded = str(value).encode("utf-8")
    if len(encoded) <= byte_limit:
        return encoded.decode("utf-8")
    return encoded[:byte_limit].decode("utf-8", errors="ignore")


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
        "recovery_count": row["recovery_count"],
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

    def initialize(self, *, recover_jobs: bool = True) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings.data_dir.chmod(0o700)
        self.database.initialize()
        with self.database.startup_lock():
            # Never invent capacity for a pre-v7 or corrupted in-flight attempt. The
            # fenced pre-dispatch check fails it closed and refunds eligible spend;
            # a retry must pass the current transactional admission boundary.
            self.cleanup_storage_reservations()
            self._retire_legacy_shared_demo()
            self.reconcile_storage()
            self.drain_deletion_queue()
            if recover_jobs:
                self.recover_interrupted_jobs()
            with self.database.transaction(immediate=True) as conn:
                conn.execute(
                    "UPDATE startup_state SET last_reconciled_at=? WHERE singleton=1",
                    (timestamp(),),
                )

    def _id(self) -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _encode_cursor(created_at: str, row_id: str) -> str:
        payload = json.dumps([created_at, row_id], separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
        if cursor is None:
            return None
        try:
            padding = "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if (
                not isinstance(value, list)
                or len(value) != 2
                or not all(isinstance(item, str) and item for item in value)
            ):
                raise ValueError
            return value[0], value[1]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ProductError("invalid_cursor", "Pagination cursor is invalid", 422) from exc

    def _audit(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str | None,
        event_type: str,
        job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if user_id:
            cutoff = timestamp(utcnow() - timedelta(days=self.settings.audit_retention_days))
            self._rollup_audit_events(conn, user_id=user_id, before=cutoff)
            user_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM audit_events WHERE user_id=?", (user_id,)
                ).fetchone()["count"]
            )
            job_count = (
                int(
                    conn.execute(
                        "SELECT COUNT(*) AS count FROM audit_events WHERE job_id=?", (job_id,)
                    ).fetchone()["count"]
                )
                if job_id
                else 0
            )
            if user_count >= self.settings.max_audit_events_per_user:
                self._rollup_oldest_audit_events(
                    conn,
                    user_id=user_id,
                    count=user_count - self.settings.max_audit_events_per_user + 1,
                )
            if job_id and job_count >= self.settings.max_audit_events_per_job:
                self._rollup_oldest_audit_events(
                    conn,
                    user_id=user_id,
                    job_id=job_id,
                    count=job_count - self.settings.max_audit_events_per_job + 1,
                )
        self._insert_row(
            conn,
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
            user_id=user_id,
            mandatory=True,
        )

    def _rollup_audit_events(self, conn: sqlite3.Connection, *, user_id: str, before: str) -> None:
        rows = conn.execute(
            "SELECT id,job_id,event_type,created_at FROM audit_events "
            "WHERE user_id=? AND created_at<? ORDER BY created_at,id",
            (user_id, before),
        ).fetchall()
        self._aggregate_audit_rows(conn, user_id=user_id, rows=rows)

    def _rollup_oldest_audit_events(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        count: int,
        job_id: str | None = None,
    ) -> None:
        rows = conn.execute(
            "SELECT id,job_id,event_type,created_at FROM audit_events WHERE user_id=? "
            "AND (? IS NULL OR job_id=?) ORDER BY created_at,id LIMIT ?",
            (user_id, job_id, job_id, max(0, count)),
        ).fetchall()
        self._aggregate_audit_rows(conn, user_id=user_id, rows=rows)

    def _aggregate_audit_rows(
        self, conn: sqlite3.Connection, *, user_id: str, rows: list[sqlite3.Row]
    ) -> None:
        for row in rows:
            job_id = row["job_id"]
            conn.execute("DELETE FROM audit_events WHERE id=?", (row["id"],))
            self._insert_row(
                conn,
                "INSERT INTO audit_rollups("
                "user_id,job_id,job_scope,event_type,day,event_count,first_at,last_at"
                ") VALUES (?,?,?,?,'archive',1,?,?) "
                "ON CONFLICT(user_id,job_scope,event_type,day) "
                "DO UPDATE SET event_count=event_count+1,"
                "first_at=MIN(first_at,excluded.first_at),"
                "last_at=MAX(last_at,excluded.last_at)",
                (
                    user_id,
                    job_id,
                    str(job_id) if job_id is not None else "account",
                    row["event_type"],
                    row["created_at"],
                    row["created_at"],
                ),
                user_id=user_id,
                mandatory=True,
            )

    def _database_row_count(self, conn: sqlite3.Connection, user_id: str | None = None) -> int:
        tables = (
            "account_challenges",
            "google_identities",
            "oauth_attempts",
            "sessions",
            "uploads",
            "jobs",
            "result_versions",
            "audit_events",
            "audit_rollups",
            "credit_ledger",
            "api_keys",
            "api_idempotency",
            "provider_attempts",
            "pending_deletions",
            "storage_reservations",
        )
        total = 0
        for table in tables:
            if user_id is None:
                row = conn.execute(
                    f'SELECT COUNT(*) AS count FROM "{table}"'  # noqa: S608 -- closed tuple
                ).fetchone()
            else:
                row = conn.execute(
                    f'SELECT COUNT(*) AS count FROM "{table}" WHERE user_id=?',  # noqa: S608 -- closed internal tuple
                    (user_id,),
                ).fetchone()
            total += int(row["count"])
        if user_id is None:
            for table in ("users", "billing_events", "rate_limits"):
                total += int(
                    conn.execute(
                        f'SELECT COUNT(*) AS count FROM "{table}"'  # noqa: S608 -- closed tuple
                    ).fetchone()["count"]
                )
        return total

    def _future_terminal_rows(self, conn: sqlite3.Connection, user_id: str | None = None) -> int:
        if user_id is None:
            rows = conn.execute(
                "SELECT status,provider_dispatched,recovery_count FROM jobs"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status,provider_dispatched,recovery_count FROM jobs WHERE user_id=?",
                (user_id,),
            ).fetchall()
        total = 0
        for row in rows:
            remaining_recoveries = max(
                0, self.settings.max_recovery_attempts - int(row["recovery_count"])
            )
            if row["status"] == "queued":
                # claim audit + dispatch/result/terminal rows, plus one recovery audit and
                # another claim audit for each allowed pre-dispatch lease recovery.
                total += 5 + (2 * remaining_recoveries)
            elif row["status"] == "running" and not row["provider_dispatched"]:
                total += 4 + (2 * remaining_recoveries)
            elif row["status"] == "running":
                total += 2
        return total

    def _new_job_future_rows(self) -> int:
        return 5 + (2 * self.settings.max_recovery_attempts)

    def _admit_database_rows(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str | None,
        additional_rows: int = 1,
        mandatory: bool = False,
        new_future_rows: int = 0,
    ) -> None:
        if additional_rows < 0 or new_future_rows < 0:
            raise ValueError("Database admission deltas cannot be negative")
        global_rows = self._database_row_count(conn)
        if global_rows + additional_rows > self.settings.max_database_rows_global:
            raise ProductError(
                "service_capacity_reached",
                "The service has reached its retained-record safety limit",
                503,
            )
        if not mandatory and (
            global_rows
            + additional_rows
            + self.settings.mandatory_database_rows_global
            + self._future_terminal_rows(conn)
            + new_future_rows
            > self.settings.max_database_rows_global
        ):
            raise ProductError(
                "service_capacity_reached",
                "The service is preserving database capacity for in-flight terminal records",
                503,
            )
        if user_id is None:
            return
        user_rows = self._database_row_count(conn, user_id)
        if user_rows + additional_rows > self.settings.max_database_rows_per_user:
            raise ProductError(
                "database_quota_reached",
                "This workspace has reached its retained-record limit; delete old work and retry",
                429,
            )
        if not mandatory and (
            user_rows
            + additional_rows
            + self.settings.mandatory_database_rows_per_user
            + self._future_terminal_rows(conn, user_id)
            + new_future_rows
            > self.settings.max_database_rows_per_user
        ):
            raise ProductError(
                "database_quota_reached",
                "This workspace is preserving database capacity for in-flight terminal records",
                429,
            )

    def _insert_row(
        self,
        conn: sqlite3.Connection,
        sql: str,
        parameters: tuple[object, ...],
        *,
        user_id: str | None,
        mandatory: bool = False,
        new_future_rows: int = 0,
    ) -> sqlite3.Cursor:
        self._admit_database_rows(
            conn,
            user_id=user_id,
            mandatory=mandatory,
            new_future_rows=new_future_rows,
        )
        return conn.execute(sql, parameters)

    def _assert_database_capacity(self, conn: sqlite3.Connection, user_id: str) -> None:
        self._admit_database_rows(conn, user_id=user_id)

    def _retained_storage_bytes(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT "
            "COALESCE((SELECT SUM(byte_size) FROM uploads),0) + "
            "COALESCE((SELECT SUM(source_byte_size) FROM jobs),0) + "
            "COALESCE((SELECT SUM(byte_size) FROM pending_deletions),0) + "
            "COALESCE((SELECT SUM(byte_count) FROM storage_reservations),0) + "
            "COALESCE((SELECT SUM(retained_byte_reservation) FROM jobs),0) + "
            "COALESCE((SELECT SUM(LENGTH(CAST(chart_json AS BLOB))) FROM result_versions),0) + "
            "COALESCE((SELECT SUM(LENGTH(CAST(COALESCE(raw_result,'') AS BLOB)) + "
            "LENGTH(CAST(COALESCE(original_result_json,'') AS BLOB)) + "
            "LENGTH(CAST(COALESCE(current_result_json,'') AS BLOB))) FROM jobs),0) AS bytes"
        ).fetchone()
        database_bytes = 0
        for path in (
            self.settings.database_path,
            Path(f"{self.settings.database_path}-wal"),
            Path(f"{self.settings.database_path}-shm"),
        ):
            try:
                database_bytes += path.stat().st_size
            except OSError:
                continue
        return int(row["bytes"]) + database_bytes + self.settings.database_headroom_bytes

    def _unrealized_storage_reservations(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE((SELECT SUM(byte_count) FROM storage_reservations),0) + "
            "COALESCE((SELECT SUM(retained_byte_reservation) FROM jobs),0) AS bytes"
        ).fetchone()
        return int(row["bytes"])

    def _assert_retained_byte_capacity(
        self, conn: sqlite3.Connection, *, additional_bytes: int
    ) -> None:
        if additional_bytes < 0:
            raise ValueError("Storage admission delta cannot be negative")
        if (
            self._retained_storage_bytes(conn) + additional_bytes
            > self.settings.max_storage_bytes_global
        ):
            raise ProductError(
                "service_storage_capacity_reached",
                "The service has reached its global retained-byte limit",
                503,
            )
        free = shutil.disk_usage(self.settings.data_dir).free
        required_free = (
            self.settings.min_free_storage_bytes
            + self.settings.database_headroom_bytes
            + self._unrealized_storage_reservations(conn)
            + additional_bytes
        )
        if free < required_free:
            raise ProductError(
                "storage_free_space_guard",
                "The service is preserving its minimum disk and database headroom",
                503,
            )

    def _reserve_result_capacity(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        job_id: str | None,
        attempt: int,
    ) -> None:
        """Reserve the worst-case durable result expansion before any billable work."""

        if attempt <= 0:
            raise ValueError("Result-capacity reservations require a positive attempt")
        usage = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(CAST(chart_json AS BLOB))),0) AS history_bytes "
            "FROM result_versions WHERE user_id=?",
            (user_id,),
        ).fetchone()
        reserved = int(
            conn.execute(
                "SELECT COALESCE(SUM(result_reservation_bytes),0) AS bytes FROM jobs "
                "WHERE user_id=? AND (? IS NULL OR id<>?)",
                (user_id, job_id, job_id),
            ).fetchone()["bytes"]
        )
        if (
            int(usage["history_bytes"]) + reserved + self.settings.max_result_json_bytes
            > self.settings.max_history_bytes_per_user
        ):
            raise ProductError(
                "history_storage_quota_reached",
                "This workspace cannot reserve another maximum-size result version",
                413,
            )
        if job_id is not None:
            versions = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM result_versions WHERE job_id=? AND user_id=?",
                    (job_id, user_id),
                ).fetchone()["count"]
            )
            if versions >= self.settings.max_result_versions_per_job:
                raise ProductError(
                    "version_quota_reached",
                    "This extraction has reached its retained version limit",
                    429,
                )
        self._assert_retained_byte_capacity(
            conn, additional_bytes=self.settings.result_publication_reservation_bytes
        )

    @staticmethod
    def _idempotency_digest(namespace: str, key: str) -> str:
        if not _IDEMPOTENCY_KEY.fullmatch(key):
            raise ProductError(
                "idempotency_key_required",
                "Provide an Idempotency-Key of 8-128 letters, numbers, '.', '_', ':', or '-'",
                422,
            )
        return hashlib.sha256(f"{namespace}:{key}".encode()).hexdigest()

    def _create_idempotency_record(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        stored_key: str,
        request_sha256: str,
        now: datetime,
    ) -> None:
        created_at = timestamp(now)
        conn.execute(
            "UPDATE api_idempotency SET response_json=NULL,expired_at=expires_at "
            "WHERE user_id=? AND expires_at<=? AND expired_at IS NULL",
            (user_id, created_at),
        )
        conn.execute(
            "DELETE FROM api_idempotency WHERE user_id=? AND expired_at<?",
            (
                user_id,
                timestamp(now - timedelta(days=self.settings.idempotency_tombstone_days)),
            ),
        )
        count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM api_idempotency WHERE user_id=?", (user_id,)
            ).fetchone()["count"]
        )
        if count >= self.settings.max_idempotency_records_per_user:
            raise ProductError(
                "idempotency_quota_reached",
                "This account has reached its retained request-key limit",
                429,
            )
        self._insert_row(
            conn,
            "INSERT INTO api_idempotency("
            "user_id,idempotency_key,request_sha256,response_json,created_at,completed_at,"
            "expires_at,expired_at) VALUES (?,?,?,NULL,?,NULL,?,NULL)",
            (
                user_id,
                stored_key,
                request_sha256,
                created_at,
                timestamp(now + timedelta(hours=self.settings.idempotency_ttl_hours)),
            ),
            user_id=user_id,
        )

    def _reserve_storage_bytes(
        self,
        *,
        user_id: str,
        byte_count: int,
        kind: str,
        storage_path: Path | None = None,
    ) -> StorageReservation:
        reservation_id = self._id()
        owner_token = random_token(24)
        now = utcnow()
        with self.database.transaction(immediate=True) as conn:
            self._assert_retained_byte_capacity(conn, additional_bytes=byte_count)
            self._insert_row(
                conn,
                "INSERT INTO storage_reservations("
                "id,owner_token,user_id,kind,byte_count,storage_path,created_at,expires_at"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    reservation_id,
                    owner_token,
                    user_id,
                    kind,
                    byte_count,
                    str(storage_path) if storage_path is not None else None,
                    timestamp(now),
                    timestamp(
                        now + timedelta(seconds=self.settings.storage_reservation_ttl_seconds)
                    ),
                ),
                user_id=user_id,
            )
        return StorageReservation(reservation_id=reservation_id, owner_token=owner_token)

    def _resize_storage_reservation(
        self,
        *,
        user_id: str,
        reservation: StorageReservation,
        byte_count: int,
        kind: str,
        storage_path: Path | None = None,
    ) -> None:
        now = utcnow()
        current_time = timestamp(now)
        renewed_expiry = timestamp(
            now + timedelta(seconds=self.settings.storage_reservation_ttl_seconds)
        )
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT byte_count FROM storage_reservations WHERE id=? AND owner_token=? "
                "AND user_id=? AND expires_at>?",
                (
                    reservation.reservation_id,
                    reservation.owner_token,
                    user_id,
                    current_time,
                ),
            ).fetchone()
            if not row:
                raise ProductError(
                    "storage_reservation_lost",
                    "The durable storage reservation expired before publication",
                    503,
                )
            delta = byte_count - int(row["byte_count"])
            if delta > 0:
                self._assert_retained_byte_capacity(conn, additional_bytes=delta)
            changed = conn.execute(
                "UPDATE storage_reservations SET kind=?,byte_count=?,storage_path=?,expires_at=? "
                "WHERE id=? AND owner_token=? AND user_id=? AND expires_at>?",
                (
                    kind,
                    byte_count,
                    str(storage_path) if storage_path is not None else None,
                    renewed_expiry,
                    reservation.reservation_id,
                    reservation.owner_token,
                    user_id,
                    current_time,
                ),
            ).rowcount
            if changed != 1:
                raise ProductError(
                    "storage_reservation_lost",
                    "The durable storage reservation expired before publication",
                    503,
                )

    def _consume_storage_reservation(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        reservation: StorageReservation,
        kind: str,
        byte_count: int,
        storage_path: Path,
    ) -> None:
        changed = conn.execute(
            "DELETE FROM storage_reservations WHERE id=? AND owner_token=? AND user_id=? "
            "AND kind=? AND byte_count=? AND storage_path=? AND expires_at>?",
            (
                reservation.reservation_id,
                reservation.owner_token,
                user_id,
                kind,
                byte_count,
                str(storage_path),
                timestamp(),
            ),
        ).rowcount
        if changed != 1:
            raise ProductError(
                "storage_reservation_lost",
                "The durable storage reservation expired before publication",
                503,
            )

    def _release_storage_reservation(
        self, *, user_id: str, reservation: StorageReservation
    ) -> None:
        with self.database.transaction(immediate=True) as conn:
            self._drop_storage_reservation(conn, user_id=user_id, reservation=reservation)

    @staticmethod
    def _drop_storage_reservation(
        conn: sqlite3.Connection,
        *,
        user_id: str,
        reservation: StorageReservation,
    ) -> bool:
        return (
            conn.execute(
                "DELETE FROM storage_reservations WHERE id=? AND owner_token=? AND user_id=?",
                (reservation.reservation_id, reservation.owner_token, user_id),
            ).rowcount
            == 1
        )

    def _stage_upload_with_reservation(
        self, *, user_id: str, source: BinaryIO
    ) -> ReservedStagedUpload:
        staging_path = self.storage.root / "staging" / f"upload-{uuid.uuid4().hex}.tmp"
        reservation = self._reserve_storage_bytes(
            user_id=user_id,
            byte_count=self.settings.max_upload_bytes,
            kind="staging",
            storage_path=staging_path,
        )
        try:
            with self.database.operational_lock():
                staged = self.storage.stage_upload(source, destination=staging_path)
            self._resize_storage_reservation(
                user_id=user_id,
                reservation=reservation,
                byte_count=staged.inspection.byte_size,
                kind="staging",
                storage_path=staged.path,
            )
            return ReservedStagedUpload(staged=staged, reservation=reservation)
        except Exception:
            try:
                with self.database.operational_lock():
                    self.storage.delete(staging_path)
            except Exception:
                with self.database.transaction(immediate=True) as conn:
                    self._queue_deletion(
                        conn,
                        staging_path,
                        "failed_staging_cleanup",
                        user_id=user_id,
                        byte_size=self.settings.max_upload_bytes,
                    )
            finally:
                self._release_storage_reservation(user_id=user_id, reservation=reservation)
            raise

    def cleanup_storage_reservations(self) -> int:
        now = timestamp()
        paths: list[str] = []
        with self.database.transaction(immediate=True) as conn:
            expired = conn.execute(
                "SELECT id,user_id,storage_path,byte_count FROM storage_reservations "
                "WHERE expires_at<=?",
                (now,),
            ).fetchall()
            for row in expired:
                if row["storage_path"]:
                    path = str(row["storage_path"])
                    paths.append(path)
                    self._queue_deletion(
                        conn,
                        path,
                        "expired_storage_reservation",
                        user_id=str(row["user_id"]) if row["user_id"] else None,
                        byte_size=int(row["byte_count"]),
                    )
                conn.execute("DELETE FROM storage_reservations WHERE id=?", (row["id"],))
        if paths:
            self.drain_deletion_queue(paths=paths)
        return len(expired)

    def _change_credits(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        delta: int,
        reason: str,
        idempotency_key: str,
        mandatory: bool = False,
    ) -> int:
        existing = conn.execute(
            "SELECT balance_after FROM credit_ledger WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return int(existing["balance_after"])
        ledger_count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM credit_ledger WHERE user_id=?", (user_id,)
            ).fetchone()["count"]
        )
        refundable = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE user_id=? "
                "AND reservation_active=1 AND provider_dispatched=0",
                (user_id,),
            ).fetchone()["count"]
        )
        if ledger_count >= self.settings.max_credit_ledger_records_per_user or (
            not mandatory
            and ledger_count + 1 + refundable > self.settings.max_credit_ledger_records_per_user
        ):
            raise ProductError(
                "credit_ledger_capacity_reached",
                "Credit activity is paused until an operator archives this account ledger",
                503,
            )
        user = conn.execute("SELECT credit_balance FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise ProductError("user_not_found", "Account no longer exists", 404)
        balance = int(user["credit_balance"]) + delta
        if balance < 0:
            raise ProductError("credits_required", "This extraction needs one chart credit", 402)
        conn.execute("UPDATE users SET credit_balance=? WHERE id=?", (balance, user_id))
        self._insert_row(
            conn,
            "INSERT INTO credit_ledger("
            "id,user_id,delta,balance_after,reason,idempotency_key,created_at"
            ") "
            "VALUES (?,?,?,?,?,?,?)",
            (self._id(), user_id, delta, balance, reason, idempotency_key, timestamp()),
            user_id=user_id,
            mandatory=mandatory,
        )
        return balance

    def _create_user(
        self,
        email: str,
        password: str,
        *,
        initial_credits: int,
        credit_reason: str = "welcome_allowance",
        account_kind: str = "customer",
        account_active: bool = True,
        activation_token: str | None = None,
        publish_activation: Callable[[], None] | None = None,
    ) -> str:
        user_id = self._id()
        now = timestamp()
        try:
            normalized_email = normalize_email(email)
            password_hash = hash_password(password)
        except ValueError as exc:
            raise ProductError("invalid_account", str(exc), 422) from exc
        try:
            with self.database.transaction(immediate=True) as conn:
                if self._database_row_count(conn) >= self.settings.max_database_rows_global:
                    raise ProductError(
                        "service_capacity_reached",
                        "The service has reached its retained-record safety limit",
                        503,
                    )
                self._insert_row(
                    conn,
                    "INSERT INTO users("
                    "id,email,password_hash,account_kind,credit_balance,created_at,"
                    "account_active,email_verified"
                    ") "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        normalized_email,
                        password_hash,
                        account_kind,
                        0,
                        now,
                        account_active,
                        False,
                    ),
                    user_id=None,
                )
                if initial_credits:
                    self._change_credits(
                        conn,
                        user_id=user_id,
                        delta=initial_credits,
                        reason=credit_reason,
                        idempotency_key=f"welcome:{user_id}",
                    )
                self._audit(conn, user_id=user_id, event_type="account_created")
                if activation_token:
                    self._store_account_challenge(conn, user_id, "reset", activation_token)
                    if publish_activation:
                        publish_activation()
        except sqlite3.IntegrityError as exc:
            raise ProductError("email_in_use", "An account already uses that email", 409) from exc
        return user_id

    def register(self, email: str, password: str) -> dict[str, str]:
        if not self.settings.allow_registration:
            raise ProductError("registration_closed", "Account registration is closed", 403)
        user_id = self._create_user(
            email,
            password,
            initial_credits=self.settings.initial_credits,
            account_active=not self.settings.require_email_verification,
        )
        if self.settings.require_email_verification:
            # Transport sends the challenge after releasing expensive KDF admission.
            return {"verification_required": "true"}
        return self.create_session(user_id)

    def request_account_email(self, email: str, *, purpose: str) -> None:
        from unrender.product.mail import send_account_email

        if purpose not in {"verify", "reset"}:
            raise ValueError("Unsupported email purpose")
        if not self.settings.email_configured:
            raise ProductError("email_unavailable", "Account email is not configured", 503)
        try:
            normalized = normalize_email(email)
        except ValueError:
            return
        # Limit by recipient as well as the existing client-IP admission bucket.
        if not self.rate_limit("account-email:" + token_hash(normalized), limit=2):
            return
        token = random_token()
        with self.database.transaction(immediate=True) as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE email=? AND account_kind='customer'", (normalized,)
            ).fetchone()
            if not user or (purpose == "verify" and user["email_verified"]):
                return
            if purpose == "reset" and user["account_active"] and not user["email_verified"]:
                # Knowing a claimed mailbox must not recover a password-only workspace.
                return
            now = timestamp()
            conn.execute("DELETE FROM account_challenges WHERE expires_at<=?", (now,))
            count = conn.execute(
                "SELECT COUNT(*) FROM account_challenges WHERE user_id=? AND purpose=?",
                (user["id"], purpose),
            ).fetchone()[0]
            if count >= 5:
                return
            self._store_account_challenge(conn, str(user["id"]), purpose, token, email_proof=True)
        # Preserve other delivered links across failed or reordered delivery.
        if send_account_email(self.settings, normalized, purpose, token) is False:
            with self.database.transaction(immediate=True) as conn:
                conn.execute(
                    "DELETE FROM account_challenges WHERE token_hash=?", (token_hash(token),)
                )

    def _store_account_challenge(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        purpose: str,
        token: str,
        *,
        email_proof: bool = False,
    ) -> None:
        self._insert_row(
            conn,
            "INSERT INTO account_challenges("
            "id,user_id,purpose,token_hash,expires_at,created_at,email_proof) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                self._id(),
                user_id,
                purpose,
                token_hash(token),
                timestamp(utcnow() + timedelta(minutes=30)),
                timestamp(),
                email_proof,
            ),
            user_id=user_id,
        )

    def invite_user(
        self, email: str, *, credits: int = 0, publish: Callable[[str], None] | None = None
    ) -> str:
        """Operator-vetted signup without transporting a password or sending email."""
        if not 0 <= credits <= 1_000_000:
            raise ProductError("invalid_credits", "Credits must be between 0 and 1,000,000", 422)
        token = random_token()
        link = f"{self.settings.base_url}/account?mode=invite#account=reset&token={token}"
        self._create_user(
            email,
            random_token(),
            initial_credits=credits,
            credit_reason="operator_grant",
            account_active=False,
            activation_token=token,
            publish_activation=(lambda: publish(link)) if publish else None,
        )
        return link

    def operator_account_link(
        self, email: str, *, publish: Callable[[str], None] | None = None
    ) -> str:
        """Replace account setup/recovery links after the operator checks identity."""
        try:
            normalized = normalize_email(email)
        except ValueError as exc:
            raise ProductError("invalid_account", str(exc), 422) from exc
        token = random_token()
        with self.database.transaction(immediate=True) as conn:
            user = conn.execute(
                "SELECT id,account_active FROM users WHERE email=? AND account_kind='customer'",
                (normalized,),
            ).fetchone()
            if not user:
                raise ProductError("user_not_found", "Account not found", 404)
            conn.execute("DELETE FROM account_challenges WHERE user_id=?", (user["id"],))
            self._store_account_challenge(conn, str(user["id"]), "reset", token)
            self._audit(conn, user_id=user["id"], event_type="operator_account_link_issued")
            mode = "" if user["account_active"] else "?mode=invite"
            link = f"{self.settings.base_url}/account{mode}#account=reset&token={token}"
            if publish:
                publish(link)
        return link

    def complete_account_email(self, token: str, *, purpose: str, password: str = "") -> None:
        if purpose not in {"verify", "reset"}:
            raise ValueError("Unsupported email purpose")
        challenge_hash = token_hash(token)
        with self.database.connect() as conn:
            candidate = conn.execute(
                "SELECT users.password_hash,users.session_generation,users.account_active,"
                "users.email_verified,account_challenges.email_proof FROM account_challenges "
                "JOIN users ON users.id=account_challenges.user_id "
                "WHERE account_challenges.token_hash=? AND account_challenges.purpose=? "
                "AND account_challenges.expires_at>? AND users.account_kind='customer'",
                (challenge_hash, purpose, timestamp()),
            ).fetchone()
        if not candidate:
            raise ProductError(
                "invalid_account_link",
                "This link expired or was already used. Request a new one.",
                400,
            )
        if (
            purpose == "reset"
            and candidate["email_proof"]
            and candidate["account_active"]
            and not candidate["email_verified"]
        ):
            raise ProductError(
                "invalid_account_link", "Verify your email before using recovery", 400
            )
        replacement = None
        if purpose == "reset":
            try:
                replacement = hash_password(password)
            except ValueError as exc:
                raise ProductError("invalid_password", str(exc), 422) from exc
        if purpose == "verify" and not verify_password(password, candidate["password_hash"]):
            raise ProductError(
                "invalid_credentials", "Enter the password you chose when signing up", 400
            )
        with self.database.transaction(immediate=True) as conn:
            user = conn.execute(
                "SELECT users.*,account_challenges.email_proof FROM account_challenges "
                "JOIN users ON users.id=account_challenges.user_id "
                "WHERE account_challenges.token_hash=? AND account_challenges.purpose=? "
                "AND account_challenges.expires_at>? AND users.account_kind='customer'",
                (challenge_hash, purpose, timestamp()),
            ).fetchone()
            if not user:
                raise ProductError(
                    "invalid_account_link",
                    "This link expired or was already used. Request a new one.",
                    400,
                )
            if (
                purpose == "reset"
                and user["email_proof"]
                and user["account_active"]
                and not user["email_verified"]
            ):
                raise ProductError(
                    "invalid_account_link", "Verify your email before using recovery", 400
                )
            if purpose == "verify":
                if (
                    user["password_hash"] != candidate["password_hash"]
                    or user["session_generation"] != candidate["session_generation"]
                ):
                    raise ProductError(
                        "invalid_account_link",
                        "Account credentials changed. Request a new link.",
                        400,
                    )
                conn.execute(
                    "UPDATE users SET email_verified=1,account_active=1 WHERE id=?", (user["id"],)
                )
                conn.execute(
                    "DELETE FROM account_challenges WHERE user_id=? AND purpose='verify'",
                    (user["id"],),
                )
            else:
                conn.execute(
                    "UPDATE users SET password_hash=?,password_enabled=1,account_active=1,"
                    "email_verified=MAX(email_verified,?),"
                    "session_generation=session_generation+1 WHERE id=?",
                    (replacement, user["email_proof"], user["id"]),
                )
                conn.execute("DELETE FROM account_challenges WHERE user_id=?", (user["id"],))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
                conn.execute(
                    "UPDATE api_keys SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (timestamp(), user["id"]),
                )
            self._audit(
                conn,
                user_id=user["id"],
                event_type="email_verified" if purpose == "verify" else "password_reset",
            )

    def provision_user(self, email: str, password: str, *, credits: int = 0) -> str:
        """Create a controlled-beta account from trusted operator tooling."""
        if not 0 <= credits <= 1_000_000:
            raise ProductError("invalid_credits", "Credits must be between 0 and 1,000,000", 422)
        return self._create_user(
            email,
            password,
            initial_credits=credits,
            credit_reason="operator_grant",
        )

    def grant_credits(self, email: str, *, credits: int, reference: str) -> None:
        if not 1 <= credits <= 1000 or not 1 <= len(reference) <= 128:
            raise ProductError(
                "invalid_grant", "Use 1–1000 credits and a unique reference (1–128 characters)", 422
            )
        try:
            normalized = normalize_email(email)
        except ValueError as exc:
            raise ProductError("invalid_account", str(exc), 422) from exc
        with self.database.transaction(immediate=True) as conn:
            user = conn.execute(
                "SELECT id FROM users WHERE email=? AND account_kind='customer' "
                "AND account_active=1",
                (normalized,),
            ).fetchone()
            if not user:
                raise ProductError("user_not_found", "Active account not found", 404)
            self._change_credits(
                conn,
                user_id=user["id"],
                delta=credits,
                reason="operator_grant",
                idempotency_key=f"grant:{user['id']}:{reference}",
            )

    def authenticate(self, email: str, password: str) -> dict[str, str]:
        try:
            normalized = normalize_email(email)
        except ValueError:
            normalized = ""
        with self.database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (normalized,)).fetchone()
        candidate_hash = (
            user["password_hash"]
            if user and user["password_enabled"]
            else self._dummy_password_hash
        )
        password_matches = verify_password(password, candidate_hash)
        if not user or not user["password_enabled"] or not password_matches:
            raise ProductError("invalid_credentials", "Email or password is incorrect", 401)
        expected_hash = str(user["password_hash"])
        if password_needs_rehash(expected_hash):
            replacement = hash_password(password)
            with self.database.transaction(immediate=True) as conn:
                changed = conn.execute(
                    "UPDATE users SET password_hash=? WHERE id=? AND password_hash=?",
                    (replacement, user["id"], user["password_hash"]),
                ).rowcount
                current = conn.execute(
                    "SELECT password_hash,session_generation FROM users WHERE id=?",
                    (user["id"],),
                ).fetchone()
            if changed:
                expected_hash = replacement
            else:
                # Another login may have upgraded the same password. A reset must
                # still invalidate this in-flight authentication attempt.
                if (
                    not current
                    or current["session_generation"] != user["session_generation"]
                    or not verify_password(password, current["password_hash"])
                ):
                    raise ProductError("invalid_credentials", "Credentials changed", 401)
                expected_hash = str(current["password_hash"])
        return self.create_session(str(user["id"]), expected_password_hash=expected_hash)

    def reauthenticate_password(self, *, user_id: str, session_token: str, password: str) -> None:
        with self.database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        candidate = (
            user["password_hash"]
            if user and user["password_enabled"]
            else self._dummy_password_hash
        )
        matches = verify_password(password, candidate)
        if not user or not user["password_enabled"] or not matches:
            raise ProductError("invalid_credentials", "Password is incorrect", 401)
        with self.database.transaction(immediate=True) as conn:
            changed = conn.execute(
                "UPDATE sessions SET reauthenticated_at=? WHERE token_hash=? AND user_id=? "
                "AND expires_at>? AND session_generation=? AND EXISTS(SELECT 1 FROM users "
                "WHERE id=? AND password_hash=? AND password_enabled=1 AND session_generation=?)",
                (
                    timestamp(),
                    token_hash(session_token),
                    user_id,
                    timestamp(),
                    user["session_generation"],
                    user_id,
                    candidate,
                    user["session_generation"],
                ),
            ).rowcount
            if not changed:
                raise ProductError("invalid_credentials", "Sign in again before continuing", 401)

    @staticmethod
    def require_recent_auth(conn: sqlite3.Connection, *, user_id: str, session_token: str) -> None:
        recent = timestamp(utcnow() - timedelta(minutes=5))
        valid = conn.execute(
            "SELECT 1 FROM sessions JOIN users ON users.id=sessions.user_id "
            "WHERE sessions.token_hash=? AND users.id=? AND users.account_active=1 "
            "AND sessions.expires_at>? AND sessions.reauthenticated_at>=? "
            "AND sessions.session_generation=users.session_generation",
            (token_hash(session_token), user_id, timestamp(), recent),
        ).fetchone()
        if not valid:
            raise ProductError(
                "reauthentication_required", "Confirm your identity to continue", 403
            )

    def demo_session(self) -> dict[str, str]:
        if not self.settings.seed_demo_account:
            raise ProductError("demo_disabled", "The sample account is disabled", 404)
        user_id = self._create_user(
            f"demo+{uuid.uuid4().hex}@unrender.local",
            random_token(24),
            initial_credits=0,
            account_kind="demo",
        )
        try:
            return self.create_session(user_id)
        except Exception:
            with self.database.transaction(immediate=True) as conn:
                conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            raise

    def is_demo_user(self, user_id: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute("SELECT account_kind FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise ProductError("user_not_found", "Account not found", 404)
        return row["account_kind"] == "demo"

    def require_customer_account(self, user_id: str, capability: str) -> None:
        if self.is_demo_user(user_id):
            raise ProductError(
                "demo_read_only",
                f"The isolated sample session cannot use {capability}",
                403,
            )

    def _is_free_demo_fixture(self, source_sha256: str) -> bool:
        """The exact saved fixture is free because replay performs no paid inference."""
        source = self.static_dir / "demo" / "budget-quarter.webp"
        if self.settings.extractor_backend != "replay" or not source.exists():
            return False
        return hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256

    def create_session(
        self, user_id: str, *, expected_password_hash: str | None = None
    ) -> dict[str, str]:
        session_token = random_token()
        csrf_token = random_token(24)
        now = utcnow()
        with self.database.transaction(immediate=True) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (timestamp(now),))
            self._assert_database_capacity(conn, user_id)
            user = conn.execute(
                "SELECT session_generation,account_active,password_hash FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not user:
                raise ProductError("user_not_found", "Account not found", 404)
            if (
                expected_password_hash is not None
                and user["password_hash"] != expected_password_hash
            ):
                raise ProductError(
                    "invalid_credentials", "Credentials changed. Sign in again.", 401
                )
            if not user["account_active"]:
                raise ProductError(
                    "account_not_active", "Complete account setup before signing in", 403
                )
            sessions = conn.execute(
                "SELECT id FROM sessions WHERE user_id=? ORDER BY created_at DESC,id DESC",
                (user_id,),
            ).fetchall()
            for stale in sessions[self.settings.max_sessions_per_user - 1 :]:
                conn.execute("DELETE FROM sessions WHERE id=?", (stale["id"],))
            self._insert_row(
                conn,
                "INSERT INTO sessions("
                "id,user_id,token_hash,csrf_hash,session_generation,expires_at,created_at"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    self._id(),
                    user_id,
                    token_hash(session_token),
                    token_hash(csrf_token),
                    int(user["session_generation"]),
                    timestamp(now + timedelta(hours=self.settings.session_ttl_hours)),
                    timestamp(now),
                ),
                user_id=user_id,
            )
            self._audit(conn, user_id=user_id, event_type="session_created")
        return {"session": session_token, "csrf": csrf_token}

    def session_user(self, session_token: str | None) -> sqlite3.Row | None:
        if not session_token:
            return None
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id "
                "WHERE sessions.token_hash=? AND sessions.expires_at>? "
                "AND sessions.session_generation=users.session_generation",
                (token_hash(session_token), timestamp()),
            ).fetchone()

    def verify_csrf(self, session_token: str | None, csrf_token: str | None) -> bool:
        if not session_token or not csrf_token:
            return False
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT sessions.csrf_hash FROM sessions "
                "JOIN users ON users.id=sessions.user_id "
                "WHERE sessions.token_hash=? AND sessions.expires_at>? "
                "AND sessions.session_generation=users.session_generation",
                (token_hash(session_token), timestamp()),
            ).fetchone()
        return bool(row and row["csrf_hash"] == token_hash(csrf_token))

    def logout(self, session_token: str | None) -> None:
        if not session_token:
            return
        should_drain = False
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT sessions.user_id,users.account_kind FROM sessions "
                "JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=?",
                (token_hash(session_token),),
            ).fetchone()
            if row:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
                conn.execute(
                    "UPDATE users SET session_generation=session_generation+1 WHERE id=?",
                    (row["user_id"],),
                )
                self._audit(conn, user_id=row["user_id"], event_type="session_revoked")
                if row["account_kind"] == "demo":
                    active = conn.execute(
                        "SELECT 1 FROM sessions WHERE user_id=? LIMIT 1", (row["user_id"],)
                    ).fetchone()
                    if not active:
                        self._queue_user_deletion(conn, str(row["user_id"]), "demo_logout")
                        should_drain = True
        if should_drain:
            self.drain_deletion_queue()

    def account(self, user_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            google_connected = (
                conn.execute(
                    "SELECT 1 FROM google_identities WHERE user_id=?", (user_id,)
                ).fetchone()
                is not None
            )
        if not user:
            raise ProductError("user_not_found", "Account not found", 404)
        return {
            "id": user["id"],
            "email": user["email"],
            "email_verified": bool(user["email_verified"]),
            "password_enabled": bool(user["password_enabled"]),
            "google_connected": google_connected,
            "credits": user["credit_balance"],
            "billing_configured": self.settings.billing_configured,
            "credit_pack_size": self.settings.credit_pack_size,
            "retention_days": self.settings.retention_days,
            "demo_mode": self.settings.extractor_backend == "replay",
            "demo_account": user["account_kind"] == "demo",
            "session_generation": int(user["session_generation"]),
            "principal_marker": hashlib.sha256(
                f"{user['id']}:{user['session_generation']}".encode()
            ).hexdigest()[:32],
        }

    def prepare_upload(self, *, user_id: str, filename: str, content: bytes) -> dict[str, Any]:
        self.require_customer_account(user_id, "customer uploads")
        return self._prepare_upload(
            user_id=user_id,
            filename=filename,
            content=content,
            require_credit=True,
        )

    def _assert_upload_capacity(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        incoming_bytes: int,
        require_credit: bool,
        fixture_sha256: str | None = None,
    ) -> None:
        user = conn.execute(
            "SELECT account_kind,credit_balance FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not user:
            raise ProductError("user_not_found", "Account not found", 404)
        if require_credit and int(user["credit_balance"]) < 1:
            raise ProductError("credits_required", "Add a chart credit before uploading", 402)
        usage = conn.execute(
            "SELECT "
            "COALESCE((SELECT SUM(byte_size) FROM uploads WHERE user_id=?),0) + "
            "COALESCE((SELECT SUM(source_byte_size) FROM jobs WHERE user_id=?),0) + "
            "COALESCE((SELECT SUM(byte_size) FROM pending_deletions WHERE user_id=?),0) "
            "AS bytes, "
            "(SELECT COUNT(*) FROM uploads WHERE user_id=?) AS upload_records, "
            "(SELECT COUNT(*) FROM uploads WHERE user_id=? AND NOT EXISTS ("
            "SELECT 1 FROM jobs WHERE jobs.upload_id=uploads.id)) AS unattached",
            (user_id, user_id, user_id, user_id, user_id),
        ).fetchone()
        existing_fixture = (
            conn.execute(
                "SELECT 1 FROM uploads WHERE user_id=? AND sha256=? LIMIT 1",
                (user_id, fixture_sha256),
            ).fetchone()
            if fixture_sha256
            else None
        )
        if (user["account_kind"] == "demo" and int(usage["bytes"]) > 0) or existing_fixture:
            raise ProductError(
                "demo_sample_limit",
                "This isolated sample session can create one verification run",
                409,
            )
        if int(usage["unattached"]) >= self.settings.max_unattached_uploads:
            raise ProductError(
                "upload_quota_reached",
                "Finish or remove an existing upload before adding another",
                429,
            )
        if int(usage["upload_records"]) >= self.settings.max_upload_records_per_user:
            raise ProductError(
                "upload_record_quota_reached",
                "This workspace has reached its retained upload-record limit",
                429,
            )
        if int(usage["bytes"]) + incoming_bytes > self.settings.max_user_storage_bytes:
            raise ProductError(
                "storage_quota_reached",
                "This workspace has reached its storage limit; remove an extraction and retry",
                413,
            )

    def _consume_upload_bytes(self, user_id: str, byte_count: int) -> None:
        principal = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        if not self.rate_limit(
            f"upload-bytes:{principal}",
            limit=self.settings.max_upload_bytes_per_minute,
            amount=byte_count,
        ):
            raise ProductError(
                "upload_rate_limited",
                "Upload bandwidth limit reached; retry in a minute",
                429,
            )

    def _assert_job_capacity(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        incoming_bytes: int,
    ) -> None:
        user = conn.execute("SELECT account_kind FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise ProductError("user_not_found", "Account not found", 404)
        usage = conn.execute(
            "SELECT "
            "COALESCE((SELECT SUM(byte_size) FROM uploads WHERE user_id=?),0) + "
            "COALESCE((SELECT SUM(source_byte_size) FROM jobs WHERE user_id=?),0) + "
            "COALESCE((SELECT SUM(byte_size) FROM pending_deletions WHERE user_id=?),0) "
            "AS bytes, "
            "(SELECT COUNT(*) FROM jobs WHERE user_id=?) AS jobs",
            (user_id, user_id, user_id, user_id),
        ).fetchone()
        if user["account_kind"] == "demo" and int(usage["jobs"]) >= 1:
            raise ProductError(
                "demo_sample_limit",
                "This isolated sample session can create one verification run",
                409,
            )
        if int(usage["jobs"]) >= self.settings.max_jobs_per_user:
            raise ProductError(
                "job_record_quota_reached",
                "This workspace has reached its retained extraction limit",
                429,
            )
        if int(usage["bytes"]) + incoming_bytes > self.settings.max_user_storage_bytes:
            raise ProductError(
                "storage_quota_reached",
                "This workspace has reached its storage limit; remove an extraction and retry",
                413,
            )

    def _prepare_upload(
        self,
        *,
        user_id: str,
        filename: str,
        content: bytes,
        require_credit: bool,
        fixture_sha256: str | None = None,
    ) -> dict[str, Any]:
        reserved = self._stage_upload_with_reservation(user_id=user_id, source=io.BytesIO(content))
        return self._prepare_staged_upload(
            user_id=user_id,
            filename=filename,
            reserved=reserved,
            require_credit=require_credit,
            fixture_sha256=fixture_sha256,
        )

    def prepare_upload_stream(
        self, *, user_id: str, filename: str, source: BinaryIO
    ) -> dict[str, Any]:
        self.require_customer_account(user_id, "customer uploads")
        return self._prepare_staged_upload(
            user_id=user_id,
            filename=filename,
            reserved=self._stage_upload_with_reservation(user_id=user_id, source=source),
            require_credit=True,
        )

    def _prepare_staged_upload(
        self,
        *,
        user_id: str,
        filename: str,
        reserved: ReservedStagedUpload,
        require_credit: bool,
        fixture_sha256: str | None = None,
    ) -> dict[str, Any]:
        staged = reserved.staged
        inspection = staged.inspection
        try:
            self._consume_upload_bytes(user_id, inspection.byte_size)
        except Exception:
            self.storage.delete(staged.path)
            self._release_storage_reservation(user_id=user_id, reservation=reserved.reservation)
            raise
        upload_id = self._id()
        safe_name = Path(filename or "chart").name[:180]
        path: Path | None = None
        now = utcnow()
        expected_path = self.storage.root / "uploads" / user_id / f"{upload_id}.source"
        try:
            self._resize_storage_reservation(
                user_id=user_id,
                reservation=reserved.reservation,
                byte_count=inspection.byte_size,
                kind="upload",
                storage_path=expected_path,
            )
            with self.database.transaction(immediate=True) as conn:
                self._assert_database_capacity(conn, user_id)
                self._assert_upload_capacity(
                    conn,
                    user_id=user_id,
                    incoming_bytes=inspection.byte_size,
                    require_credit=require_credit,
                    fixture_sha256=fixture_sha256,
                )
                path = self.storage.commit_staged_upload(
                    user_id=user_id, upload_id=upload_id, staged=staged.path
                )
                self._insert_row(
                    conn,
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
                    user_id=user_id,
                )
                self._consume_storage_reservation(
                    conn,
                    user_id=user_id,
                    reservation=reserved.reservation,
                    kind="upload",
                    byte_count=inspection.byte_size,
                    storage_path=expected_path,
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    event_type="upload_prepared",
                    details={"upload_id": upload_id, "mime": inspection.mime_type},
                )
        except Exception:
            expected = path if path is not None else expected_path
            self.storage.delete(expected)
            self.storage.delete(staged.path)
            self._release_storage_reservation(user_id=user_id, reservation=reserved.reservation)
            raise
        return {
            "id": upload_id,
            "name": safe_name,
            "mime_type": inspection.mime_type,
            "page_count": inspection.page_count,
            "expires_at": timestamp(now + timedelta(hours=self.settings.upload_ttl_hours)),
        }

    def prepare_demo_upload(self, user_id: str) -> dict[str, Any]:
        self.account(user_id)
        source = self.static_dir / "demo" / "budget-quarter.webp"
        if not source.exists():
            raise ProductError("demo_fixture_missing", "The sample source is unavailable", 500)
        content = source.read_bytes()
        return self._prepare_upload(
            user_id=user_id,
            filename="budget-quarter-sample.webp",
            content=content,
            require_credit=False,
            fixture_sha256=hashlib.sha256(content).hexdigest(),
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
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
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
        effective_key = idempotency_key or f"trusted-{uuid.uuid4().hex}"
        stored_key = self._idempotency_digest("browser-job", effective_key)
        request_sha256 = hashlib.sha256(
            json.dumps(
                {"upload_id": upload_id, "page_index": page_index, "crop": crop},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.database.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM api_idempotency WHERE user_id=? AND idempotency_key=?",
                (user_id, stored_key),
            ).fetchone()
        if existing:
            return self._idempotent_response(existing, request_sha256=request_sha256)
        upload = self.upload(user_id=user_id, upload_id=upload_id)
        if self.is_demo_user(user_id) and not self._is_free_demo_fixture(str(upload["sha256"])):
            raise ProductError(
                "demo_fixture_only",
                "The isolated sample session can run only the saved verification fixture",
                403,
            )
        if not 0 <= page_index < int(upload["page_count"]):
            raise ProductError("invalid_page", "Selected page does not exist")
        job_id = self._id()
        source_path: Path | None = None
        credit_cost = 0 if self._is_free_demo_fixture(str(upload["sha256"])) else 1
        expected_source_path = self.storage.root / "jobs" / user_id / f"{job_id}.source"
        copy_reservation = self._reserve_storage_bytes(
            user_id=user_id,
            byte_count=int(upload["byte_size"]),
            kind="job_copy",
            storage_path=expected_source_path,
        )
        try:
            with self.database.transaction(immediate=True) as conn:
                existing = conn.execute(
                    "SELECT * FROM api_idempotency WHERE user_id=? AND idempotency_key=?",
                    (user_id, stored_key),
                ).fetchone()
                if existing:
                    self._drop_storage_reservation(
                        conn,
                        user_id=user_id,
                        reservation=copy_reservation,
                    )
                    return self._idempotent_response(existing, request_sha256=request_sha256)
                live_upload = conn.execute(
                    "SELECT * FROM uploads WHERE id=? AND user_id=? AND expires_at>?",
                    (upload_id, user_id, timestamp()),
                ).fetchone()
                if not live_upload:
                    raise ProductError("upload_not_found", "Upload expired or was not found", 404)
                self._assert_job_capacity(
                    conn,
                    user_id=user_id,
                    incoming_bytes=int(live_upload["byte_size"]),
                )
                self._reserve_result_capacity(conn, user_id=user_id, job_id=None, attempt=1)
                now_value = utcnow()
                now = timestamp(now_value)
                self._create_idempotency_record(
                    conn,
                    user_id=user_id,
                    stored_key=stored_key,
                    request_sha256=request_sha256,
                    now=now_value,
                )
                source_path = self.storage.copy_to_job(
                    user_id=user_id,
                    job_id=job_id,
                    source=Path(live_upload["storage_path"]),
                )
                self._insert_row(
                    conn,
                    "INSERT INTO jobs("
                    "id,user_id,upload_id,source_name,source_mime,source_path,"
                    "source_sha256,source_byte_size,page_index,crop_json,status,progress_stage,"
                    "reservation_active,result_reservation_bytes,result_reservation_attempt,"
                    "retained_byte_reservation,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,'queued','Waiting for extraction',?,?,?,?,?,?)",
                    (
                        job_id,
                        user_id,
                        upload_id,
                        live_upload["original_name"],
                        live_upload["mime_type"],
                        str(source_path),
                        live_upload["sha256"],
                        live_upload["byte_size"],
                        page_index,
                        json.dumps(crop, separators=(",", ":")) if crop else None,
                        credit_cost,
                        self.settings.max_result_json_bytes,
                        1,
                        self.settings.result_publication_reservation_bytes,
                        now,
                        now,
                    ),
                    user_id=user_id,
                    new_future_rows=(self._new_job_future_rows() + 1 + int(bool(credit_cost))),
                )
                if credit_cost:
                    self._change_credits(
                        conn,
                        user_id=user_id,
                        delta=-credit_cost,
                        reason="job_reserved",
                        idempotency_key=f"job:{job_id}:reserve:1",
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
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                response = public_job(row)
                conn.execute(
                    "UPDATE api_idempotency SET response_json=?,completed_at=? "
                    "WHERE user_id=? AND idempotency_key=?",
                    (
                        json.dumps(response, separators=(",", ":")),
                        timestamp(),
                        user_id,
                        stored_key,
                    ),
                )
                self._consume_storage_reservation(
                    conn,
                    user_id=user_id,
                    reservation=copy_reservation,
                    kind="job_copy",
                    byte_count=int(live_upload["byte_size"]),
                    storage_path=expected_source_path,
                )
        except Exception:
            expected = source_path if source_path is not None else expected_source_path
            self.storage.delete(expected)
            self._release_storage_reservation(user_id=user_id, reservation=copy_reservation)
            raise
        return response

    def _idempotent_response(
        self,
        row: sqlite3.Row,
        *,
        request_sha256: str,
    ) -> dict[str, Any]:
        if row["expired_at"] or str(row["expires_at"]) <= timestamp():
            raise ProductError(
                "idempotency_key_expired",
                "That Idempotency-Key is outside its replay window; use a new key only for a "
                "new logical request",
                409,
            )
        if not hmac.compare_digest(str(row["request_sha256"]), request_sha256):
            raise ProductError(
                "idempotency_conflict",
                "That Idempotency-Key was already used for a different request",
                409,
            )
        if not row["response_json"]:
            raise ProductError(
                "request_in_progress",
                "A request with this Idempotency-Key is already in progress",
                409,
            )
        try:
            response = json.loads(str(row["response_json"]))
        except json.JSONDecodeError as exc:
            raise ProductError(
                "idempotency_state_invalid",
                "The stored request response could not be replayed",
                500,
            ) from exc
        if not isinstance(response, dict):
            raise ProductError(
                "idempotency_state_invalid",
                "The stored request response could not be replayed",
                500,
            )
        return response

    def submit_api_extraction(
        self,
        *,
        user_id: str,
        filename: str,
        content: bytes,
        page_index: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Atomically persist, reserve, and queue one public API request."""
        self.require_customer_account(user_id, "API extraction")
        return self._submit_api_staged_extraction(
            user_id=user_id,
            filename=filename,
            reserved=self._stage_upload_with_reservation(
                user_id=user_id, source=io.BytesIO(content)
            ),
            page_index=page_index,
            idempotency_key=idempotency_key,
        )

    def submit_api_extraction_stream(
        self,
        *,
        user_id: str,
        filename: str,
        source: BinaryIO,
        page_index: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.require_customer_account(user_id, "API extraction")
        return self._submit_api_staged_extraction(
            user_id=user_id,
            filename=filename,
            reserved=self._stage_upload_with_reservation(user_id=user_id, source=source),
            page_index=page_index,
            idempotency_key=idempotency_key,
        )

    def _submit_api_staged_extraction(
        self,
        *,
        user_id: str,
        filename: str,
        reserved: ReservedStagedUpload,
        page_index: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Atomically commit one bounded request spool, reservation, and queue row."""
        staged = reserved.staged

        def abandon_staging() -> None:
            self.storage.delete(staged.path)
            self._release_storage_reservation(user_id=user_id, reservation=reserved.reservation)

        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            abandon_staging()
            raise ProductError(
                "idempotency_key_required",
                "Provide an Idempotency-Key of 8-128 letters, numbers, '.', '_', ':', or '-'",
                422,
            )
        stored_key = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        inspection = staged.inspection
        if not 0 <= page_index < inspection.page_count:
            abandon_staging()
            raise ProductError("invalid_page", "Selected page does not exist")
        safe_name = Path(filename or "chart").name[:180]
        request_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "content_sha256": inspection.sha256,
                    "filename": safe_name,
                    "page_index": page_index,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.database.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM api_idempotency WHERE user_id=? AND idempotency_key=?",
                (user_id, stored_key),
            ).fetchone()
        if existing:
            abandon_staging()
            return self._idempotent_response(existing, request_sha256=request_sha256)

        try:
            self._consume_upload_bytes(user_id, inspection.byte_size)
        except Exception:
            abandon_staging()
            raise
        upload_id = self._id()
        job_id = self._id()
        expected_upload = self.storage.root / "uploads" / user_id / f"{upload_id}.source"
        expected_source = self.storage.root / "jobs" / user_id / f"{job_id}.source"
        copy_reservation: StorageReservation | None = None
        try:
            self._resize_storage_reservation(
                user_id=user_id,
                reservation=reserved.reservation,
                byte_count=inspection.byte_size,
                kind="upload",
                storage_path=expected_upload,
            )
            copy_reservation = self._reserve_storage_bytes(
                user_id=user_id,
                byte_count=inspection.byte_size,
                kind="job_copy",
                storage_path=expected_source,
            )
        except Exception:
            abandon_staging()
            if copy_reservation is not None:
                self._release_storage_reservation(user_id=user_id, reservation=copy_reservation)
            raise
        if copy_reservation is None:  # pragma: no cover - guarded by reservation success above
            abandon_staging()
            raise RuntimeError("Job source reservation was not created")
        upload_path: Path | None = None
        source_path: Path | None = None
        try:
            with self.database.transaction(immediate=True) as conn:
                existing = conn.execute(
                    "SELECT * FROM api_idempotency WHERE user_id=? AND idempotency_key=?",
                    (user_id, stored_key),
                ).fetchone()
                if existing:
                    self.storage.delete(staged.path)
                    self._drop_storage_reservation(
                        conn,
                        user_id=user_id,
                        reservation=reserved.reservation,
                    )
                    self._drop_storage_reservation(
                        conn,
                        user_id=user_id,
                        reservation=copy_reservation,
                    )
                    return self._idempotent_response(existing, request_sha256=request_sha256)
                self._assert_upload_capacity(
                    conn,
                    user_id=user_id,
                    incoming_bytes=inspection.byte_size,
                    require_credit=True,
                )
                self._assert_job_capacity(
                    conn,
                    user_id=user_id,
                    incoming_bytes=inspection.byte_size,
                )
                self._reserve_result_capacity(conn, user_id=user_id, job_id=None, attempt=1)
                now = utcnow()
                created_at = timestamp(now)
                self._create_idempotency_record(
                    conn,
                    user_id=user_id,
                    stored_key=stored_key,
                    request_sha256=request_sha256,
                    now=now,
                )
                upload_path = self.storage.commit_staged_upload(
                    user_id=user_id,
                    upload_id=upload_id,
                    staged=staged.path,
                )
                source_path = self.storage.copy_to_job(
                    user_id=user_id,
                    job_id=job_id,
                    source=upload_path,
                )
                self._insert_row(
                    conn,
                    "INSERT INTO uploads("
                    "id,user_id,original_name,mime_type,storage_path,byte_size,sha256,"
                    "page_count,created_at,expires_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        upload_id,
                        user_id,
                        safe_name,
                        inspection.mime_type,
                        str(upload_path),
                        inspection.byte_size,
                        inspection.sha256,
                        inspection.page_count,
                        created_at,
                        timestamp(now + timedelta(hours=self.settings.upload_ttl_hours)),
                    ),
                    user_id=user_id,
                )
                self._insert_row(
                    conn,
                    "INSERT INTO jobs("
                    "id,user_id,upload_id,source_name,source_mime,source_path,"
                    "source_sha256,source_byte_size,page_index,crop_json,status,progress_stage,"
                    "reservation_active,result_reservation_bytes,result_reservation_attempt,"
                    "retained_byte_reservation,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,NULL,'queued',"
                    "'Waiting for extraction',1,?,?,?,?,?)",
                    (
                        job_id,
                        user_id,
                        upload_id,
                        safe_name,
                        inspection.mime_type,
                        str(source_path),
                        inspection.sha256,
                        inspection.byte_size,
                        page_index,
                        self.settings.max_result_json_bytes,
                        1,
                        self.settings.result_publication_reservation_bytes,
                        created_at,
                        created_at,
                    ),
                    user_id=user_id,
                    new_future_rows=self._new_job_future_rows() + 3,
                )
                self._change_credits(
                    conn,
                    user_id=user_id,
                    delta=-1,
                    reason="job_reserved",
                    idempotency_key=f"job:{job_id}:reserve:1",
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    event_type="upload_prepared",
                    details={"upload_id": upload_id, "mime": inspection.mime_type},
                )
                self._audit(
                    conn,
                    user_id=user_id,
                    job_id=job_id,
                    event_type="job_queued",
                    details={
                        "page_index": page_index,
                        "cropped": False,
                        "credits_reserved": 1,
                        "submission": "api_v1",
                    },
                )
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                response = public_job(row)
                encoded_response = json.dumps(response, separators=(",", ":"))
                conn.execute(
                    "UPDATE api_idempotency SET response_json=?,completed_at=? "
                    "WHERE user_id=? AND idempotency_key=?",
                    (encoded_response, timestamp(), user_id, stored_key),
                )
                self._consume_storage_reservation(
                    conn,
                    user_id=user_id,
                    reservation=reserved.reservation,
                    kind="upload",
                    byte_count=inspection.byte_size,
                    storage_path=expected_upload,
                )
                self._consume_storage_reservation(
                    conn,
                    user_id=user_id,
                    reservation=copy_reservation,
                    kind="job_copy",
                    byte_count=inspection.byte_size,
                    storage_path=expected_source,
                )
            return response
        except Exception:
            self.storage.delete(staged.path)
            failed_paths = [
                source_path or expected_source,
                upload_path or expected_upload,
            ]
            for path in failed_paths:
                try:
                    self.storage.delete(path)
                except Exception:
                    with self.database.transaction(immediate=True) as conn:
                        self._queue_deletion(
                            conn,
                            path,
                            "api_submission_rollback",
                            user_id=user_id,
                        )
            self._release_storage_reservation(user_id=user_id, reservation=reserved.reservation)
            self._release_storage_reservation(user_id=user_id, reservation=copy_reservation)
            raise

    def list_jobs_page(
        self, user_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        bounded_limit = min(max(limit, 1), 100)
        decoded = self._decode_cursor(cursor)
        created_at, row_id = decoded if decoded else (None, None)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id=? AND ("
                "? IS NULL OR created_at<? OR (created_at=? AND id<?)) "
                "ORDER BY created_at DESC,id DESC LIMIT ?",
                (user_id, created_at, created_at, created_at, row_id, bounded_limit + 1),
            ).fetchall()
        page = rows[:bounded_limit]
        return {
            "items": [public_job(row, include_result=False) for row in page],
            "next_cursor": (
                self._encode_cursor(str(page[-1]["created_at"]), str(page[-1]["id"]))
                if len(rows) > bounded_limit and page
                else None
            ),
        }

    def list_jobs(self, user_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.list_jobs_page(user_id, cursor=cursor, limit=100)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items

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

    def job_audit_page(
        self,
        *,
        user_id: str,
        job_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self._job_row(user_id=user_id, job_id=job_id)
        bounded_limit = min(max(limit, 1), 100)
        decoded = self._decode_cursor(cursor)
        created_at, row_id = decoded if decoded else (None, None)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id,event_type,details_json,created_at FROM audit_events "
                "WHERE job_id=? AND (? IS NULL OR created_at<? OR (created_at=? AND id<?)) "
                "ORDER BY created_at DESC,id DESC LIMIT ?",
                (job_id, created_at, created_at, created_at, row_id, bounded_limit + 1),
            ).fetchall()
            rollups = (
                conn.execute(
                    "SELECT event_type,event_count,first_at,last_at FROM audit_rollups "
                    "WHERE job_id=? ORDER BY last_at DESC,event_type",
                    (job_id,),
                ).fetchall()
                if cursor is None
                else []
            )
        page = rows[:bounded_limit]
        return {
            "items": [
                {
                    "event": row["event_type"],
                    "details": json.loads(row["details_json"]),
                    "created_at": row["created_at"],
                }
                for row in page
            ],
            "rollups": [
                {
                    "event": row["event_type"],
                    "count": int(row["event_count"]),
                    "first_at": row["first_at"],
                    "created_at": row["last_at"],
                }
                for row in rollups
            ],
            "next_cursor": (
                self._encode_cursor(str(page[-1]["created_at"]), str(page[-1]["id"]))
                if len(rows) > bounded_limit and page
                else None
            ),
        }

    def job_audit(self, *, user_id: str, job_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.job_audit_page(user_id=user_id, job_id=job_id, cursor=cursor, limit=100)
            if cursor is None:
                items.extend(page["rollups"])
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items

    def job_versions(
        self,
        *,
        user_id: str,
        job_id: str,
        before: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._job_row(user_id=user_id, job_id=job_id)
        bounded_limit = min(max(limit, 1), 50)
        if before is not None and before <= 0:
            raise ProductError("invalid_version_cursor", "Version cursor must be positive", 422)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT version,source,created_at,LENGTH(CAST(chart_json AS BLOB)) AS byte_size "
                "FROM result_versions WHERE job_id=? AND user_id=? "
                "AND (? IS NULL OR version<?) ORDER BY version DESC LIMIT ?",
                (job_id, user_id, before, before, bounded_limit + 1),
            ).fetchall()
        has_more = len(rows) > bounded_limit
        page = rows[:bounded_limit]
        items = [
            {
                "version": int(row["version"]),
                "source": row["source"],
                "created_at": row["created_at"],
                "byte_size": int(row["byte_size"]),
            }
            for row in page
        ]
        return {
            "items": items,
            "next_before": int(page[-1]["version"]) if has_more and page else None,
        }

    def job_version(self, *, user_id: str, job_id: str, version: int) -> dict[str, Any]:
        self._job_row(user_id=user_id, job_id=job_id)
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT version,source,chart_json,created_at FROM result_versions "
                "WHERE job_id=? AND user_id=? AND version=?",
                (job_id, user_id, version),
            ).fetchone()
        if not row:
            raise ProductError("version_not_found", "Result version not found", 404)
        return {
            "version": int(row["version"]),
            "source": row["source"],
            "result": json.loads(row["chart_json"]),
            "created_at": row["created_at"],
        }

    def _next_result_version(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        job_id: str,
        encoded_bytes: int = 0,
        reservation_attempt: int | None = None,
    ) -> int:
        if encoded_bytes < 0 or encoded_bytes > self.settings.max_result_json_bytes:
            raise ProductError("invalid_result", "The chart result exceeds the service limit", 422)
        usage = conn.execute(
            "SELECT COALESCE(MAX(version),0) AS latest,COUNT(*) AS job_versions,"
            "(SELECT COALESCE(SUM(LENGTH(CAST(chart_json AS BLOB))),0) "
            "FROM result_versions WHERE user_id=?) AS user_bytes,"
            "(SELECT COALESCE(SUM(result_reservation_bytes),0) FROM jobs "
            "WHERE user_id=?) AS reserved_bytes,"
            "(SELECT CASE WHEN result_reservation_attempt=? THEN result_reservation_bytes "
            "ELSE 0 END FROM jobs WHERE id=? AND user_id=?) AS own_reservation "
            "FROM result_versions WHERE job_id=? AND user_id=?",
            (
                user_id,
                user_id,
                reservation_attempt,
                job_id,
                user_id,
                job_id,
                user_id,
            ),
        ).fetchone()
        if int(usage["job_versions"]) >= self.settings.max_result_versions_per_job:
            raise ProductError(
                "version_quota_reached",
                "This extraction has reached its retained version limit",
                429,
            )
        if (
            int(usage["user_bytes"])
            + int(usage["reserved_bytes"])
            - int(usage["own_reservation"] or 0)
            + encoded_bytes
            > self.settings.max_history_bytes_per_user
        ):
            raise ProductError(
                "history_storage_quota_reached",
                "This workspace has reached its result-history storage limit",
                413,
            )
        return int(usage["latest"]) + 1

    def save_correction(
        self, *, user_id: str, job_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            chart = ChartData.model_validate(result)
            self._validate_product_chart(chart)
        except (TypeError, ValueError) as exc:
            raise ProductError("invalid_result", "The edited table is not valid", 422) from exc
        encoded = chart.model_dump_json()
        encoded_bytes = len(encoded.encode("utf-8"))
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            if row["status"] not in {"review", "approved"}:
                raise ProductError("job_not_editable", "Wait for extraction before editing", 409)
            version = self._next_result_version(
                conn,
                user_id=user_id,
                job_id=job_id,
                encoded_bytes=encoded_bytes,
            )
            old_current_bytes = len(str(row["current_result_json"] or "").encode("utf-8"))
            self._assert_retained_byte_capacity(
                conn,
                additional_bytes=encoded_bytes + max(0, encoded_bytes - old_current_bytes),
            )
            now = timestamp()
            self._insert_row(
                conn,
                "INSERT INTO result_versions("
                "id,job_id,user_id,version,source,chart_json,created_at"
                ") "
                "VALUES (?,?,?,?,?,?,?)",
                (self._id(), job_id, user_id, version, "correction", encoded, now),
                user_id=user_id,
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
                if isinstance(point.x, (int, float)) and not math.isfinite(float(point.x)):
                    raise ValueError("Chart coordinates must be finite")
                if isinstance(point.x, str) and len(point.x) > 500:
                    raise ValueError("Chart labels are too long")
        if len(chart.model_dump_json().encode()) > self.settings.max_result_json_bytes:
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
                self._finish_cancelled_queued_in_transaction(conn, row)
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
            # Reprocessing creates the same terminal, audit, provider-attempt, and
            # recovery obligations whether or not this particular fixture costs a
            # credit.  Admit all of those rows before changing any durable job state.
            self._admit_database_rows(
                conn,
                user_id=user_id,
                additional_rows=1 + int(bool(credit_cost)),
                new_future_rows=self._new_job_future_rows(),
            )
            self._reserve_result_capacity(conn, user_id=user_id, job_id=job_id, attempt=attempt)
            now = timestamp()
            conn.execute(
                "UPDATE jobs SET status='queued',progress_stage='Waiting for extraction',"
                "attempt=?,recovery_count=0,cancel_requested=0,reservation_active=?,error_code=NULL,"
                "error_message=NULL,provider_dispatched=0,provider_dispatched_at=NULL,"
                "worker_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,"
                "result_reservation_bytes=?,result_reservation_attempt=?,"
                "retained_byte_reservation=?,"
                "updated_at=? WHERE id=?",
                (
                    attempt,
                    credit_cost,
                    self.settings.max_result_json_bytes,
                    attempt,
                    self.settings.result_publication_reservation_bytes,
                    now,
                    job_id,
                ),
            )
            if credit_cost:
                self._change_credits(
                    conn,
                    user_id=user_id,
                    delta=-credit_cost,
                    reason="job_reprocess_reserved",
                    idempotency_key=f"job:{job_id}:reserve:{attempt}",
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
            billing_count = int(
                conn.execute("SELECT COUNT(*) AS count FROM billing_events").fetchone()["count"]
            )
            if billing_count >= self.settings.max_billing_events_global:
                raise ProductError(
                    "billing_event_capacity_reached",
                    "Billing event processing is paused pending operator archival",
                    503,
                )
            user = conn.execute(
                "SELECT id,account_kind FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not user:
                raise ProductError("billing_user_missing", "Billing account was not found", 422)
            if user["account_kind"] == "demo":
                raise ProductError(
                    "billing_user_invalid", "Demo sessions cannot receive credits", 422
                )
            self._insert_row(
                conn,
                "INSERT INTO billing_events(event_id,event_type,payload_sha256,processed_at) "
                "VALUES (?,?,?,?)",
                (event_id, event_type, payload_sha256, timestamp()),
                user_id=None,
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

    def _export_rows(self, chart: ChartData) -> list[list[str | float]]:
        x_label = chart.x_axis.label or ("category" if chart.chart_type == "pie" else "x")
        y_label = chart.y_axis.label or "value"
        if len(chart.series) <= 1:
            rows: list[list[str | float]] = [[x_label, y_label]]
            if chart.series:
                rows.extend([[point.x, point.y] for point in chart.series[0].points])
            return rows
        rows = [["series", x_label, y_label]]
        for index, series in enumerate(chart.series):
            series_name = series.name or f"series_{index + 1}"
            rows.extend([[series_name, point.x, point.y] for point in series.points])
        return rows

    def _safe_csv(self, chart: ChartData) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        for row in self._export_rows(chart):
            writer.writerow(
                [
                    self._spreadsheet_cell(value) if isinstance(value, str) else value
                    for value in row
                ]
            )
        return output.getvalue()

    def _xlsx(self, chart: ChartData, row: sqlite3.Row) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Extracted data"
        for row_values in self._export_rows(chart):
            sheet.append(
                [
                    self._spreadsheet_cell(value) if isinstance(value, str) else value
                    for value in row_values
                ]
            )
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

    def delete_job(self, *, user_id: str, job_id: str) -> bool:
        deletion_paths: list[str] = []
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            if row["status"] in {"queued", "running"}:
                raise ProductError("job_busy", "Cancel the extraction before deleting it", 409)
            self._audit(
                conn,
                user_id=user_id,
                event_type="job_deleted",
                details={"deleted_job_id": job_id},
            )
            self._queue_deletion(
                conn,
                row["source_path"],
                "job_deleted",
                user_id=user_id,
                byte_size=int(row["source_byte_size"]),
            )
            deletion_paths.append(str(row["source_path"]))
            if row["upload_id"]:
                shared = conn.execute(
                    "SELECT 1 FROM jobs WHERE upload_id=? AND id<>? LIMIT 1",
                    (row["upload_id"], job_id),
                ).fetchone()
                if not shared:
                    upload = conn.execute(
                        "SELECT storage_path,byte_size FROM uploads WHERE id=? AND user_id=?",
                        (row["upload_id"], user_id),
                    ).fetchone()
                    if upload:
                        self._queue_deletion(
                            conn,
                            upload["storage_path"],
                            "last_job_upload_deleted",
                            user_id=user_id,
                            byte_size=int(upload["byte_size"]),
                        )
                        deletion_paths.append(str(upload["storage_path"]))
                        conn.execute(
                            "DELETE FROM uploads WHERE id=? AND user_id=?",
                            (row["upload_id"], user_id),
                        )
            conn.execute("DELETE FROM jobs WHERE id=? AND user_id=?", (job_id, user_id))
        self.drain_deletion_queue(paths=deletion_paths)
        with self.database.connect() as conn:
            remaining = sum(
                int(
                    conn.execute(
                        "SELECT COUNT(*) AS count FROM pending_deletions WHERE storage_path=?",
                        (path,),
                    ).fetchone()["count"]
                )
                for path in deletion_paths
            )
        return remaining == 0

    def _queue_deletion(
        self,
        conn: sqlite3.Connection,
        storage_path: str | Path,
        reason: str,
        *,
        user_id: str | None = None,
        byte_size: int | None = None,
    ) -> None:
        now = timestamp()
        if byte_size is None:
            try:
                byte_size = Path(storage_path).stat().st_size
            except OSError:
                byte_size = 0
        existing = conn.execute(
            "SELECT 1 FROM pending_deletions WHERE storage_path=?", (str(storage_path),)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE pending_deletions SET "
                "user_id=COALESCE(?,user_id),byte_size=MAX(?,byte_size),reason=?,updated_at=? "
                "WHERE storage_path=?",
                (user_id, max(0, byte_size), reason[:80], now, str(storage_path)),
            )
            return
        self._insert_row(
            conn,
            "INSERT INTO pending_deletions("
            "storage_path,user_id,byte_size,reason,attempts,last_error,created_at,updated_at"
            ") VALUES (?,?,?,?,0,NULL,?,?)",
            (str(storage_path), user_id, max(0, byte_size), reason[:80], now, now),
            user_id=user_id,
            mandatory=True,
        )

    def _queue_user_deletion(self, conn: sqlite3.Connection, user_id: str, reason: str) -> None:
        paths = conn.execute(
            "SELECT storage_path AS path,byte_size FROM uploads WHERE user_id=? "
            "UNION ALL SELECT source_path AS path,source_byte_size AS byte_size "
            "FROM jobs WHERE user_id=?",
            (user_id, user_id),
        ).fetchall()
        for row in paths:
            self._queue_deletion(
                conn,
                row["path"],
                reason,
                user_id=user_id,
                byte_size=int(row["byte_size"]),
            )
        conn.execute("DELETE FROM audit_events WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))

    def drain_deletion_queue(self, *, paths: list[str] | None = None, limit: int = 200) -> int:
        if paths is None:
            with self.database.connect() as conn:
                rows = conn.execute(
                    "SELECT storage_path FROM pending_deletions ORDER BY created_at LIMIT ?",
                    (limit,),
                ).fetchall()
            selected = [str(row["storage_path"]) for row in rows]
        else:
            selected = list(dict.fromkeys(paths[:limit]))
        deleted = 0
        for storage_path in selected:
            # The exclusive operations lock spans both the final reference check
            # and filesystem deletion.  Publication holds the shared side of the
            # same lock, so it cannot commit a new reference between these steps.
            with self.database.transaction(immediate=True, exclusive_operation=True) as conn:
                if self._path_is_referenced(conn, storage_path):
                    conn.execute(
                        "DELETE FROM pending_deletions WHERE storage_path=?", (storage_path,)
                    )
                    continue
                try:
                    self.storage.delete(storage_path)
                except Exception as exc:
                    conn.execute(
                        "UPDATE pending_deletions SET "
                        "attempts=attempts+1,last_error=?,updated_at=? "
                        "WHERE storage_path=?",
                        (f"{type(exc).__name__}: {exc}"[:500], timestamp(), storage_path),
                    )
                else:
                    changed = conn.execute(
                        "DELETE FROM pending_deletions WHERE storage_path=?", (storage_path,)
                    ).rowcount
                    deleted += int(changed == 1)
        return deleted

    @staticmethod
    def _path_is_referenced(conn: sqlite3.Connection, storage_path: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM uploads WHERE storage_path=? "
                "UNION SELECT 1 FROM jobs WHERE source_path=? "
                "UNION SELECT 1 FROM storage_reservations WHERE storage_path=? LIMIT 1",
                (storage_path, storage_path, storage_path),
            ).fetchone()
            is not None
        )

    def create_api_key(
        self, *, user_id: str, name: str, expected_generation: int | None = None
    ) -> dict[str, str]:
        self.require_customer_account(user_id, "API credentials")
        clean_name = name.strip()[:80]
        if not clean_name:
            raise ProductError("invalid_key_name", "Name the API key")
        secret, prefix, digest = api_key()
        with self.database.transaction(immediate=True) as conn:
            user = conn.execute(
                "SELECT session_generation FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not user or (
                expected_generation is not None
                and user["session_generation"] != expected_generation
            ):
                raise ProductError("authentication_required", "Sign in again to create a key", 401)
            self._assert_database_capacity(conn, user_id)
            counts = conn.execute(
                "SELECT COUNT(*) AS retained,"
                "SUM(CASE WHEN revoked_at IS NULL THEN 1 ELSE 0 END) AS active "
                "FROM api_keys WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if int(counts["active"] or 0) >= self.settings.max_active_api_keys_per_user:
                raise ProductError(
                    "active_api_key_limit_reached",
                    "Revoke an active API key before creating another",
                    429,
                )
            retained = int(counts["retained"] or 0)
            if retained >= self.settings.max_api_key_records_per_user:
                removable = retained - self.settings.max_api_key_records_per_user + 1
                deleted = conn.execute(
                    "DELETE FROM api_keys WHERE id IN (SELECT id FROM api_keys "
                    "WHERE user_id=? AND revoked_at IS NOT NULL "
                    "ORDER BY revoked_at,created_at,id LIMIT ?)",
                    (user_id, removable),
                ).rowcount
                if deleted < removable:
                    raise ProductError(
                        "api_key_history_limit_reached",
                        "Revoke old credentials before creating another API key",
                        429,
                    )
            self._insert_row(
                conn,
                "INSERT INTO api_keys(id,user_id,name,prefix,key_hash,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (self._id(), user_id, clean_name, prefix, digest, timestamp()),
                user_id=user_id,
            )
            self._audit(
                conn,
                user_id=user_id,
                event_type="api_key_created",
                details={"name": clean_name, "prefix": prefix},
            )
        return {"key": secret, "prefix": prefix, "name": clean_name}

    def list_api_keys_page(
        self,
        *,
        user_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self.require_customer_account(user_id, "API credentials")
        bounded_limit = min(max(limit, 1), 100)
        decoded = self._decode_cursor(cursor)
        created_at, row_id = decoded if decoded else (None, None)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id,name,prefix,created_at,last_used_at,revoked_at FROM api_keys "
                "WHERE user_id=? AND (? IS NULL OR created_at<? OR (created_at=? AND id<?)) "
                "ORDER BY created_at DESC,id DESC LIMIT ?",
                (user_id, created_at, created_at, created_at, row_id, bounded_limit + 1),
            ).fetchall()
        page = rows[:bounded_limit]
        return {
            "items": [dict(row) for row in page],
            "next_cursor": (
                self._encode_cursor(str(page[-1]["created_at"]), str(page[-1]["id"]))
                if len(rows) > bounded_limit and page
                else None
            ),
        }

    def list_api_keys(self, *, user_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.list_api_keys_page(user_id=user_id, cursor=cursor, limit=100)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items

    def revoke_api_key(self, *, user_id: str, key_id: str) -> dict[str, Any]:
        self.require_customer_account(user_id, "API credentials")
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

    def revoke_all_api_keys(self, *, user_id: str) -> int:
        self.require_customer_account(user_id, "API credentials")
        with self.database.transaction(immediate=True) as conn:
            now = timestamp()
            rows = conn.execute(
                "SELECT prefix FROM api_keys WHERE user_id=? AND revoked_at IS NULL", (user_id,)
            ).fetchall()
            changed = conn.execute(
                "UPDATE api_keys SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            ).rowcount
            if changed:
                self._audit(
                    conn,
                    user_id=user_id,
                    event_type="api_keys_revoked_all",
                    details={"count": changed, "prefixes": [row["prefix"] for row in rows[:20]]},
                )
        return int(changed)

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

    def claim_next_job(self, worker_owner: str = "manual") -> WorkerClaim | None:
        now = utcnow()
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            token = random_token(24)
            generation = int(row["lease_generation"]) + 1
            changed = conn.execute(
                "UPDATE jobs SET status='running',progress_stage='Preparing source',"
                "worker_owner=?,lease_token=?,lease_generation=?,heartbeat_at=?,lease_expires_at=?,"
                "updated_at=? WHERE id=? AND status='queued' AND lease_generation=?",
                (
                    worker_owner,
                    token,
                    generation,
                    timestamp(now),
                    timestamp(now + timedelta(seconds=self.settings.worker_lease_seconds)),
                    timestamp(now),
                    row["id"],
                    row["lease_generation"],
                ),
            ).rowcount
            if changed != 1:
                return None
            claimed = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            self._audit(
                conn,
                user_id=row["user_id"],
                job_id=row["id"],
                event_type="job_started",
                details={"attempt": row["attempt"], "execution_generation": generation},
            )
        return WorkerClaim(
            job_id=str(claimed["id"]),
            user_id=str(claimed["user_id"]),
            attempt=int(claimed["attempt"]),
            generation=generation,
            token=token,
            owner=worker_owner,
            row=claimed,
        )

    def _claim_row(
        self, conn: sqlite3.Connection, claim: WorkerClaim, *, require_live_lease: bool = True
    ) -> sqlite3.Row | None:
        sql = (
            "SELECT * FROM jobs WHERE id=? AND user_id=? AND attempt=? AND status='running' "
            "AND worker_owner=? AND lease_token=? AND lease_generation=?"
        )
        values: list[Any] = [
            claim.job_id,
            claim.user_id,
            claim.attempt,
            claim.owner,
            claim.token,
            claim.generation,
        ]
        if require_live_lease:
            sql += " AND lease_expires_at>?"
            values.append(timestamp())
        return conn.execute(sql, values).fetchone()

    def heartbeat_claim(self, claim: WorkerClaim) -> bool:
        now = utcnow()
        with self.database.transaction(immediate=True) as conn:
            changed = conn.execute(
                "UPDATE jobs SET heartbeat_at=?,lease_expires_at=?,updated_at=? "
                "WHERE id=? AND user_id=? AND attempt=? AND status='running' AND worker_owner=? "
                "AND lease_token=? AND lease_generation=? AND lease_expires_at>?",
                (
                    timestamp(now),
                    timestamp(now + timedelta(seconds=self.settings.worker_lease_seconds)),
                    timestamp(now),
                    claim.job_id,
                    claim.user_id,
                    claim.attempt,
                    claim.owner,
                    claim.token,
                    claim.generation,
                    timestamp(now),
                ),
            ).rowcount
        return changed == 1

    def _update_claim_progress(self, claim: WorkerClaim, stage: str) -> bool:
        with self.database.transaction(immediate=True) as conn:
            current = self._claim_row(conn, claim)
            if not current:
                return False
            return (
                conn.execute(
                    "UPDATE jobs SET progress_stage=?,updated_at=? WHERE id=? AND user_id=? "
                    "AND attempt=? AND status='running' AND worker_owner=? AND lease_token=? "
                    "AND lease_generation=? AND lease_expires_at>?",
                    (
                        stage,
                        timestamp(),
                        claim.job_id,
                        claim.user_id,
                        claim.attempt,
                        claim.owner,
                        claim.token,
                        claim.generation,
                        timestamp(),
                    ),
                ).rowcount
                == 1
            )

    def _start_claim_heartbeat(
        self, claim: WorkerClaim
    ) -> tuple[threading.Event, threading.Event, threading.Thread]:
        finished = threading.Event()
        lost = threading.Event()

        def renew() -> None:
            while not finished.wait(self.settings.worker_heartbeat_seconds):
                try:
                    if not self.heartbeat_claim(claim):
                        lost.set()
                        return
                except Exception:
                    logger.exception("job_lease_heartbeat_failed")

        thread = threading.Thread(
            target=renew,
            name=f"unrender-heartbeat-{claim.job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return finished, lost, thread

    def _provider_circuit_open(self, conn: sqlite3.Connection, user_id: str) -> bool:
        cutoff = timestamp(utcnow() - timedelta(hours=1))
        user_failures = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM provider_attempts WHERE user_id=? "
                "AND outcome='failed' AND completed_at>=?",
                (user_id, cutoff),
            ).fetchone()["count"]
        )
        global_failures = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM provider_attempts WHERE outcome='failed' "
                "AND completed_at>=?",
                (cutoff,),
            ).fetchone()["count"]
        )
        return (
            user_failures >= self.settings.provider_failure_limit_per_user_hour
            or global_failures >= self.settings.provider_failure_limit_global_hour
        )

    def _begin_provider_dispatch(self, claim: WorkerClaim) -> bool:
        with self.database.transaction(immediate=True) as conn:
            current = self._claim_row(conn, claim)
            if not current:
                return False
            if current["cancel_requested"]:
                self._finish_cancelled_claim_in_transaction(conn, current, claim)
                return False
            if (
                int(current["result_reservation_bytes"]) != self.settings.max_result_json_bytes
                or int(current["result_reservation_attempt"] or -1) != claim.attempt
                or int(current["retained_byte_reservation"])
                != self.settings.result_publication_reservation_bytes
            ):
                self._finish_failed_claim_in_transaction(
                    conn,
                    current,
                    claim,
                    "result_capacity_reservation_lost",
                    "The durable result-capacity reservation was unavailable; no provider "
                    "call was made.",
                )
                return False
            if self._provider_circuit_open(conn, claim.user_id):
                self._finish_failed_claim_in_transaction(
                    conn,
                    current,
                    claim,
                    "provider_circuit_open",
                    "Provider dispatch is paused after repeated recent failures; "
                    "no provider call was made.",
                )
                return False
            retained_attempts = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM provider_attempts WHERE job_id=?",
                    (claim.job_id,),
                ).fetchone()["count"]
            )
            if retained_attempts >= self.settings.max_provider_attempts_per_job:
                self._finish_failed_claim_in_transaction(
                    conn,
                    current,
                    claim,
                    "provider_attempt_history_limit",
                    "This extraction reached its retained provider-attempt limit; "
                    "no provider call was made.",
                )
                return False
            now = timestamp()
            changed = conn.execute(
                "UPDATE jobs SET provider_dispatched=1,provider_dispatched_at=?,updated_at=? "
                "WHERE id=? AND user_id=? AND attempt=? AND status='running' AND worker_owner=? "
                "AND lease_token=? AND lease_generation=? AND lease_expires_at>? "
                "AND provider_dispatched=0 AND cancel_requested=0",
                (
                    now,
                    now,
                    claim.job_id,
                    claim.user_id,
                    claim.attempt,
                    claim.owner,
                    claim.token,
                    claim.generation,
                    now,
                ),
            ).rowcount
            if changed != 1:
                return False
            self._insert_row(
                conn,
                "INSERT INTO provider_attempts("
                "job_id,user_id,attempt,lease_generation,dispatched_at"
                ") VALUES (?,?,?,?,?)",
                (claim.job_id, claim.user_id, claim.attempt, claim.generation, now),
                user_id=claim.user_id,
                mandatory=True,
            )
            self._audit(
                conn,
                user_id=claim.user_id,
                job_id=claim.job_id,
                event_type="provider_dispatched",
                details={"attempt": claim.attempt, "execution_generation": claim.generation},
            )
            return True

    def _release_claim_for_shutdown(self, claim: WorkerClaim) -> bool:
        with self.database.transaction(immediate=True) as conn:
            current = self._claim_row(conn, claim)
            if not current or current["provider_dispatched"]:
                return False
            changed = conn.execute(
                "UPDATE jobs SET status='queued',progress_stage='Worker draining',"
                "worker_owner=NULL,"
                "lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=? "
                "WHERE id=? AND user_id=? AND attempt=? AND status='running' AND worker_owner=? "
                "AND lease_token=? AND lease_generation=? AND lease_expires_at>? "
                "AND provider_dispatched=0",
                (
                    timestamp(),
                    claim.job_id,
                    claim.user_id,
                    claim.attempt,
                    claim.owner,
                    claim.token,
                    claim.generation,
                    timestamp(),
                ),
            ).rowcount
            if changed:
                self._audit(
                    conn,
                    user_id=claim.user_id,
                    job_id=claim.job_id,
                    event_type="job_released_for_shutdown",
                    details={"execution_generation": claim.generation},
                )
            return changed == 1

    def process_one(
        self,
        worker_owner: str = "manual",
        stop_event: threading.Event | None = None,
    ) -> bool:
        claim = self.claim_next_job(worker_owner)
        if not claim:
            return False
        row = claim.row
        job_id = claim.job_id
        started = time.monotonic()
        provider_started: float | None = None
        heartbeat_stop, lease_lost, heartbeat_thread = self._start_claim_heartbeat(claim)
        logger.info(
            "job_processing_started",
            extra={"event_name": "job_processing_started", "job_id": job_id},
        )
        try:
            if row["cancel_requested"]:
                self._finish_cancelled_claim(claim)
                return True
            if stop_event and stop_event.is_set():
                self._release_claim_for_shutdown(claim)
                return True
            if not self._update_claim_progress(claim, "Reading chart"):
                return True
            image = self.storage.page_png(
                source=Path(row["source_path"]),
                mime_type=row["source_mime"],
                page_index=int(row["page_index"]),
                crop=json.loads(row["crop_json"]) if row["crop_json"] else None,
            )
            if stop_event and stop_event.is_set():
                self._release_claim_for_shutdown(claim)
                return True
            if lease_lost.is_set() or not self._update_claim_progress(claim, "Extracting table"):
                return True
            if not self._begin_provider_dispatch(claim):
                return True
            provider_started = time.monotonic()
            output = self.extractor.extract(image)
            provider_duration_ms = round((time.monotonic() - provider_started) * 1000)
            try:
                validated_chart = ChartData.model_validate(output.chart)
                self._validate_product_chart(validated_chart)
                raw_output = truncate_utf8(output.raw, self.settings.max_result_json_bytes)
                extractor_name = truncate_utf8(output.extractor, 200)
                model_version = truncate_utf8(output.model_version, 500)
            except (AttributeError, TypeError, ValueError) as exc:
                raise ExtractionError(
                    "model_output_invalid", "The provider returned an invalid chart result"
                ) from exc
            logger.info(
                "provider_call_succeeded",
                extra={
                    "event_name": "provider_call_succeeded",
                    "job_id": job_id,
                    "provider": extractor_name,
                    "duration_ms": provider_duration_ms,
                },
            )
            encoded = validated_chart.model_dump_json()
            with self.database.transaction(immediate=True) as conn:
                current = self._claim_row(conn, claim)
                if not current:
                    return True
                if current["cancel_requested"]:
                    self._finish_cancelled_claim_in_transaction(conn, current, claim)
                    return True
                version = self._next_result_version(
                    conn,
                    user_id=claim.user_id,
                    job_id=job_id,
                    encoded_bytes=len(encoded.encode("utf-8")),
                    reservation_attempt=claim.attempt,
                )
                now = timestamp()
                source = "extraction" if version == 1 else "reprocess"
                self._insert_row(
                    conn,
                    "INSERT INTO result_versions("
                    "id,job_id,user_id,version,source,chart_json,created_at"
                    ") VALUES (?,?,?,?,?,?,?)",
                    (self._id(), job_id, claim.user_id, version, source, encoded, now),
                    user_id=claim.user_id,
                    mandatory=True,
                )
                changed = conn.execute(
                    "UPDATE jobs SET status='review',progress_stage='Ready for review',"
                    "reservation_active=0,extractor=?,model_version=?,raw_result=?,"
                    "original_result_json=COALESCE(original_result_json,?),current_result_json=?,"
                    "error_code=NULL,error_message=NULL,approved_at=NULL,worker_owner=NULL,"
                    "lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=? "
                    ",result_reservation_bytes=0,result_reservation_attempt=NULL,"
                    "retained_byte_reservation=0 "
                    "WHERE id=? AND user_id=? AND attempt=? AND status='running' "
                    "AND worker_owner=? "
                    "AND lease_token=? AND lease_generation=? AND lease_expires_at>? "
                    "AND result_reservation_attempt=?",
                    (
                        extractor_name,
                        model_version,
                        raw_output,
                        encoded,
                        encoded,
                        now,
                        job_id,
                        claim.user_id,
                        claim.attempt,
                        claim.owner,
                        claim.token,
                        claim.generation,
                        now,
                        claim.attempt,
                    ),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("Worker lease changed during terminal commit")
                provider_changed = conn.execute(
                    "UPDATE provider_attempts SET outcome='succeeded',completed_at=? "
                    "WHERE job_id=? AND attempt=? AND lease_generation=? AND outcome='dispatched'",
                    (now, job_id, claim.attempt, claim.generation),
                ).rowcount
                if provider_changed != 1:
                    raise RuntimeError("Provider attempt changed during terminal commit")
                self._audit(
                    conn,
                    user_id=claim.user_id,
                    job_id=job_id,
                    event_type="extraction_completed",
                    details={
                        "version": version,
                        "extractor": extractor_name,
                        "model": model_version,
                        "execution_generation": claim.generation,
                    },
                )
            logger.info(
                "job_processing_succeeded",
                extra={
                    "event_name": "job_processing_succeeded",
                    "job_id": job_id,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
            )
        except ExtractionError as exc:
            logger.warning(
                "provider_call_failed",
                extra={
                    "event_name": "provider_call_failed",
                    "job_id": job_id,
                    "error_code": exc.code,
                    "duration_ms": round((time.monotonic() - (provider_started or started)) * 1000),
                },
            )
            self._finish_failed_claim(claim, exc.code, str(exc))
        except ProductError as exc:
            self._finish_failed_claim(claim, exc.code, str(exc))
        except (InvalidUpload, ValueError) as exc:
            self._finish_failed_claim(claim, "source_invalid", str(exc))
        except Exception:
            logger.exception(
                "job_processing_failed",
                extra={"event_name": "job_processing_failed", "job_id": job_id},
            )
            self._finish_failed_claim(
                claim,
                "internal_error",
                "The extraction failed unexpectedly. Credit handling follows dispatch state.",
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
        return True

    def _finish_failed_claim(self, claim: WorkerClaim, code: str, message: str) -> bool:
        with self.database.transaction(immediate=True) as conn:
            current = self._claim_row(conn, claim)
            if not current:
                return False
            if current["cancel_requested"]:
                return self._finish_cancelled_claim_in_transaction(conn, current, claim)
            return self._finish_failed_claim_in_transaction(conn, current, claim, code, message)

    def _finish_failed_claim_in_transaction(
        self,
        conn: sqlite3.Connection,
        current: sqlite3.Row,
        claim: WorkerClaim,
        code: str,
        message: str,
    ) -> bool:
        preserved_status = self._preserved_result_status(current)
        status = preserved_status or "failed"
        charged = bool(current["provider_dispatched"])
        stage = (
            "Reprocess failed; previous approval retained"
            if preserved_status == "approved"
            else "Reprocess failed; previous review retained"
            if preserved_status == "review"
            else "Needs attention"
        )
        changed = conn.execute(
            "UPDATE jobs SET status=?,progress_stage=?,reservation_active=0,cancel_requested=0,"
            "error_code=?,error_message=?,worker_owner=NULL,lease_token=NULL,lease_expires_at=NULL,"
            "heartbeat_at=NULL,result_reservation_bytes=0,result_reservation_attempt=NULL,"
            "retained_byte_reservation=0,updated_at=? WHERE id=? AND user_id=? AND attempt=? "
            "AND status='running' AND worker_owner=? AND lease_token=? AND lease_generation=? "
            "AND lease_expires_at>?",
            (
                status,
                stage,
                code,
                message[:500],
                timestamp(),
                claim.job_id,
                claim.user_id,
                claim.attempt,
                claim.owner,
                claim.token,
                claim.generation,
                timestamp(),
            ),
        ).rowcount
        if changed != 1:
            return False
        if current["reservation_active"] and not charged:
            self._change_credits(
                conn,
                user_id=claim.user_id,
                delta=1,
                reason="job_failed_before_dispatch_refund",
                idempotency_key=f"job:{claim.job_id}:refund:{claim.attempt}",
                mandatory=True,
            )
        if charged:
            provider_changed = conn.execute(
                "UPDATE provider_attempts SET outcome='failed',completed_at=? "
                "WHERE job_id=? AND attempt=? AND lease_generation=? AND outcome='dispatched'",
                (timestamp(), claim.job_id, claim.attempt, claim.generation),
            ).rowcount
            if provider_changed != 1:
                raise RuntimeError("Provider attempt changed during failed terminal commit")
        self._audit(
            conn,
            user_id=claim.user_id,
            job_id=claim.job_id,
            event_type="extraction_failed",
            details={
                "code": code,
                "provider_dispatched": charged,
                "credit_refunded": bool(current["reservation_active"] and not charged),
                "execution_generation": claim.generation,
            },
        )
        return True

    def _finish_cancelled_claim(self, claim: WorkerClaim) -> bool:
        with self.database.transaction(immediate=True) as conn:
            current = self._claim_row(conn, claim)
            if not current:
                return False
            return self._finish_cancelled_claim_in_transaction(conn, current, claim)

    def _finish_cancelled_claim_in_transaction(
        self, conn: sqlite3.Connection, current: sqlite3.Row, claim: WorkerClaim
    ) -> bool:
        preserved_status = self._preserved_result_status(current)
        status = preserved_status or "cancelled"
        charged = bool(current["provider_dispatched"])
        stage = (
            "Reprocess cancelled; previous approval retained"
            if preserved_status == "approved"
            else "Reprocess cancelled; previous review retained"
            if preserved_status == "review"
            else "Cancelled"
        )
        changed = conn.execute(
            "UPDATE jobs SET status=?,progress_stage=?,reservation_active=0,cancel_requested=0,"
            "worker_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,"
            "result_reservation_bytes=0,result_reservation_attempt=NULL,"
            "retained_byte_reservation=0,updated_at=? "
            "WHERE id=? AND user_id=? AND attempt=? AND status='running' AND worker_owner=? "
            "AND lease_token=? AND lease_generation=? AND lease_expires_at>?",
            (
                status,
                stage,
                timestamp(),
                claim.job_id,
                claim.user_id,
                claim.attempt,
                claim.owner,
                claim.token,
                claim.generation,
                timestamp(),
            ),
        ).rowcount
        if changed != 1:
            return False
        if current["reservation_active"] and not charged:
            self._change_credits(
                conn,
                user_id=claim.user_id,
                delta=1,
                reason="job_cancelled_before_dispatch_refund",
                idempotency_key=f"job:{claim.job_id}:refund:{claim.attempt}",
                mandatory=True,
            )
        if charged:
            provider_changed = conn.execute(
                "UPDATE provider_attempts SET outcome='cancelled',completed_at=? "
                "WHERE job_id=? AND attempt=? AND lease_generation=? AND outcome='dispatched'",
                (timestamp(), claim.job_id, claim.attempt, claim.generation),
            ).rowcount
            if provider_changed != 1:
                raise RuntimeError("Provider attempt changed during cancelled terminal commit")
        self._audit(
            conn,
            user_id=claim.user_id,
            job_id=claim.job_id,
            event_type="job_cancelled",
            details={
                "preserved_status": preserved_status,
                "provider_dispatched": charged,
                "credit_refunded": bool(current["reservation_active"] and not charged),
                "execution_generation": claim.generation,
            },
        )
        return True

    def _finish_cancelled_queued_in_transaction(
        self, conn: sqlite3.Connection, current: sqlite3.Row
    ) -> bool:
        preserved_status = self._preserved_result_status(current)
        status = preserved_status or "cancelled"
        stage = (
            "Reprocess cancelled; previous approval retained"
            if preserved_status == "approved"
            else "Reprocess cancelled; previous review retained"
            if preserved_status == "review"
            else "Cancelled"
        )
        changed = conn.execute(
            "UPDATE jobs SET status=?,progress_stage=?,reservation_active=0,cancel_requested=0,"
            "result_reservation_bytes=0,result_reservation_attempt=NULL,"
            "retained_byte_reservation=0,updated_at=? "
            "WHERE id=? AND user_id=? AND attempt=? AND status='queued'",
            (
                status,
                stage,
                timestamp(),
                current["id"],
                current["user_id"],
                current["attempt"],
            ),
        ).rowcount
        if changed != 1:
            return False
        if current["reservation_active"]:
            self._change_credits(
                conn,
                user_id=current["user_id"],
                delta=1,
                reason="job_cancelled_before_dispatch_refund",
                idempotency_key=f"job:{current['id']}:refund:{current['attempt']}",
                mandatory=True,
            )
        self._audit(
            conn,
            user_id=current["user_id"],
            job_id=current["id"],
            event_type="job_cancelled",
            details={"preserved_status": preserved_status, "credit_refunded": True},
        )
        return True

    @staticmethod
    def _preserved_result_status(current: sqlite3.Row) -> str | None:
        if not current["current_result_json"]:
            return None
        return "approved" if current["approved_at"] else "review"

    def _retire_legacy_shared_demo(self) -> None:
        """Remove the pre-v0.2.1 shared demo tenant and revoke all of its sessions."""

        retired = False
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute("SELECT id FROM users WHERE email='demo@unrender.local'").fetchone()
            if row:
                self._queue_user_deletion(conn, str(row["id"]), "legacy_shared_demo_retired")
                retired = True
        if retired:
            self.drain_deletion_queue()

    def reconcile_storage(self) -> int:
        """Queue product-owned files that no longer have a database owner."""

        with self.database.connect() as conn:
            referenced = {
                str(Path(row["path"]).resolve())
                for row in conn.execute(
                    "SELECT storage_path AS path FROM uploads "
                    "UNION SELECT source_path AS path FROM jobs "
                    "UNION SELECT storage_path AS path FROM pending_deletions "
                    "UNION SELECT storage_path AS path FROM storage_reservations "
                    "WHERE storage_path IS NOT NULL"
                ).fetchall()
            }
        orphans = [
            path
            for path in self.storage.object_paths(
                older_than_seconds=self.settings.reconciliation_grace_seconds
            )
            if str(path.resolve()) not in referenced
        ]
        if not orphans:
            return 0
        with self.database.transaction(immediate=True) as conn:
            for path in orphans:
                if self._path_is_referenced(conn, str(path)):
                    continue
                self._queue_deletion(conn, path, "orphan_reconciliation")
        return len(orphans)

    def recover_interrupted_jobs(self) -> int:
        recovered = 0
        now = timestamp()
        with self.database.transaction(immediate=True) as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status='running' "
                "AND (lease_expires_at IS NULL OR lease_expires_at<=?)",
                (now,),
            ).fetchall()
            for row in rows:
                identity = (
                    row["id"],
                    row["user_id"],
                    row["attempt"],
                    row["lease_generation"],
                    row["worker_owner"],
                    row["lease_token"],
                    now,
                )
                recovery_count = int(row["recovery_count"])
                charged = bool(row["provider_dispatched"])
                should_requeue = (
                    not row["cancel_requested"]
                    and not charged
                    and recovery_count < self.settings.max_recovery_attempts
                )
                if should_requeue:
                    changed = conn.execute(
                        "UPDATE jobs SET status='queued',recovery_count=recovery_count+1,"
                        "progress_stage='Recovered after expired worker lease',worker_owner=NULL,"
                        "lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=? "
                        "WHERE id=? AND user_id=? AND attempt=? AND lease_generation=? "
                        "AND worker_owner IS ? AND lease_token IS ? AND status='running' "
                        "AND (lease_expires_at IS NULL OR lease_expires_at<=?)",
                        (now, *identity),
                    ).rowcount
                    if changed != 1:
                        continue
                    self._audit(
                        conn,
                        user_id=row["user_id"],
                        job_id=row["id"],
                        event_type="job_recovered",
                        details={
                            "recovery": recovery_count + 1,
                            "expired_execution_generation": row["lease_generation"],
                        },
                    )
                    recovered += 1
                    continue
                preserved_status = self._preserved_result_status(row)
                cancelled = bool(row["cancel_requested"])
                status = preserved_status or ("cancelled" if cancelled else "failed")
                code = (
                    None
                    if cancelled
                    else "worker_lease_expired_after_dispatch"
                    if charged
                    else "worker_recovery_exhausted"
                )
                message = (
                    None
                    if cancelled
                    else "The worker lease expired after provider dispatch. The attempt was not "
                    "redriven or refunded because provider spend may have occurred."
                    if charged
                    else "The worker stopped repeatedly before provider dispatch. The reserved "
                    "credit was returned; retry after reviewing worker health."
                )
                stage = (
                    "Previous reviewed result retained"
                    if preserved_status
                    else "Cancelled after worker lease expiry"
                    if cancelled
                    else "Automatic recovery stopped"
                )
                changed = conn.execute(
                    "UPDATE jobs SET status=?,reservation_active=0,cancel_requested=0,"
                    "progress_stage=?,error_code=?,error_message=?,worker_owner=NULL,"
                    "lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,"
                    "result_reservation_bytes=0,result_reservation_attempt=NULL,"
                    "retained_byte_reservation=0,updated_at=? "
                    "WHERE id=? AND user_id=? AND attempt=? AND lease_generation=? "
                    "AND worker_owner IS ? AND lease_token IS ? AND status='running' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at<=?)",
                    (status, stage, code, message, now, *identity),
                ).rowcount
                if changed != 1:
                    continue
                refunded = bool(row["reservation_active"] and not charged)
                if refunded:
                    self._change_credits(
                        conn,
                        user_id=row["user_id"],
                        delta=1,
                        reason=(
                            "job_cancelled_before_dispatch_refund"
                            if cancelled
                            else "job_recovery_exhausted_refund"
                        ),
                        idempotency_key=f"job:{row['id']}:refund:{row['attempt']}",
                        mandatory=True,
                    )
                if charged:
                    provider_changed = conn.execute(
                        "UPDATE provider_attempts SET outcome=?,completed_at=? WHERE job_id=? "
                        "AND attempt=? AND lease_generation=? AND outcome='dispatched'",
                        (
                            "cancelled" if cancelled else "failed",
                            now,
                            row["id"],
                            row["attempt"],
                            row["lease_generation"],
                        ),
                    ).rowcount
                    if provider_changed != 1:
                        raise RuntimeError(
                            "Provider attempt changed during recovery terminal commit"
                        )
                self._audit(
                    conn,
                    user_id=row["user_id"],
                    job_id=row["id"],
                    event_type="job_cancelled" if cancelled else "job_recovery_exhausted",
                    details={
                        "recovery_count": recovery_count,
                        "provider_dispatched": charged,
                        "credit_refunded": refunded,
                        "expired_execution_generation": row["lease_generation"],
                    },
                )
                recovered += 1
        return recovered

    def cleanup_expired(self) -> dict[str, int]:
        expired_reservations = self.cleanup_storage_reservations()
        now = timestamp()
        cutoff = timestamp(utcnow() - timedelta(days=self.settings.retention_days))
        demo_cutoff = timestamp(utcnow() - timedelta(hours=self.settings.session_ttl_hours))
        idempotency_tombstone_cutoff = timestamp(
            utcnow() - timedelta(days=self.settings.idempotency_tombstone_days)
        )
        upload_paths: list[str] = []
        job_paths: list[str] = []
        demo_users = 0
        with self.database.transaction(immediate=True) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            conn.execute("DELETE FROM account_challenges WHERE expires_at<=?", (now,))
            audit_users = conn.execute(
                "SELECT DISTINCT user_id FROM audit_events WHERE user_id IS NOT NULL"
            ).fetchall()
            audit_cutoff = timestamp(utcnow() - timedelta(days=self.settings.audit_retention_days))
            for audit_user in audit_users:
                self._rollup_audit_events(
                    conn, user_id=str(audit_user["user_id"]), before=audit_cutoff
                )
            conn.execute("DELETE FROM audit_events WHERE user_id IS NULL AND job_id IS NULL")
            expired_uploads = conn.execute(
                "SELECT storage_path,user_id,byte_size FROM uploads WHERE expires_at<=?", (now,)
            ).fetchall()
            upload_paths = [row["storage_path"] for row in expired_uploads]
            for row in expired_uploads:
                self._queue_deletion(
                    conn,
                    row["storage_path"],
                    "upload_expired",
                    user_id=str(row["user_id"]),
                    byte_size=int(row["byte_size"]),
                )
            conn.execute("DELETE FROM uploads WHERE expires_at<=?", (now,))
            expired_jobs = conn.execute(
                "SELECT source_path,user_id,source_byte_size FROM jobs "
                "WHERE updated_at<? AND status NOT IN ('queued','running')",
                (cutoff,),
            ).fetchall()
            job_paths = [row["source_path"] for row in expired_jobs]
            for row in expired_jobs:
                self._queue_deletion(
                    conn,
                    row["source_path"],
                    "job_retention_expired",
                    user_id=str(row["user_id"]),
                    byte_size=int(row["source_byte_size"]),
                )
            conn.execute(
                "DELETE FROM jobs WHERE updated_at<? AND status NOT IN ('queued','running')",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM rate_limits WHERE window_start<?",
                (int(utcnow().timestamp()) - 3600,),
            )
            conn.execute(
                "UPDATE api_idempotency SET response_json=NULL,expired_at=expires_at "
                "WHERE expires_at<=? AND expired_at IS NULL",
                (now,),
            )
            conn.execute(
                "DELETE FROM api_idempotency WHERE expired_at<?",
                (idempotency_tombstone_cutoff,),
            )
            expired_demo_users = conn.execute(
                "SELECT users.id FROM users LEFT JOIN sessions ON sessions.user_id=users.id "
                "WHERE users.account_kind='demo' AND users.created_at<? "
                "GROUP BY users.id HAVING COUNT(sessions.id)=0",
                (demo_cutoff,),
            ).fetchall()
            for row in expired_demo_users:
                self._queue_user_deletion(conn, str(row["id"]), "demo_session_expired")
            demo_users = len(expired_demo_users)
        self.reconcile_storage()
        self.drain_deletion_queue()
        return {
            "uploads": len(upload_paths),
            "jobs": len(job_paths),
            "demo_users": demo_users,
            "storage_reservations": expired_reservations,
        }

    def rate_limit(
        self,
        bucket_key: str,
        *,
        limit: int | None = None,
        amount: int = 1,
    ) -> bool:
        effective_limit = limit or self.settings.rate_limit_per_minute
        if amount <= 0:
            raise ValueError("Rate-limit amount must be positive")
        window = int(utcnow().timestamp()) // 60 * 60
        with self.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT request_count FROM rate_limits WHERE bucket_key=? AND window_start=?",
                (bucket_key, window),
            ).fetchone()
            count = int(row["request_count"]) + amount if row else amount
            if row:
                conn.execute(
                    "UPDATE rate_limits SET request_count=? WHERE bucket_key=? AND window_start=?",
                    (count, bucket_key, window),
                )
            else:
                try:
                    self._insert_row(
                        conn,
                        "INSERT INTO rate_limits(bucket_key,window_start,request_count) "
                        "VALUES (?,?,?)",
                        (bucket_key, window, count),
                        user_id=None,
                    )
                except ProductError:
                    return False
        return count <= effective_limit
