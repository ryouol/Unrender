"""Isolated browser acceptance server: no inherited cloud credentials or external provider."""

import tempfile
from pathlib import Path

import uvicorn

from unrender.product.config import Settings
from unrender.product.web import create_app

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="unrender-e2e-") as root:
        settings = Settings(
            data_dir=Path(root),
            environment="test",
            base_url="http://127.0.0.1:8765",
            extractor_backend="replay",
            worker_enabled=True,
            seed_demo_account=True,
            global_rate_limit_per_minute=10000,
            rate_limit_per_minute=10000,
            global_auth_rate_limit_per_minute=1000,
            auth_rate_limit_per_minute=1000,
        )
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8765)
