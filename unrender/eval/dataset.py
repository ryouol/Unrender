"""Load an eval set (image path + ground-truth ChartData) from a chat JSONL.

Reuses the train/val/test.jsonl produced by split_dataset.py: the user turn is
the prompt, the assistant turn is the exact GT JSON. Works on any split.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import ChartData


@dataclass
class EvalSample:
    id: str
    image: str
    gt_json: str          # canonical GT JSON string
    gt: ChartData
    meta: dict            # slice keys: labels_shown, chart_type, augmented


def _resolve_image(image: str, jsonl_path: str) -> str:
    """Image paths are either absolute (Modal-generated sets: /vol/...) or
    repo-root-relative (locally-generated sets: data/synthetic_v2/images/x.png).
    For the relative case, anchor on the JSONL's own location — it lives at
    <root>/data/<set>/<split>.jsonl, so <root> is its 3rd parent. Works
    unchanged on the Mac (root=".") and in a Modal container (root="/vol").
    When neither exists, return the path UNCHANGED: flows that never open the
    image (mock providers, re-scoring saved predictions on a machine without
    the images) must keep working; a real provider fails loudly at open."""
    if Path(image).exists():
        return image
    p = Path(jsonl_path).resolve()
    if len(p.parents) >= 3:
        alt = p.parents[2] / image
        if alt.exists():
            return str(alt)
    return image


def load_eval_samples(path: str, limit: int = 0) -> List[EvalSample]:
    rows = read_jsonl(path, limit=limit)
    samples = []
    for r in rows:
        image = _resolve_image(r["images"][0], path)
        gt_json = r["messages"][1]["content"]
        samples.append(
            EvalSample(
                id=Path(image).stem,
                image=image,
                gt_json=gt_json,
                gt=ChartData.model_validate_json(gt_json),
                meta=r.get("meta", {}),
            )
        )
    return samples
