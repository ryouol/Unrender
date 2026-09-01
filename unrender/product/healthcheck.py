"""Container-local readiness probe that preserves the configured public Host."""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.parse import urlsplit

from unrender.product.config import Settings


def main() -> None:
    settings = Settings.from_env()
    public_host = urlsplit(settings.base_url).hostname
    if not public_host:
        raise SystemExit("UNRENDER_BASE_URL has no host")
    port = int(os.getenv("PORT", "8000"))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health/ready",
        headers={"Host": public_host},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            payload = json.load(response)
            if response.status != 200 or payload.get("status") != "ready":
                raise SystemExit("Unrender is not ready")
    except Exception as exc:
        raise SystemExit(f"Unrender readiness probe failed: {type(exc).__name__}") from exc
