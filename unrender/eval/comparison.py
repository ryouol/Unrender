"""Shared paired-input identity, independent of an arm's image preprocessing.

Historical rows with no recorded image digest remain descriptive evidence only.
If either arm records an identity, both must record the same identity. Processor
outputs may intentionally differ; the source pixels, truth and reviews may not.
"""

from __future__ import annotations

import re

from unrender.schema.chart_schema import ChartData


def source_identity(row: dict) -> dict:
    meta = row.get("meta") or {}
    hashes = [
        row.get("image_sha256"),
        (meta.get("generation") or {}).get("image_sha256"),
        (meta.get("ground_truth_review") or {}).get("image_sha256"),
    ]
    recorded = [h for h in hashes if h is not None]
    if any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in recorded):
        raise ValueError(f"invalid source image hash for {row['id']}")
    if len(set(recorded)) > 1:
        raise ValueError(f"conflicting source image identity for {row['id']}")
    return {
        "image_sha256": recorded[0] if recorded else None,
        "source": meta.get("source"),
        "source_group": meta.get("source_group"),
        "generation": meta.get("generation"),
        "ground_truth_review": meta.get("ground_truth_review"),
        "source_review": meta.get("source_review"),
    }


def require_same_input(a: dict, b: dict) -> None:
    if ChartData.model_validate_json(a["gt"]) != ChartData.model_validate_json(b["gt"]) or (
        a.get("meta") or {}
    ).get("labels_shown") != (b.get("meta") or {}).get("labels_shown"):
        raise ValueError(f"ground truth mismatch for paired id {a['id']}")
    if source_identity(a) != source_identity(b):
        raise ValueError(f"source image/review identity mismatch for paired id {a['id']}")
