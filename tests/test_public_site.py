"""Regression contract for public documents; private APIs stay machine-readable."""

from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from unrender.product.config import Settings
from unrender.product.public_site import PAGES
from unrender.product.web import create_app


def test_public_document_links_metadata_and_private_sitemap(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, environment="test", worker_enabled=False))
    with TestClient(app) as client:
        titles = set()
        for path in PAGES:
            response = client.get(path)
            assert response.status_code == 200
            page = BeautifulSoup(response.text, "html.parser")
            titles.add(page.title.text)
            if path != "/":
                assert "noindex" in response.headers["x-robots-tag"]
                assert "noindex" in page.find("meta", attrs={"name": "robots"})["content"]
            assert page.find("meta", attrs={"name": "description"})["content"]
            for prop in ("og:title", "og:description", "og:url", "og:image"):
                assert page.find("meta", attrs={"property": prop})["content"]
            assert page.find("meta", attrs={"name": "twitter:image"})
            assert str(date.today().year) in page.footer.text
            assert page.find(id="cookie-notice").has_attr("hidden")
            for link in page.select("footer a[href], link[rel=icon], link[rel=apple-touch-icon]"):
                assert client.get(link["href"]).status_code == 200
        assert len(titles) == len(PAGES)
        sitemap = client.get("/sitemap.xml")
        locations = ElementTree.fromstring(sitemap.text).findall(
            ".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
        )
        assert {node.text for node in locations} == {"http://127.0.0.1:8000/"}
        assert "Disallow: /api/" in client.get("/robots.txt").text
        assert client.get("/api/me").status_code == 401
        assert (
            client.get("/api/does-not-exist").headers["content-type"].startswith("application/json")
        )
        missing = client.get("/does-not-exist")
        assert missing.status_code == 404
        assert "Return home" in missing.text
        assert missing.headers["x-content-type-options"] == "nosniff"


def test_browser_500_does_not_reveal_exception(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, environment="test", worker_enabled=False))

    @app.get("/broken-test-page")
    def broken():
        raise RuntimeError("secret-internal-test-marker")

    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.get("/broken-test-page", headers={"Accept": "text/html"})
        assert result.status_code == 500
        assert "Something went wrong" in result.text
        assert "secret-internal-test-marker" not in result.text
        assert "frame-ancestors 'none'" in result.headers["content-security-policy"]
