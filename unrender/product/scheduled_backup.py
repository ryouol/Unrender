"""Daily off-host backups using the deployment's existing Modal credentials."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any

from unrender.product.backup import create_backup
from unrender.product.config import Settings

logger = logging.getLogger("unrender.backup")
_ARCHIVE = re.compile(r"backup-[0-9]{10}-[0-9a-f]{64}\.tar\Z")
_INTERVAL = 24 * 60 * 60
_RETAIN = 7
_MAX_ARCHIVE_BYTES = 1024**3


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _archives(volume: Any) -> list[str]:
    return sorted(
        PurePosixPath(entry.path).name
        for entry in volume.listdir("/")
        if _ARCHIVE.fullmatch(PurePosixPath(entry.path).name)
    )


class _BoundedDownload:
    def __init__(self, file: Any):
        self.file = file

    def tell(self) -> int:
        return int(self.file.tell())

    def seek(self, offset: int, whence: int = 0) -> int:
        return int(self.file.seek(offset, whence))

    def write(self, chunk: bytes) -> int:
        if self.tell() + len(chunk) > _MAX_ARCHIVE_BYTES:
            raise RuntimeError("Off-host backup exceeds the archive limit")
        return int(self.file.write(chunk))


def _verify(volume: Any, name: str) -> int:
    expected = name.removesuffix(".tar").rsplit("-", 1)[1]
    with tempfile.TemporaryFile() as download:
        # Modal 1.5.5's public reader prefetches whole blocks per host CPU.
        # This pinned SDK method streams into a file with explicit concurrency.
        volume._read_file_into_fileobj(name, _BoundedDownload(download), concurrency=1)
        size = download.seek(0, 2)
        download.seek(0)
        received = hashlib.file_digest(download, "sha256").hexdigest()
    if received != expected:
        raise RuntimeError("Off-host backup verification failed")
    return size


def _finish(volume: Any, name: str, size: int) -> dict[str, object]:
    for expired in _archives(volume)[:-_RETAIN]:
        volume.remove_file(expired)
    return {
        "last_success": int(name.split("-")[1]),
        "archive": name,
        "sha256": name.removesuffix(".tar").rsplit("-", 1)[1],
        "bytes": size,
    }


def upload_backup(settings: Settings, volume: Any) -> dict[str, object]:
    existing = _archives(volume)
    if len(existing) > _RETAIN + 1:
        raise RuntimeError("Backup volume requires operator cleanup")
    recent = bool(existing and 0 <= time.time() - int(existing[-1].split("-")[1]) < _INTERVAL)
    if len(existing) == _RETAIN + 1 or recent:
        # Resume verification/pruning after a previous interrupted publication.
        return _finish(volume, existing[-1], _verify(volume, existing[-1]))
    with tempfile.TemporaryDirectory(prefix="unrender-backup-") as temporary:
        root = Path(temporary)
        snapshot = create_backup(
            settings, root / "snapshot", require_idle=True, max_snapshot_bytes=_MAX_ARCHIVE_BYTES
        )
        archive = root / "backup.tar"
        with tarfile.open(archive, "w") as output:
            output.add(snapshot, arcname="snapshot")
        os.chmod(archive, 0o600)
        if archive.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise RuntimeError("Backup exceeds the one GiB archive limit")
        digest = _digest(archive)
        created = int(time.time())
        name = f"backup-{created:010d}-{digest}.tar"
        with volume.batch_upload() as batch:
            batch.put_file(archive, f"/{name}", mode=0o600)
        size = _verify(volume, name)
        if size != archive.stat().st_size:
            raise RuntimeError("Off-host backup size verification failed")
        return _finish(volume, name, size)


class ScheduledBackup:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status_path = settings.data_dir / "backup-status.json"
        self._last_success = 0.0
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def start(self) -> None:
        if not self.settings.backup_volume_name or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="unrender-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._process_lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
        if self._thread:
            self._thread.join(timeout=1)

    def due(self) -> bool:
        if 0 <= time.time() - self._last_success < _INTERVAL:
            return False
        try:
            last = json.loads(self.status_path.read_text())["last_success"]
            return not isinstance(last, (int, float)) or not 0 <= time.time() - last < _INTERVAL
        except (OSError, ValueError, KeyError, TypeError):
            return True

    def run_once(self) -> dict[str, object]:
        import modal

        volume = modal.Volume.from_name(self.settings.backup_volume_name)
        status = upload_backup(self.settings, volume)
        completed = status["last_success"]
        if not isinstance(completed, int):
            raise RuntimeError("Backup completion timestamp is invalid")
        self._last_success = completed
        temporary = self.status_path.with_suffix(".tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump(status, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.status_path)
            status["status_persisted"] = True
        except OSError:
            status["status_persisted"] = False
            logger.warning("scheduled_backup_status_write_failed")
        return status

    def _run_isolated(self) -> None:
        # The parent removes child files even after a timeout or termination.
        with tempfile.TemporaryDirectory(prefix="unrender-scheduled-") as temporary:
            with self._process_lock:
                if self._stop.is_set():
                    return
                process = subprocess.Popen(
                    [sys.executable, "-m", "unrender.product.scheduled_backup"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    env={**os.environ, "TMPDIR": temporary, "TMP": temporary, "TEMP": temporary},
                )
                self._process = process
            try:
                try:
                    output, _ = process.communicate(timeout=600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
                if process.returncode:
                    raise RuntimeError("Backup subprocess failed")
                status = json.loads(output)
                self._last_success = float(status["last_success"])
                logger.info("scheduled_backup_succeeded")
                if not status["status_persisted"]:
                    logger.warning("scheduled_backup_status_write_failed")
            finally:
                with self._process_lock:
                    self._process = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.due():
                try:
                    self._run_isolated()
                except Exception:
                    if not self._stop.is_set():
                        logger.exception("scheduled_backup_failed")
            self._stop.wait(3600)


def _configure_upload_budget() -> None:
    from modal._utils import blob_utils

    # Only the dedicated backup child changes these pinned SDK constants.
    # A 64 MiB budget permits one 16 MiB multipart segment plus SDK buffers.
    blob_utils.MULTIPART_INFLIGHT_BYTES_MIN = 64 * 1024**2
    blob_utils.MULTIPART_INFLIGHT_BYTES_MAX = 64 * 1024**2


if __name__ == "__main__":
    _configure_upload_budget()
    configured = Settings.from_env()
    if not configured.backup_volume_name:
        raise RuntimeError("Backup volume is not configured")
    print(json.dumps(ScheduledBackup(configured).run_once()))
