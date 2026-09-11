"""Cached, anonymous operational checks, separate from restart readiness."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta

from unrender.product.config import Settings


class OperationsProbe:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._checked_at = float("-inf")
        self._checks: dict[str, bool] = {}

    def check(self) -> dict[str, bool]:
        # Public requests share one bounded scan per minute, including failures.
        if not self._lock.acquire(blocking=False):
            return {"probe_available": False}
        try:
            if time.monotonic() - self._checked_at >= 60:
                try:
                    self._checks = self._read_checks()
                except (OSError, sqlite3.Error, ValueError):
                    self._checks = {"probe_available": False}
                self._checked_at = time.monotonic()
            return dict(self._checks)
        finally:
            self._lock.release()

    def _read_checks(self) -> dict[str, bool]:
        now = datetime.now(UTC)
        hour = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        queue_cutoff = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        deadline = time.monotonic() + 2
        uri = self.settings.database_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as conn:
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            conn.execute("BEGIN")
            queue_delayed = conn.execute(
                "SELECT 1 FROM jobs j WHERE status IN ('queued','running') AND "
                "CASE WHEN status='queued' THEN updated_at "
                "ELSE COALESCE(provider_dispatched_at,(SELECT MAX(a.created_at) "
                "FROM audit_events a WHERE a.job_id=j.id AND a.event_type='job_started' "
                "AND json_extract(a.details_json,'$.attempt')=j.attempt "
                "AND json_extract(a.details_json,'$.execution_generation')=j.lease_generation),"
                "'1970-01-01T00:00:00Z') END<? LIMIT 1",
                (queue_cutoff,),
            ).fetchone()
            failures = conn.execute(
                "SELECT COUNT(*) FROM (SELECT 1 FROM provider_attempts "
                "WHERE outcome='failed' AND completed_at>=? LIMIT 3)",
                (hour,),
            ).fetchone()[0]
            slow = conn.execute(
                "SELECT 1 FROM provider_attempts WHERE completed_at>=? "
                "AND (julianday(completed_at)-julianday(dispatched_at))*86400>180 LIMIT 1",
                (hour,),
            ).fetchone()
            ledger_drift = conn.execute(
                "SELECT 1 FROM users u LEFT JOIN "
                "(SELECT user_id,SUM(delta) AS balance FROM credit_ledger GROUP BY user_id) l "
                "ON l.user_id=u.id WHERE u.credit_balance!=COALESCE(l.balance,0) LIMIT 1"
            ).fetchone()
        return {
            "queue_timely": queue_delayed is None,
            "provider_failures_below_threshold": failures < 3,
            "provider_latency_below_threshold": slow is None,
            "credit_ledger_consistent": ledger_drift is None,
            "backup_recent": self._backup_recent(now.timestamp()),
        }

    def _backup_recent(self, now: float) -> bool:
        if not self.settings.backup_volume_name:
            return True
        try:
            with (self.settings.data_dir / "backup-status.json").open("rb") as source:
                value = json.loads(source.read(4097))["last_success"]
            return (
                type(value) in (int, float)
                and math.isfinite(value)
                and 0 <= now - value < 48 * 60 * 60
            )
        except (OSError, ValueError, KeyError, TypeError):
            return False
