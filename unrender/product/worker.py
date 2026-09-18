"""Bounded durable-job worker pool for the default SQLite deployment."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid

from unrender.product.service import ProductService

logger = logging.getLogger("unrender.worker")


class JobWorker:
    def __init__(self, service: ProductService, *, poll_seconds: float = 0.25):
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
        self._draining = False

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._draining = False
        self._threads = [
            threading.Thread(
                target=self._run, args=(slot,), name=f"unrender-job-worker-{slot}", daemon=True
            )
            for slot in range(self.service.settings.worker_concurrency)
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        self._draining = True
        self._stop.set()
        deadline = time.monotonic() + (
            timeout
            if timeout is not None
            else self.service.settings.worker_shutdown_timeout_seconds
        )
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        stopped = not self.is_running
        if not stopped:
            logger.warning(
                "job_worker_shutdown_wait_expired",
                extra={"event_name": "job_worker_shutdown_wait_expired", "owner": self.owner},
            )
        return stopped

    @property
    def is_running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    @property
    def is_accepting(self) -> bool:
        return (
            len(self._threads) == self.service.settings.worker_concurrency
            and all(thread.is_alive() for thread in self._threads)
            and not self._draining
        )

    def _run(self, slot: int) -> None:
        next_cleanup = 0.0
        next_recovery = 0.0
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if slot == 0 and now >= next_recovery:
                    self.service.recover_interrupted_jobs()
                    next_recovery = now + self.service.settings.worker_heartbeat_seconds
                did_work = self.service.process_one(f"{self.owner}:{slot}", self._stop)
                now = time.monotonic()
                if slot == 0 and now >= next_cleanup:
                    self.service.cleanup_expired()
                    next_cleanup = now + 3600
                if not did_work:
                    self._stop.wait(self.poll_seconds)
            except Exception:  # keep the queue alive; individual jobs normalize failures
                logger.exception("job_worker_loop_failed")
                self._stop.wait(1.0)
