"""Persist run identity before training; refuse mutable bases and recipe drift."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path

from unrender.train.checkpoints import canonical, identity_digest


def require_revision(revision: str) -> None:
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("training requires an immutable 40-character base_revision")


def inventory(root: Path) -> dict:
    """Hash the resolved bytes, not cache symlink names; reject concurrent changes."""
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("model/processor contains an unsupported file")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("model/processor changed during inventory")
        files[path.relative_to(root).as_posix()] = digest.hexdigest()
    if not files:
        raise ValueError("model/processor snapshot is empty")
    return files


def runtime_identity() -> dict:
    return {
        "world_size": 1,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": dict(
            sorted(
                (dist.metadata["Name"].lower(), dist.version)
                for dist in importlib.metadata.distributions()
                if dist.metadata["Name"]
            )
        ),
    }


def source_identity() -> dict:
    package = Path(__file__).resolve().parents[1]
    return {
        p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(package.rglob("*.py"))
    }


def record_identity(out: Path, identity: dict) -> None:
    """Caller must own this run. Existing unidentified artifacts are not resumable."""
    from unrender.eval.ledger import atomic_text

    identity_digest(identity)
    path = out / "training-recipe.json"
    if path.exists():
        if canonical(json.loads(path.read_bytes())) != canonical(identity):
            raise ValueError("training recipe changed; use a new run directory")
        return
    if any(p.name != ".run.lock" for p in out.iterdir()):
        raise ValueError("existing training artifacts lack a verified recipe; use a new run")
    atomic_text(path, canonical(identity).decode())
