"""Review-first chart digitization product surface.

The research and training packages remain independent from this application.
The product package owns authentication, durable jobs, review state, exports,
and the boundary to a configured inference provider.
"""

from unrender.product.config import Settings
from unrender.product.web import create_app

__all__ = ["Settings", "create_app"]
