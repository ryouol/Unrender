"""Public document shell; never renders tenant content or request-derived URLs."""

from datetime import date
from html import escape
from pathlib import Path

from fastapi.responses import HTMLResponse

PAGES = {
    "/account": (
        "account.html",
        "Account help — Unrender",
        "Verify your email or recover access to your workspace.",
    ),
    "/": (
        "landing.html",
        "Unrender — from chart to spreadsheet",
        "Review chart extraction against its source, correct the table, "
        "and export an auditable result.",
    ),
    "/app": ("index.html", "Workspace — Unrender", "Review, correct and export your chart data."),
    "/login": ("index.html", "Sign in — Unrender", "Sign in to your Unrender workspace."),
    "/signup": (
        "index.html",
        "Create a workspace — Unrender",
        "Start reviewing your chart data with Unrender.",
    ),
    "/privacy": (
        "privacy.html",
        "Privacy draft — Unrender",
        "How Unrender handles accounts, chart uploads, review records, "
        "retention, and test payments.",
    ),
    "/terms": (
        "terms.html",
        "Terms draft — Unrender",
        "Review responsibilities, permitted use, and limitations of the Unrender preview.",
    ),
    "/contact": (
        "contact.html",
        "Contact — Unrender",
        "Contact information and launch-readiness status for Unrender.",
    ),
}
INDEXABLE_PATHS = ("/",)


def document(static_dir: Path, path: str, base_url: str) -> HTMLResponse:
    filename, title, description = PAGES[path]
    content = (static_dir / filename).read_text()
    social_image = escape(base_url + "/static/artwork/unfold-hero-1600.webp", quote=True)
    # Fixed page allowlist plus validated deployment origin: never the Host header.
    tags = (
        f'<link rel="canonical" href="{escape(base_url + path, quote=True)}">'
        '<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{escape(title, quote=True)}">'
        f'<meta property="og:description" content="{escape(description, quote=True)}">'
        f'<meta property="og:url" content="{escape(base_url + path, quote=True)}">'
        f'<meta property="og:image" content="{social_image}">'
        '<meta property="og:image:alt" content="A paper chart unfolds into numbers '
        'and a spreadsheet. Concept illustration of chart-to-data extraction.">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{escape(title, quote=True)}">'
        f'<meta name="twitter:description" content="{escape(description, quote=True)}">'
        f'<meta name="twitter:image" content="{social_image}">'
        '<link rel="icon" href="/static/icons/favicon.ico" sizes="any">'
        '<link rel="icon" href="/static/icons/favicon-32.png" sizes="32x32" type="image/png">'
        '<link rel="icon" href="/static/icons/favicon-16.png" sizes="16x16" type="image/png">'
        '<link rel="icon" href="/static/icons/favicon-dark-32.png" sizes="32x32" '
        'type="image/png" media="(prefers-color-scheme: dark)">'
        '<link rel="icon" href="/static/icons/favicon-dark-16.png" sizes="16x16" '
        'type="image/png" media="(prefers-color-scheme: dark)">'
        '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">'
        '<link rel="manifest" href="/static/site.webmanifest">'
        '<script src="/static/site.js" defer></script>'
    )
    if path not in INDEXABLE_PATHS and 'name="robots"' not in content:
        tags += '<meta name="robots" content="noindex, nofollow">'
    if 'name="description"' not in content:
        tags += f'<meta name="description" content="{escape(description, quote=True)}">'
    start = content.index("<title>")
    end = content.index("</title>", start) + len("</title>")
    content = content[:start] + f"<title>{escape(title)}</title>" + content[end:]
    content = content.replace("<head>", '<head><script src="/static/theme.js"></script>', 1)
    content = content.replace("</head>", tags + "</head>")
    footer = (
        '<footer class="site-footer"><span>© '
        f'{date.today().year} Unrender</span><nav aria-label="Footer">'
        '<a href="/privacy">Privacy</a><a href="/terms">Terms</a>'
        '<a href="/contact">Contact</a>'
        '<button class="text-button" type="button" id="cookie-settings">Cookie settings</button>'
        "</nav></footer>"
        '<section class="cookie-notice" id="cookie-notice" aria-label="Cookie choices" hidden>'
        "<p>Essential cookies keep your workspace secure. Optional analytics are off. "
        "No analytics data is sent until a provider is configured and you opt in.</p>"
        '<button class="button button-secondary" id="cookie-reject" type="button">'
        "Essential only</button>"
        '<button class="button button-secondary" id="cookie-accept" type="button">'
        "Allow optional analytics</button>"
        "</section>"
        "<!-- TODO: provide approved analytics provider, measurement ID, and privacy disclosure -->"
    )
    headers = {} if path in INDEXABLE_PATHS else {"X-Robots-Tag": "noindex, nofollow"}
    return HTMLResponse(content.replace("</body>", footer + "</body>"), headers=headers)


def error_document(status: int) -> HTMLResponse:
    title = "Page not found" if status == 404 else "Something went wrong"
    message = (
        "This address does not point to a page. Your workspace is still available."
        if status == 404
        else "We could not complete that request. Return to your workspace and retry."
    )
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        '<link rel="icon" href="/static/icons/favicon.ico">'
        f'<meta name="description" content="{message}"><title>{title} — Unrender</title>'
        '<script src="/static/theme.js"></script>'
        '<link rel="stylesheet" href="/static/app.css"></head><body>'
        '<header class="site-header"><a class="wordmark" href="/">'
        '<img src="/static/icons/icon-192.png" width="30" height="30" alt="">'
        "Unrender</a></header>"
        f'<main class="legal-page"><p class="eyebrow">{status}</p><h1>{title}</h1>'
        f'<p>{message}</p><a class="button button-primary" href="/">Return home</a>'
        "</main></body></html>",
        status_code=status,
    )


def sitemap(base_url: str) -> str:
    # Only fixed public documents; never enumerate jobs, accounts or source files.
    urls = "".join(f"<url><loc>{escape(base_url + path)}</loc></url>" for path in INDEXABLE_PATHS)
    return '<?xml version="1.0" encoding="UTF-8"?>' + (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    )
