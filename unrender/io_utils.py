"""Small shared I/O helpers. JSONL is the project's on-disk format everywhere
(manifests, splits, predictions), so reading it lives in one place."""

from __future__ import annotations

import json
from typing import List


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
