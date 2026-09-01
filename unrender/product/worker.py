"""Single durable-job worker for the default SQLite deployment."""

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
        self._thread: threading.Thread | None = None
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
        self._draining = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._draining = False
        self._thread = threading.Thread(target=self._run, name="unrender-job-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        self._draining = True
        self._stop.set()
        if self._thread:
            self._thread.join(
                timeout=(
                    timeout
                    if timeout is not None
                    else self.service.settings.worker_shutdown_timeout_seconds
                )
            )
        stopped = not self.is_running
        if not stopped:
            logger.warning(
                "job_worker_shutdown_wait_expired",
                extra={"event_name": "job_worker_shutdown_wait_expired", "owner": self.owner},
            )
        return stopped

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def is_accepting(self) -> bool:
        return self.is_running and not self._draining

    def _run(self) -> None:
        next_cleanup = 0.0
        while not self._stop.is_set():
            try:
                did_work = self.service.process_one(self.owner, self._stop)
                now = time.monotonic()
                if now >= next_cleanup:
                    self.service.cleanup_expired()
                    next_cleanup = now + 3600
                if not did_work:
                    self._stop.wait(self.poll_seconds)
            except Exception:  # keep the queue alive; individual jobs normalize failures
                logger.exception("job_worker_loop_failed")
                self._stop.wait(1.0)
