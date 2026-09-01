"""Local and container entry point."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("UNRENDER_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("unrender.product.web:app", host=host, port=port, log_level="info")
