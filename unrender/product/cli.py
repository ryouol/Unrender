"""Local and container entry point."""

from __future__ import annotations

import os
from copy import deepcopy

import uvicorn


def main() -> None:
    host = os.getenv("UNRENDER_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["formatters"]["product"] = {
        "()": "unrender.product.observability.ProductLogFormatter"
    }
    log_config["handlers"]["product"] = {
        "class": "logging.StreamHandler",
        "formatter": "product",
        "stream": "ext://sys.stdout",
    }
    log_config["loggers"]["unrender"] = {
        "handlers": ["product"],
        "level": "INFO",
        "propagate": False,
    }
    uvicorn.run(
        "unrender.product.web:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
        log_config=log_config,
    )
