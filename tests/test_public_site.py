"""Regression contract for public documents; private APIs stay machine-readable."""

import subprocess
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


def test_landing_and_account_shells_stay_separate_and_private(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        environment="test",
        worker_enabled=False,
        seed_demo_account=False,
        allow_registration=False,
        initial_credits=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        service = app.state.service
        user_id = service.provision_user(
            "private-owner@example.com", "a private long password", credits=2
        )
        session = service.create_session(user_id)
        client.cookies.set("unrender_session", session["session"])

        landing_response = client.get("/")
        landing = BeautifulSoup(landing_response.text, "html.parser")
        assert landing.find(id="landing-title")
        assert not landing.select('input[type="password"], #workspace-view')
        assert landing.select_one('a[href="/login"]')
        assert landing.select_one('a[href="/signup"]')
        assert landing.select_one('script[src="/static/landing.js"]')
        assert not landing.select_one('script[src="/static/app.js"]')
        assert "noindex" not in landing_response.headers.get("x-robots-tag", "")

        for path in ("/login", "/signup", "/app", "/account"):
            response = client.get(path)
            page = BeautifulSoup(response.text, "html.parser")
            assert response.status_code == 200
            assert "noindex" in response.headers["x-robots-tag"]
            assert "noindex" in page.select_one('meta[name="robots"]')["content"]
            assert page.select_one('link[rel="canonical"]')["href"] == settings.base_url + path
            assert not page.find(id="landing-example-dialog")
            assert not page.select_one('script[src="/static/landing.js"]')
            if path == "/account":
                assert page.find(id="account-form")
                assert page.select_one('script[src="/static/account.js"]')
            else:
                assert page.find(id="login-form") and page.find(id="register-form")
                assert page.find(id="workspace-view").has_attr("hidden")
                assert page.select_one('script[src="/static/app.js"]')
            assert "private-owner@example.com" not in response.text
            assert session["session"] not in response.text
            assert "set-cookie" not in response.headers

        assert service.account(user_id)["credits"] == 2
        with service.database.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
        config = client.get("/api/public-config").json()
        assert config["registration_open"] is False
        assert config["sample_available"] is False
        assert config["email_available"] is False
        assert config["initial_credits"] == 0


def test_new_shell_assets_are_served_locally(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, environment="test", worker_enabled=False))
    with TestClient(app) as client:
        assets = set()
        for path in ("/", "/login", "/signup", "/app", "/account"):
            page = BeautifulSoup(client.get(path).text, "html.parser")
            for node in page.select('script[src], img[src], link[rel="stylesheet"]'):
                source = node.get("src") or node["href"]
                assert source.startswith("/static/"), source
                assets.add(source)
            assert len(page.select('script[src="/static/theme.js"]')) == 1
        assert {
            "/static/landing.js",
            "/static/landing.css",
            "/static/theme.js",
            "/static/icons/icon-192.png",
            "/static/demo/revenue-example.png",
        }.issubset(assets)
        for asset in assets:
            response = client.get(asset)
            assert response.status_code == 200, asset
            assert response.content, asset
            assert not response.headers["content-type"].startswith("text/html"), asset


def test_browser_landing_example_requires_saved_approval_and_stays_local() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "unrender/product/static"
    for filename in ("theme.js", "landing.js"):
        subprocess.run(
            ["node", "--check", str(static_dir / filename)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("browser_landing.mjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_browser_account_help_stays_available_without_email() -> None:
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("browser_account.mjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout
