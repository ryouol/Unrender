"""Session-only library routes kept separate from extraction transport."""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from unrender.product.library import ChartLibrary
from unrender.product.service import ProductService


class ProjectName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


class ChartMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=80)


def install_library_routes(
    app: FastAPI, service: ProductService, current_user: Any, csrf_user: Any
) -> None:
    library = ChartLibrary(service)

    @app.get("/api/projects")
    def list_projects(user: Any = current_user):
        return library.list_projects(user["id"])

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, user: Any = current_user):
        return library.get_project(user["id"], project_id)

    @app.post("/api/projects", status_code=201)
    def create_project(payload: ProjectName, user: Any = csrf_user):
        return library.create_project(user["id"], payload.name)

    @app.patch("/api/projects/{project_id}")
    def rename_project(project_id: str, payload: ProjectName, user: Any = csrf_user):
        return library.rename_project(user["id"], project_id, payload.name)

    @app.patch("/api/jobs/{job_id}")
    def update_chart(job_id: str, payload: ChartMetadata, user: Any = csrf_user):
        return library.update_chart(user["id"], job_id, payload.model_dump(exclude_unset=True))
