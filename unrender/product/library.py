"""Private chart organization and metadata, with bounded tenant-owned projects."""

from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any

from unrender.product.service import ProductError, ProductService, public_job, timestamp

MAX_PROJECTS = 50


def library_name(value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise ProductError("invalid_name", "Enter a name", 422)
    name = value.strip()
    if not 1 <= len(name) <= limit or any(
        unicodedata.category(character).startswith("C") for character in name
    ):
        raise ProductError(
            "invalid_name", f"Use 1–{limit} characters without control characters", 422
        )
    return name


class ChartLibrary:
    def __init__(self, service: ProductService):
        self.service = service

    @staticmethod
    def _project(conn: sqlite3.Connection, user_id: str, project_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT projects.*,COUNT(jobs.id) AS chart_count,"
            "COALESCE(SUM(jobs.status IN ('queued','running')),0) AS active_count "
            "FROM projects LEFT JOIN jobs ON jobs.project_id=projects.id AND jobs.user_id=? "
            "WHERE projects.id=? AND projects.user_id=? GROUP BY projects.id",
            (user_id, project_id, user_id),
        ).fetchone()
        if not row:
            raise ProductError("project_not_found", "Project not found", 404)
        project = dict(row)
        del project["user_id"]
        return project

    def list_projects(self, user_id: str) -> dict[str, Any]:
        with self.service.database.connect() as conn:
            rows = conn.execute(
                "SELECT projects.id,projects.name,projects.created_at,projects.updated_at,"
                "COUNT(jobs.id) AS chart_count,"
                "COALESCE(SUM(jobs.status IN ('queued','running')),0) AS active_count "
                "FROM projects LEFT JOIN jobs ON jobs.project_id=projects.id AND jobs.user_id=? "
                "WHERE projects.user_id=? GROUP BY projects.id "
                "ORDER BY projects.created_at DESC,projects.id LIMIT ?",
                (user_id, user_id, MAX_PROJECTS),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "limit": MAX_PROJECTS}

    def get_project(self, user_id: str, project_id: str) -> dict[str, Any]:
        with self.service.database.connect() as conn:
            return self._project(conn, user_id, project_id)

    def create_project(self, user_id: str, name: str) -> dict[str, Any]:
        name = library_name(name, 80)
        project_id, now = self.service._id(), timestamp()
        with self.service.database.transaction(immediate=True) as conn:
            self.service.require_customer_account(user_id, "projects")
            count = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            if count >= MAX_PROJECTS:
                raise ProductError(
                    "project_limit", "Delete an unused project before adding one", 429
                )
            self.service._insert_row(
                conn,
                "INSERT INTO projects(id,user_id,name,created_at,updated_at) VALUES (?,?,?,?,?)",
                (project_id, user_id, name, now, now),
                user_id=user_id,
            )
            self.service._audit(conn, user_id=user_id, event_type="project_created")
            return self._project(conn, user_id, project_id)

    def rename_project(self, user_id: str, project_id: str, name: str) -> dict[str, Any]:
        name = library_name(name, 80)
        with self.service.database.transaction(immediate=True) as conn:
            self._project(conn, user_id, project_id)
            conn.execute(
                "UPDATE projects SET name=?,updated_at=? WHERE id=? AND user_id=?",
                (name, timestamp(), project_id, user_id),
            )
            self.service._audit(conn, user_id=user_id, event_type="project_renamed")
            return self._project(conn, user_id, project_id)

    def update_chart(self, user_id: str, job_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes or changes.keys() - {"display_name", "project_id"}:
            raise ProductError("invalid_request", "Provide a chart name or project", 422)
        with self.service.database.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if not row:
                raise ProductError("job_not_found", "Extraction not found", 404)
            name = (
                library_name(changes["display_name"], 120)
                if "display_name" in changes
                else row["display_name"]
            )
            project_id = changes.get("project_id", row["project_id"])
            if project_id is not None:
                if not isinstance(project_id, str) or not 1 <= len(project_id) <= 80:
                    raise ProductError("invalid_request", "Choose a project", 422)
                self._project(conn, user_id, project_id)
            conn.execute(
                "UPDATE jobs SET display_name=?,project_id=?,updated_at=? WHERE id=? AND user_id=?",
                (name, project_id, timestamp(), job_id, user_id),
            )
            self.service._audit(
                conn,
                user_id=user_id,
                job_id=job_id,
                event_type="chart_metadata_changed",
                details={"fields": sorted(changes)},
            )
            return public_job(
                conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(),
                include_result=False,
            )

    def delete_project(
        self,
        user_id: str,
        project_id: str,
        *,
        mode: str,
        expected_chart_count: int | None,
    ) -> dict[str, Any]:
        if mode not in {"keep_charts", "delete_charts"}:
            raise ProductError(
                "invalid_request", "Choose whether to keep or delete the charts", 422
            )
        paths: list[str] = []
        with self.service.database.transaction(immediate=True) as conn:
            project = self._project(conn, user_id, project_id)
            count = project["chart_count"]
            if mode == "delete_charts":
                if expected_chart_count is None:
                    raise ProductError(
                        "invalid_request", "Confirm the number of charts to delete", 422
                    )
                if expected_chart_count != count:
                    raise ProductError(
                        "project_changed", "Charts changed. Review the project again", 409
                    )
                if project["active_count"]:
                    raise ProductError(
                        "project_busy", "Cancel active extractions before deleting", 409
                    )
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE project_id=? AND user_id=?", (project_id, user_id)
                ).fetchall()
                for row in rows:
                    paths.extend(self.service._delete_job_in_transaction(conn, row))
            conn.execute("DELETE FROM projects WHERE id=? AND user_id=?", (project_id, user_id))
            self.service._audit(
                conn,
                user_id=user_id,
                event_type="project_deleted",
                details={"mode": mode, "chart_count": count},
            )
        deleted = self.service.finish_file_deletion(paths)
        return {
            "status": "deleted" if deleted else "deletion_queued",
            "charts_deleted": count if mode == "delete_charts" else 0,
            "charts_kept": count if mode == "keep_charts" else 0,
        }
