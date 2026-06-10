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


def load_eval_samples(path: str, limit: int = 0) -> List[EvalSample]:
    rows = read_jsonl(path, limit=limit)
    samples = []
    for r in rows:
        image = r["images"][0]
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
