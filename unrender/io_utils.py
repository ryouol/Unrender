"""Small shared I/O helpers. JSONL is the project's on-disk format everywhere
(manifests, splits, predictions), so reading it lives in one place."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, List


def read_jsonl(path, limit: int = 0) -> List[dict]:
    """Read a .jsonl file into a list of dicts, streaming line-by-line.

    Blank lines are skipped. With ``limit > 0`` it stops after ``limit`` records
    — so taking a prefix of a huge file doesn't read the whole thing.
    """
    out: List[dict] = []
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
