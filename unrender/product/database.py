"""Small SQLite persistence layer with explicit migrations and transactions."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

SCHEMA_VERSION = 6


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    account_kind TEXT NOT NULL DEFAULT 'customer'
        CHECK (account_kind IN ('customer','demo')),
    credit_balance INTEGER NOT NULL DEFAULT 0 CHECK (credit_balance >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    upload_id TEXT REFERENCES uploads(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_mime TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_byte_size INTEGER NOT NULL DEFAULT 0 CHECK (source_byte_size >= 0),
    page_index INTEGER NOT NULL DEFAULT 0,
    crop_json TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('queued','running','review','approved','failed','cancelled')
    ),
    progress_stage TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    recovery_count INTEGER NOT NULL DEFAULT 0 CHECK (recovery_count >= 0),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    reservation_active INTEGER NOT NULL DEFAULT 1 CHECK (reservation_active IN (0,1)),
    provider_dispatched INTEGER NOT NULL DEFAULT 0 CHECK (provider_dispatched IN (0,1)),
    provider_dispatched_at TEXT,
    worker_owner TEXT,
    lease_token TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    extractor TEXT,
    model_version TEXT,
    raw_result TEXT,
    original_result_json TEXT,
    current_result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS jobs_user_created_idx ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_status_created_idx ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS jobs_lease_expiry_idx ON jobs(status, lease_expires_at);

CREATE TABLE IF NOT EXISTS result_versions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('extraction','correction','reprocess')),
    chart_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, version)
);

CREATE INDEX IF NOT EXISTS result_versions_user_idx ON result_versions(user_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_job_created_idx ON audit_events(job_id, created_at);
CREATE INDEX IF NOT EXISTS audit_user_created_idx
ON audit_events(user_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS audit_rollups (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    job_scope TEXT NOT NULL,
    event_type TEXT NOT NULL,
    day TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK (event_count > 0),
    first_at TEXT NOT NULL,
    last_at TEXT NOT NULL,
    PRIMARY KEY(user_id, job_scope, event_type, day),
    CHECK (
        (job_id IS NULL AND job_scope='account') OR
        (job_id IS NOT NULL AND job_scope=job_id)
    )
);

CREATE TABLE IF NOT EXISTS credit_ledger (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS billing_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_attempts (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    lease_generation INTEGER NOT NULL,
    dispatched_at TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'dispatched'
        CHECK (outcome IN ('dispatched','succeeded','failed','cancelled')),
    completed_at TEXT,
    PRIMARY KEY(job_id, attempt, lease_generation)
);
CREATE INDEX IF NOT EXISTS provider_attempts_failure_idx
ON provider_attempts(user_id, outcome, completed_at);

CREATE TABLE IF NOT EXISTS rate_limits (
    bucket_key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL,
    PRIMARY KEY(bucket_key, window_start)
);

CREATE TABLE IF NOT EXISTS pending_deletions (
    storage_path TEXT PRIMARY KEY,
    user_id TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    reason TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_idempotency (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    expires_at TEXT NOT NULL,
    expired_at TEXT,
    PRIMARY KEY(user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS api_idempotency_expiry_idx
ON api_idempotency(user_id, expired_at);

CREATE TABLE IF NOT EXISTS startup_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    last_reconciled_at TEXT
);
INSERT OR IGNORE INTO startup_state(singleton,last_reconciled_at) VALUES (1,NULL);

"""


