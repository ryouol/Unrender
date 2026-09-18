"""Concurrent worker claims must stay bounded and charge each job once."""

import threading
import time
from types import SimpleNamespace

import pytest

from tests.test_product import (
    _install_successful_extractor,
    _paid_job,
    customer_id,
    service_for,
    settings_for,
)
from unrender.product.worker import JobWorker


@pytest.mark.parametrize("value", [0, 5, -1, True])
def test_pool_size_rejects_unbounded_configuration(tmp_path, value):
    with pytest.raises(ValueError, match="WORKER_CONCURRENCY"):
        settings_for(tmp_path, worker_concurrency=value).validate()


def test_pool_overlapping_jobs_bounded_claimed_once_and_drained(tmp_path):
    service = service_for(
        tmp_path, seed_demo_account=False, initial_credits=5, worker_concurrency=2
    )
    user = customer_id(service)
    jobs = [_paid_job(service, user, color=color) for color in ["red", "green", "blue", "yellow"]]
    _install_successful_extractor(service)
    original = service.extractor.extract
    lock, entered, release = threading.Lock(), threading.Event(), threading.Event()
    counts = {"active": 0, "peak": 0, "calls": 0}

    def extract(image):
        with lock:
            counts["calls"] += 1
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
            if counts["active"] == 2:
                entered.set()
        assert release.wait(5)
        result = original(image)
        with lock:
            counts["active"] -= 1
        return result

    service.extractor = SimpleNamespace(extract=extract)
    worker = JobWorker(service, poll_seconds=0.01)
    worker.start()
    try:
        assert entered.wait(5)
        assert worker.is_accepting
        worker.start()  # idempotent; cannot add slots
        assert not worker.stop(timeout=0.02)
        assert not worker.is_accepting
        assert counts["calls"] == 2
        release.set()
        assert worker.stop(timeout=5)
        assert not worker.is_running
        # Restart drains the remaining queue without repeating the first two.
        worker.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(
                service.get_job(user_id=user, job_id=str(j["id"]))["status"] == "review"
                for j in jobs
            ):
                break
            time.sleep(0.01)
        assert all(
            service.get_job(user_id=user, job_id=str(j["id"]))["status"] == "review" for j in jobs
        )
        assert counts == {"active": 0, "peak": 2, "calls": 4}
        assert service.account(user)["credits"] == 1
        with service.database.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 4
    finally:
        release.set()
        worker.stop(timeout=5)
