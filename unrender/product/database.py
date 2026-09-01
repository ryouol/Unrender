"""Small SQLite persistence layer with explicit migrations and transactions."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 5


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

"""


MIGRATE_V1_TO_V2 = """
ALTER TABLE users ADD COLUMN account_kind TEXT NOT NULL DEFAULT 'customer'
    CHECK (account_kind IN ('customer','demo'));
ALTER TABLE jobs ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0
    CHECK (recovery_count >= 0);
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
UPDATE schema_meta SET version=2;
"""


MIGRATE_V2_TO_V3 = """
ALTER TABLE jobs ADD COLUMN source_byte_size INTEGER NOT NULL DEFAULT 0
    CHECK (source_byte_size >= 0);
UPDATE jobs SET source_byte_size=COALESCE(
    (SELECT uploads.byte_size FROM uploads WHERE uploads.id=jobs.upload_id), 0
);
CREATE TABLE IF NOT EXISTS api_idempotency (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY(user_id, idempotency_key)
);
UPDATE schema_meta SET version=3;
"""


MIGRATE_V3_TO_V4 = """
UPDATE schema_meta SET version=4;
"""


MIGRATE_V4_TO_V5 = """
ALTER TABLE api_idempotency RENAME TO api_idempotency_v4;
CREATE TABLE api_idempotency (
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
INSERT INTO api_idempotency(
    user_id,idempotency_key,request_sha256,response_json,created_at,completed_at,
    expires_at,expired_at
)
SELECT user_id,idempotency_key,request_sha256,response_json,created_at,completed_at,
       COALESCE(expires_at, strftime('%Y-%m-%dT%H:%M:%fZ', created_at, '+30 days')),
       expired_at
FROM api_idempotency_v4;
DROP TABLE api_idempotency_v4;
CREATE INDEX IF NOT EXISTS api_idempotency_expiry_idx
ON api_idempotency(user_id, expired_at);
UPDATE schema_meta SET version=5;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            while True:
                row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
                if row is None:
                    conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
                    break
                if row["version"] == 1:
                    conn.executescript(MIGRATE_V1_TO_V2)
                    continue
                if row["version"] == 2:
                    conn.executescript(MIGRATE_V2_TO_V3)
                    continue
                if row["version"] == 3:
                    columns = {
                        column["name"]
                        for column in conn.execute("PRAGMA table_info(pending_deletions)")
                    }
                    if "user_id" not in columns:
                        conn.execute("ALTER TABLE pending_deletions ADD COLUMN user_id TEXT")
                    if "byte_size" not in columns:
                        conn.execute(
                            "ALTER TABLE pending_deletions ADD COLUMN byte_size INTEGER "
                            "NOT NULL DEFAULT 0 CHECK (byte_size >= 0)"
                        )
                    conn.executescript(MIGRATE_V3_TO_V4)
                    continue
                if row["version"] == 4:
                    columns = {
                        column["name"]
                        for column in conn.execute("PRAGMA table_info(api_idempotency)")
                    }
                    if "expires_at" not in columns:
                        conn.execute("ALTER TABLE api_idempotency ADD COLUMN expires_at TEXT")
                    if "expired_at" not in columns:
                        conn.execute("ALTER TABLE api_idempotency ADD COLUMN expired_at TEXT")
                    conn.executescript(MIGRATE_V4_TO_V5)
                    continue
                if row["version"] == SCHEMA_VERSION:
                    break
                raise RuntimeError(
                    f"Database schema {row['version']} is not supported; expected {SCHEMA_VERSION}"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS api_idempotency_expiry_idx "
                "ON api_idempotency(user_id, expired_at)"
            )

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

    def ready(self) -> bool:
        try:
            with self.connect() as conn:
                row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
                return bool(row and row["version"] == SCHEMA_VERSION)
        except sqlite3.Error:
            return False
