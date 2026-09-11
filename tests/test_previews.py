"""Thumbnails preserve source geometry, authorization, and browser resource bounds."""

import io
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_product import settings_for

from unrender.product.web import create_app


def test_preview_browser_queue() -> None:
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("browser_previews.mjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("cropped", [False, True])
def test_thumbnail_geometry_full_source_and_private_access(tmp_path, cropped):
    app = create_app(settings_for(tmp_path, seed_demo_account=False))
    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={"email": "owner@example.com", "password": "a long original password"},
        )
        owner = client.get("/api/me").json()["id"]
        output = io.BytesIO()
        Image.new("RGB", (2400, 1200), "white").save(output, format="PNG")
        upload = app.state.service.prepare_upload(
            user_id=owner, filename="large.png", content=output.getvalue()
        )
        job = app.state.service.create_job(
            user_id=owner,
            upload_id=upload["id"],
            page_index=0,
            crop={"x": 0, "y": 0, "width": 0.5, "height": 1} if cropped else None,
        )
        path = f"/api/jobs/{job['id']}/source"
        thumbnail = client.get(path + "?thumbnail=true")
        assert thumbnail.status_code == 200
        assert thumbnail.headers["cache-control"] == "no-store"
        assert thumbnail.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(thumbnail.content)) as image:
            assert image.size == ((640, 640) if cropped else (640, 320))
        full = client.get(path)
        with Image.open(io.BytesIO(full.content)) as image:
            assert image.size == ((1200, 1200) if cropped else (2200, 1100))
        assert client.get(path + "?thumbnail=false").content == full.content
        policy = thumbnail.headers["content-security-policy"]
        assert "img-src 'self' blob:;" in policy
        for guard in ("script-src 'self';", "connect-src 'self';", "object-src 'none';"):
            assert guard in policy
        assert "data:" not in policy
        assert client.get(path + "?thumbnail=invalid").status_code == 422
        client.cookies.clear()
        for suffix in ("", "?thumbnail=true"):
            assert client.get(path + suffix).status_code == 401
        client.post(
            "/api/auth/register",
            json={"email": "other@example.com", "password": "a long original password"},
        )
        for suffix in ("", "?thumbnail=true"):
            assert client.get(path + suffix).status_code == 404
