"""Coordinated, hash-verified product backup and restore primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
from pathlib import Path
from typing import Any

from unrender.product.config import Settings
from unrender.product.database import Database


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
        ):
            raise BackupError(f"Backup source contains an unsafe path: {path}")
        if stat.S_ISREG(metadata.st_mode):
            files.append(path)
    return sorted(files)


def _committed_storage_paths(conn: sqlite3.Connection, storage_root: Path) -> list[Path]:
    rows = conn.execute(
        "SELECT storage_path AS path FROM uploads UNION SELECT source_path AS path FROM jobs"
    ).fetchall()
    root = storage_root.resolve(strict=True)
    committed: set[Path] = set()
    for row in rows:
        candidate = Path(str(row[0]))
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise BackupError(
                "A committed source path is missing or outside product storage"
            ) from exc
        if (
            candidate != resolved
            or not relative.parts
            or relative.parts[0] not in {"uploads", "jobs"}
        ):
            raise BackupError("A committed source path contains an unsafe link or namespace")
        metadata = resolved.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise BackupError("A committed source path is not a regular file")
        committed.add(resolved)
    return sorted(committed)


def _copy_regular_file(source: Path, destination: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BackupError("A committed source changed before backup")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with destination.open("xb") as output:
            while chunk := os.read(descriptor, 1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise BackupError("A committed source changed during backup")
        os.chmod(destination, 0o600)
    finally:
        os.close(descriptor)


def _manifest(root: Path, *, source_data_dir: Path) -> dict[str, Any]:
    files = {
        path.relative_to(root).as_posix(): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in _safe_files(root)
        if path.name != "manifest.json"
    }
    return {
        "format": "unrender-coordinated-backup-v1",
        "source_data_dir": str(source_data_dir.resolve()),
        "files": files,
    }


def _manifest_source_root(manifest: dict[str, Any]) -> Path:
    value = manifest.get("source_data_dir")
    if not isinstance(value, str) or not value or "~" in value:
        raise BackupError("Backup manifest source root is invalid")
    root = Path(value)
    if not root.is_absolute() or any(part in {".", ".."} for part in root.parts):
        raise BackupError("Backup manifest source root is unsafe")
    return root


def _storage_relative(path_value: object, data_root: Path) -> Path:
    candidate = Path(str(path_value))
    try:
        relative = candidate.relative_to(data_root / "storage")
    except ValueError as exc:
        raise BackupError(
            "Restored database contains a source path outside product storage"
        ) from exc
    if not relative.parts or relative.parts[0] not in {"uploads", "jobs"} or ".." in relative.parts:
        raise BackupError("Restored database contains an unsafe source namespace")
    return relative


def _validate_restored_storage(
    conn: sqlite3.Connection,
    *,
    old_data_root: Path,
    recovery_root: Path,
) -> None:
    for table, column in (("uploads", "storage_path"), ("jobs", "source_path")):
        for row in conn.execute(f'SELECT "{column}" FROM "{table}"'):  # noqa: S608 -- closed constants
            relative = _storage_relative(row[0], old_data_root)
            restored_file = recovery_root / "storage" / relative
            if restored_file.is_symlink() or not restored_file.is_file():
                raise BackupError(f"Recovery set is missing a committed {table} source")
    for row in conn.execute("SELECT storage_path FROM pending_deletions"):
        _storage_relative(row[0], old_data_root)


def create_backup(settings: Settings, destination: Path) -> Path:
    data_dir = settings.data_dir.resolve()
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise BackupError("Backup destination must not already exist")
    if destination == data_dir or destination.is_relative_to(data_dir):
        raise BackupError("Backup destination must be outside the live data directory")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    database = Database(settings.database_path)
    temporary.mkdir(mode=0o700)
    try:
        try:
            lock = database.operational_lock(exclusive=True, timeout_seconds=0)
            with lock:
                if not database.ready():
                    raise BackupError("The live database is not initialized at the current schema")
                output_db = temporary / "unrender.sqlite3"
                source = database.connect()
                target = sqlite3.connect(output_db)
                try:
                    source.backup(target)
                    target.commit()
                    committed = _committed_storage_paths(target, settings.storage_dir)
                finally:
                    target.close()
                    source.close()
                os.chmod(output_db, 0o600)
                storage_output = temporary / "storage"
                storage_output.mkdir(mode=0o700)
                storage_root = settings.storage_dir.resolve(strict=True)
                for live_path in committed:
                    _copy_regular_file(
                        live_path,
                        storage_output / live_path.relative_to(storage_root),
                    )
                manifest = _manifest(temporary, source_data_dir=data_dir)
                manifest_path = temporary / "manifest.json"
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                os.chmod(manifest_path, 0o600)
        except TimeoutError as exc:
            raise BackupError(
                "A product mutation is active; drain writes and retry the coordinated backup"
            ) from exc
        os.rename(temporary, destination)
        return destination
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _validated_manifest(source: Path) -> dict[str, Any]:
    manifest_path = source / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest is missing or invalid") from exc
    if manifest.get("format") != "unrender-coordinated-backup-v1":
        raise BackupError("Backup format is not supported")
    _manifest_source_root(manifest)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise BackupError("Backup manifest contains no files")
    actual_paths = {
        path.relative_to(source).as_posix()
        for path in _safe_files(source)
        if path.name != "manifest.json"
    }
    if actual_paths != set(files):
        raise BackupError("Backup file inventory does not match its manifest")
    for relative, evidence in files.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise BackupError("Backup manifest contains an unsafe path")
        path = source / relative_path
        if (
            not isinstance(evidence, dict)
            or _sha256(path) != evidence.get("sha256")
            or path.stat().st_size != evidence.get("bytes")
        ):
            raise BackupError(f"Backup hash/size validation failed for {relative}")
    return manifest


def restore_backup(source: Path, target_data_dir: Path) -> Path:
    expanded_source = source.expanduser()
    if expanded_source.is_symlink():
        raise BackupError("Restore source must not be a symbolic link")
    source = expanded_source.resolve(strict=True)
    target = target_data_dir.expanduser().resolve()
    if target.exists():
        raise BackupError("Restore target must not already exist")
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise BackupError("Restore source and target must be separate trees")
    manifest = _validated_manifest(source)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, temporary, symlinks=False)
        _validated_manifest(temporary)
        database_path = temporary / "unrender.sqlite3"
        conn = sqlite3.connect(database_path)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise BackupError("Restored database failed integrity_check")
            conn.execute("PRAGMA foreign_keys=ON")
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise BackupError("Restored database failed foreign_key_check")
            old_data_root = _manifest_source_root(manifest)
            _validate_restored_storage(
                conn,
                old_data_root=old_data_root,
                recovery_root=temporary,
            )
            old_root = str(old_data_root)
            new_root = str(target)
            if old_root != new_root:
                mappings = (
                    ("uploads", "storage_path"),
                    ("jobs", "source_path"),
                    ("pending_deletions", "storage_path"),
                )
                for table, column in mappings:
                    conn.execute(
                        f'UPDATE "{table}" SET "{column}"=? || substr("{column}", ?) '  # noqa: S608 -- identifiers are a closed constant tuple
                        f'WHERE "{column}"=? OR "{column}" LIKE ?',
                        (new_root, len(old_root) + 1, old_root, f"{old_root}/%"),
                    )
                conn.commit()
        finally:
            conn.close()
        (temporary / "manifest.json").unlink()
        os.rename(temporary, target)
        return target
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
