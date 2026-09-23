"""Small shared I/O helpers. JSONL is the project's on-disk format everywhere
(manifests, splits, predictions), so reading it lives in one place."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path


def resolve_image(image: str, split_path: str | Path) -> str:
    """Absolute paths stay absolute; relative images belong to their split directory.

    Never search the working directory or guess a dataset root. Missing images
    remain resolvable so evaluation can record them as input failures.
    """
    parts = Path(image).parts
    if (
        len(parts) >= 2
        and parts[0] == "data"
        and parts[1] in {"synthetic_v0", "synthetic_v1", "synthetic_v2"}
    ):
        raise ValueError(
            "historical repository-relative images are unsupported for new inference; "
            "rescore saved predictions or use a current split-relative dataset"
        )
    if Path(image).is_absolute():
        return image
    return str(Path(split_path).resolve().parent / image)


def read_jsonl(path, limit: int = 0) -> list[dict]:
    """Read a .jsonl file into a list of dicts, streaming line-by-line.

    Blank lines are skipped. With ``limit > 0`` it stops after ``limit`` records
    — so taking a prefix of a huge file doesn't read the whole thing.
    """
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
            if limit and len(out) >= limit:
                break
    return out


def fingerprint_ids(ids: Iterable) -> str:
    """Order-independent 16-hex fingerprint of an id collection.

    Binds a predictions/report file to the exact split or subset it was produced
    from, so a desynced split (e.g. the dev300/Modal-test divergence, where a
    subset was built against a different shuffle than the model saw) is detectable
    instead of silently scoring a smaller, unbalanced N.
    """
    joined = "\n".join(sorted({str(i) for i in ids}))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]
