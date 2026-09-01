"""Review-first chart digitization product surface.

The research and training packages remain independent from this application.
The product package owns authentication, durable jobs, review state, exports,
and the boundary to a configured inference provider.
"""

from typing import Any

__all__ = ["Settings", "create_app"]


def __getattr__(name: str) -> Any:
    if name == "Settings":
        from unrender.product.config import Settings

        return Settings
    if name == "create_app":
        from unrender.product.web import create_app

        return create_app
    raise AttributeError(name)
