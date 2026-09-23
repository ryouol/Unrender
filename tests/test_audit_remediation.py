"""Integration regressions for the September platform audit."""

from fastapi.testclient import TestClient

from test_product import settings_for
from unrender.product.web import create_app


def test_readiness_does_not_spend_public_admission_capacity(tmp_path):
    settings = settings_for(tmp_path, global_rate_limit_per_minute=3)
    with TestClient(create_app(settings)) as client:
        assert [client.get('/').status_code for _ in range(3)] == [200] * 3
        assert client.get('/').status_code == 429
        assert client.get('/health/ready').status_code == 200
        assert client.get('/health/live').status_code == 200
        assert client.get('/').status_code == 429
