"""Explicit account removal after recent authentication and safe work settlement."""

from __future__ import annotations

import sqlite3
from typing import Any

from unrender.product.service import ProductError, ProductService, timestamp


class AccountLifecycle:
    def __init__(self, service: ProductService):
        self.service = service

    @staticmethod
    def _summary(conn: sqlite3.Connection, user_id: str) -> dict[str, int]:
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM jobs WHERE user_id=users.id) AS charts,"
            "(SELECT COUNT(*) FROM projects WHERE user_id=users.id) AS projects,"
            "(SELECT COUNT(*) FROM jobs WHERE user_id=users.id AND status='running') "
            "AS running_extractions,"
            "(SELECT COUNT(*) FROM storage_reservations WHERE user_id=users.id AND expires_at>?) "
            "AS preparing_uploads FROM users WHERE id=? AND account_kind='customer'",
            (timestamp(), user_id),
        ).fetchone()
        if not row:
            raise ProductError("user_not_found", "Account not found", 404)
        return dict(row)

    def summary(self, user_id: str) -> dict[str, int]:
        with self.service.database.connect() as conn:
            return self._summary(conn, user_id)

    def delete_account(self, user_id: str, session_token: str) -> dict[str, Any]:
        with self.service.database.transaction(immediate=True) as conn:
            self.service.require_recent_auth(conn, user_id=user_id, session_token=session_token)
            summary = self._summary(conn, user_id)
            if summary["running_extractions"]:
                raise ProductError(
                    "account_busy",
                    "Cancel running extractions and wait for them to finish, then retry",
                    409,
                )
            if summary["preparing_uploads"]:
                raise ProductError(
                    "account_busy",
                    "An upload is being prepared. Wait for it to finish and retry",
                    409,
                )
            queued = conn.execute(
                "SELECT * FROM jobs WHERE user_id=? AND status='queued'", (user_id,)
            ).fetchall()
            for row in queued:
                self.service._finish_cancelled_queued_in_transaction(conn, row)

            # Release credential and audit capacity before creating deletion rows.
            # This whole transaction either commits removal or preserves the account.
            for table in ("sessions", "api_keys", "audit_events", "audit_rollups"):
                conn.execute(
                    f'DELETE FROM "{table}" WHERE user_id=?',  # noqa: S608 -- closed tuple
                    (user_id,),
                )
            jobs = conn.execute("SELECT * FROM jobs WHERE user_id=?", (user_id,)).fetchall()
            for row in jobs:
                self.service._delete_job_in_transaction(conn, row)
            uploads = conn.execute("SELECT * FROM uploads WHERE user_id=?", (user_id,)).fetchall()
            for row in uploads:
                self.service._delete_upload_in_transaction(conn, row)
            reservations = conn.execute(
                "SELECT * FROM storage_reservations WHERE user_id=?", (user_id,)
            ).fetchall()
            for row in reservations:
                if row["storage_path"]:
                    self.service._queue_deletion(
                        conn,
                        row["storage_path"],
                        "account_deleted",
                        user_id=user_id,
                        byte_size=int(row["byte_count"]),
                    )
                conn.execute("DELETE FROM storage_reservations WHERE id=?", (row["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            paths = [
                str(row["storage_path"])
                for row in conn.execute(
                    "SELECT storage_path FROM pending_deletions WHERE user_id=?", (user_id,)
                )
            ]
        deleted = self.service.finish_file_deletion(paths)
        return {
            "status": "deleted" if deleted else "deletion_queued",
            "charts_deleted": summary["charts"],
            "projects_deleted": summary["projects"],
        }