def _execute_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a simple DDL script without ``executescript``'s implicit COMMIT."""

    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            statement = ""
            if sql:
                conn.execute(sql)
    if statement.strip():
        raise RuntimeError("Incomplete database schema statement")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._migration_fault_hook: Callable[[], None] | None = None

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        with self.migration_lock():
            conn = self.connect()
            try:
                conn.execute("BEGIN EXCLUSIVE")
                self._initialize_in_transaction(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        if not Database._table_exists(conn, table):
            return set()
        return {str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{table}")')}

    @staticmethod
    def _add_column(conn: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
        if name not in Database._columns(conn, table):
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}')

    def _migration_execute(
        self,
        conn: sqlite3.Connection,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute one migration statement and expose a test-only post-statement crash seam."""

        cursor = conn.execute(sql, parameters)
        hook = self._migration_fault_hook
        if hook is not None:
            hook()
        return cursor

    def _infer_legacy_version(self, conn: sqlite3.Connection) -> int:
        jobs = self._columns(conn, "jobs")
        idempotency = self._columns(conn, "api_idempotency")
        pending = self._columns(conn, "pending_deletions")
        if "lease_generation" in jobs:
            return 6
        if {"expires_at", "expired_at"}.issubset(idempotency):
            return 5
        if {"user_id", "byte_size"}.issubset(pending):
            return 4
        if "source_byte_size" in jobs:
            return 3
        if "recovery_count" in jobs:
            return 2
        return 1

    def _initialize_in_transaction(self, conn: sqlite3.Connection) -> None:
        has_meta = self._table_exists(conn, "schema_meta")
        has_jobs = self._table_exists(conn, "jobs")
        if not has_meta and not has_jobs:
            _execute_script(conn, SCHEMA)
            conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            return
        if not has_meta:
            conn.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        rows = conn.execute("SELECT version FROM schema_meta").fetchall()
        if not rows:
            conn.execute(
                "INSERT INTO schema_meta(version) VALUES (?)", (self._infer_legacy_version(conn),)
            )
        elif len(rows) != 1:
            raise RuntimeError("Database schema metadata must contain exactly one row")

        while True:
            version = int(conn.execute("SELECT version FROM schema_meta").fetchone()["version"])
            if version == 1:
                self._migrate_v1_to_v2(conn)
            elif version == 2:
                self._migrate_v2_to_v3(conn)
            elif version == 3:
                self._migrate_v3_to_v4(conn)
            elif version == 4:
                self._migrate_v4_to_v5(conn)
            elif version == 5:
                self._migrate_v5_to_v6(conn)
            elif version == SCHEMA_VERSION:
                break
            else:
                raise RuntimeError(
                    f"Database schema {version} is not supported; expected {SCHEMA_VERSION}"
                )
        self._ensure_v6_shape(conn)
        _execute_script(conn, SCHEMA)

    def _ensure_v6_shape(self, conn: sqlite3.Connection) -> None:
        """Repair the only pre-release v6 shape that existed before audit rollups were final."""

        if not self._table_exists(conn, "audit_rollups"):
            return
        if "job_scope" in self._columns(conn, "audit_rollups"):
            return
        conn.execute("ALTER TABLE audit_rollups RENAME TO audit_rollups_v6_old")
        conn.execute(
            "CREATE TABLE audit_rollups ("
            "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,job_scope TEXT NOT NULL,"
            "event_type TEXT NOT NULL,day TEXT NOT NULL,event_count INTEGER NOT NULL "
            "CHECK (event_count > 0),first_at TEXT NOT NULL,last_at TEXT NOT NULL,"
            "PRIMARY KEY(user_id,job_scope,event_type,day),"
            "CHECK ((job_id IS NULL AND job_scope='account') OR "
            "(job_id IS NOT NULL AND job_scope=job_id)))"
        )
        conn.execute(
            "INSERT INTO audit_rollups("
            "user_id,job_id,job_scope,event_type,day,event_count,first_at,last_at"
            ") SELECT user_id,job_id,COALESCE(job_id,'account'),event_type,day,"
            "SUM(event_count),MIN(first_at),MAX(last_at) FROM audit_rollups_v6_old "
            "GROUP BY user_id,COALESCE(job_id,'account'),event_type,day"
        )
        conn.execute("DROP TABLE audit_rollups_v6_old")

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        self._add_column(
            conn,
            "users",
            "account_kind",
            "TEXT NOT NULL DEFAULT 'customer' CHECK (account_kind IN ('customer','demo'))",
        )
        self._add_column(
            conn,
            "jobs",
            "recovery_count",
            "INTEGER NOT NULL DEFAULT 0 CHECK (recovery_count >= 0)",
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pending_deletions ("
            "storage_path TEXT PRIMARY KEY,user_id TEXT,byte_size INTEGER NOT NULL DEFAULT 0 "
            "CHECK (byte_size >= 0),reason TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0 "
            "CHECK (attempts >= 0),last_error TEXT,created_at TEXT NOT NULL,"
            "updated_at TEXT NOT NULL)"
        )
        conn.execute("UPDATE schema_meta SET version=2")

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        self._add_column(
            conn,
            "jobs",
            "source_byte_size",
            "INTEGER NOT NULL DEFAULT 0 CHECK (source_byte_size >= 0)",
        )
        conn.execute(
            "UPDATE jobs SET source_byte_size=COALESCE((SELECT uploads.byte_size FROM uploads "
            "WHERE uploads.id=jobs.upload_id),0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS api_idempotency ("
            "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "idempotency_key TEXT NOT NULL,request_sha256 TEXT NOT NULL,response_json TEXT,"
            "created_at TEXT NOT NULL,completed_at TEXT,PRIMARY KEY(user_id,idempotency_key))"
        )
        conn.execute("UPDATE schema_meta SET version=3")

    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        self._add_column(conn, "pending_deletions", "user_id", "TEXT")
        self._add_column(
            conn,
            "pending_deletions",
            "byte_size",
            "INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0)",
        )
        conn.execute("UPDATE schema_meta SET version=4")

    def _migrate_v4_to_v5(self, conn: sqlite3.Connection) -> None:
        replacement = "api_idempotency_v5_new"
        self._migration_execute(conn, f'DROP TABLE IF EXISTS "{replacement}"')
        self._migration_execute(
            conn,
            f'CREATE TABLE "{replacement}" ('
            "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "idempotency_key TEXT NOT NULL,request_sha256 TEXT NOT NULL,response_json TEXT,"
            "created_at TEXT NOT NULL,completed_at TEXT,expires_at TEXT NOT NULL,"
            "expired_at TEXT,PRIMARY KEY(user_id,idempotency_key))",
        )
        for source in ("api_idempotency", "api_idempotency_v4"):
            columns = self._columns(conn, source)
            required = {
                "user_id",
                "idempotency_key",
                "request_sha256",
                "response_json",
                "created_at",
                "completed_at",
            }
            if not required.issubset(columns):
                continue
            expires = (
                "COALESCE(expires_at, strftime('%Y-%m-%dT%H:%M:%fZ', created_at, '+30 days'))"
                if "expires_at" in columns
                else "strftime('%Y-%m-%dT%H:%M:%fZ', created_at, '+30 days')"
            )
            expired = "expired_at" if "expired_at" in columns else "NULL"
            self._migration_execute(
                conn,
                f'INSERT OR IGNORE INTO "{replacement}"('  # noqa: S608 -- migration identifiers are closed constants
                "user_id,idempotency_key,request_sha256,response_json,created_at,completed_at,"
                "expires_at,expired_at) "
                f"SELECT user_id,idempotency_key,request_sha256,response_json,created_at,"
                f'completed_at,{expires},{expired} FROM "{source}"',
            )
        for source in ("api_idempotency", "api_idempotency_v4"):
            if self._table_exists(conn, source):
                self._migration_execute(conn, f'DROP TABLE "{source}"')
        self._migration_execute(
            conn,
            f'ALTER TABLE "{replacement}" RENAME TO api_idempotency',
        )
        self._migration_execute(conn, "UPDATE schema_meta SET version=5")

    def _migrate_v5_to_v6(self, conn: sqlite3.Connection) -> None:
        job_columns = {
            "provider_dispatched": (
                "INTEGER NOT NULL DEFAULT 0 CHECK (provider_dispatched IN (0,1))"
            ),
            "provider_dispatched_at": "TEXT",
            "worker_owner": "TEXT",
            "lease_token": "TEXT",
            "lease_generation": "INTEGER NOT NULL DEFAULT 0 CHECK (lease_generation >= 0)",
            "lease_expires_at": "TEXT",
            "heartbeat_at": "TEXT",
        }
        for name, declaration in job_columns.items():
            self._add_column(conn, "jobs", name, declaration)
        conn.execute("UPDATE schema_meta SET version=6")

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        if not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if candidate.exists():
                os.chmod(candidate, 0o600)
        return conn

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self.operational_lock():
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def _file_lock(
        self,
        suffix: str,
        *,
        exclusive: bool,
        timeout_seconds: float = 10.0,
    ) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.parent / suffix
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        try:
            while True:
                try:
                    fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring {suffix}") from None
                    time.sleep(0.025)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def migration_lock(self) -> AbstractContextManager[None]:
        return self._file_lock(".migration.lock", exclusive=True, timeout_seconds=30)

    def startup_lock(self) -> AbstractContextManager[None]:
        return self._file_lock(".startup.lock", exclusive=True, timeout_seconds=30)

    def operational_lock(
        self, *, exclusive: bool = False, timeout_seconds: float = 10.0
    ) -> AbstractContextManager[None]:
        return self._file_lock(
            ".operations.lock", exclusive=exclusive, timeout_seconds=timeout_seconds
        )

    def ready(self) -> bool:
        try:
            with self.connect() as conn:
                row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
                return bool(row and row["version"] == SCHEMA_VERSION)
        except sqlite3.Error:
            return False
