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
        self.service.require_customer_account(user_id, "projects")
        project_id, now = self.service._id(), timestamp()
        with self.service.database.transaction(immediate=True) as conn:
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
            return public_job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
