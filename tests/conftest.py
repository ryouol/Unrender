"""Shared controls for tests that exercise fixed-window request limits."""

import pytest

from unrender.product import service


@pytest.fixture
def fixed_rate_window(monkeypatch):
    now = service.utcnow()
    monkeypatch.setattr(service, "utcnow", lambda: now)
