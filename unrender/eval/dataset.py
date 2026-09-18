"""Load an eval set (image path + ground-truth ChartData) from a chat JSONL.

Reuses the train/val/test.jsonl produced by split_dataset.py: the user turn is
the prompt, the assistant turn is the exact GT JSON. Works on any split.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from unrender.data_gen.provenance import read_split
from unrender.io_utils import resolve_image
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import strict_json


class GroundTruthReview(BaseModel):
    """A review attestation bound to an image, annotation and source data snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True)
    contract: Literal["real-ground-truth-review-v1"]
    status: Literal["verified"]
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed_at: str
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    visible_metadata_checked: Literal[True]
    source_values_checked: Literal[True]
    scale_units_checked: Literal[True]
    recoverability_checked: Literal[True]


def annotation_sha256(gt_json: str, meta: dict) -> str:
    """Bind review to the complete target, value-label visibility and source citation."""
    payload = {
        "chart": strict_json(gt_json),
        "labels_shown": meta.get("labels_shown"),
        "source": meta.get("source"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def validate_ground_truth_review(gt_json: str, meta: dict, image: Path) -> None:
    """External charts cannot start a new evaluation with unreviewed annotations.

    Missing images remain an input error for the attempt ledger. When present,
    their bytes must match the reviewed image. Offline historical rescoring does
    not call this loader and remains possible, with its original claim limits.
    """
    if not meta.get("source") and "ground_truth_review" not in meta:
        return
    try:
        review = GroundTruthReview.model_validate(meta.get("ground_truth_review"))
        if any(
            meta["ground_truth_review"][key] is not True
            for key in (
                "visible_metadata_checked",
                "source_values_checked",
                "scale_units_checked",
                "recoverability_checked",
            )
        ):
            raise ValueError("review checks must be explicit true booleans")
        reviewed_at = datetime.fromisoformat(review.reviewed_at.replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None or not review.reviewer.strip():
            raise ValueError("review needs an identified reviewer and timezone-aware time")
        if (
            not isinstance(meta.get("labels_shown"), bool)
            or not isinstance(meta.get("source"), str)
            or not meta["source"].strip()
        ):
            raise ValueError("review needs a source citation and explicit value-label visibility")
        if annotation_sha256(gt_json, meta) != review.annotation_sha256:
            raise ValueError("annotation changed since review")
        if (
            image.is_file()
            and hashlib.sha256(image.read_bytes()).hexdigest() != review.image_sha256
        ):
            raise ValueError("image changed since review")
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"unverified real-chart ground truth for {image.stem}: invalid review: {exc}"
        ) from exc


def ground_truth_review_coverage(rows: list[dict]) -> dict:
    external = []
    unverified = []
    for row in rows:
        meta = row.get("meta") or {}
        if not meta.get("source") and "ground_truth_review" not in meta:
            continue
        external.append(str(row["id"]))
        try:
            validate_ground_truth_review(row["gt"], meta, Path(row.get("image") or row["id"]))
        except ValueError:
            unverified.append(str(row["id"]))
    return {
        "external_charts": len(external),
        "verified": len(external) - len(unverified),
        "unverified_ids": unverified,
        "review_gate_passed": not unverified,
    }


def require_reviewed_predictions(rows: list[dict]) -> None:
    if ids := ground_truth_review_coverage(rows)["unverified_ids"]:
        raise ValueError(
            f"unverified real-chart ground truth; comparison withheld for {len(ids)} IDs"
        )


@dataclass
class EvalSample:
    id: str
    image: str
    gt_json: str  # canonical GT JSON string
    gt: ChartData
    meta: dict  # slice keys: labels_shown, chart_type, augmented


def load_eval_samples(path: str, limit: int = 0) -> list[EvalSample]:
    rows = read_split(path)
    if limit:
        rows = rows[:limit]
    samples = []
    for r in rows:
        image = resolve_image(r["images"][0], path)
        gt_json = r["messages"][1]["content"]
        meta = r.get("meta", {})
        validate_ground_truth_review(gt_json, meta, Path(image))
        samples.append(
            EvalSample(
                id=Path(image).stem,
                image=image,
                gt_json=gt_json,
                gt=ChartData.model_validate_json(gt_json),
                meta=meta,
            )
        )
    return samples
