"""Build a reviewed real-chart evaluation set from images and source-backed labels.

Each label must include the real-ground-truth-review-v1 receipt documented in
data/real_v0/README.md. It binds actual visible metadata, values, units and
recoverability checks to the image, annotation and retained source data. Missing,
incomplete or stale reviews fail before either output JSONL is written.

Emits test.jsonl and test.modal.jsonl with identical targets and review metadata,
using local and /vol image paths respectively. Historical real_v0 annotations
are rejected; use a new dataset version for corrected, independently reviewed data.

    python -m unrender.eval.build_real_set --dir data/real_dev_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

# Reuse the EXACT row shape the train/val/test splits use (canonical prompt +
# GT JSON + meta). Importing it (rather than re-emitting) is what guarantees a
# real row is indistinguishable from a synthetic one to the loader and scorer.
from unrender.data_gen.split_dataset import _row
from unrender.eval.dataset import validate_ground_truth_review
from unrender.schema.chart_schema import (
    CHART_TYPES,
    Axis,
    ChartData,
    Point,
    Series,
    canonical_json,
)

VOL_ROOT = "/vol"  # Modal volume mount point (modal_train.py `V`)


def _axis(d) -> Axis:
    d = d or {}
    return Axis(label=d.get("label"), unit=d.get("unit"))


def label_to_chartdata(label: dict, src: str) -> ChartData:
    """Validate one hand-written label into a ChartData (the GT format), raising a
    clear, file-named error on any typo. A malformed label must fail loudly here,
    never slip through as a plausible-but-wrong ground truth that silently corrupts
    the benchmark."""
    ct = label.get("chart_type")
    if ct not in CHART_TYPES:
        raise ValueError(f"{src}: chart_type {ct!r} is not one of {list(CHART_TYPES)}")
    series = []
    for i, s in enumerate(label.get("series") or []):
        pts = []
        for p in s.get("points") or []:
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                raise ValueError(f"{src}: series[{i}] point {p!r} must be a [x, y] pair")
            x, y = p
            try:
                y = float(y)
            except (TypeError, ValueError):
                raise ValueError(f"{src}: series[{i}] y value {y!r} is not a number") from None
            pts.append(Point(x=x, y=y))
        if not pts:
            raise ValueError(f"{src}: series[{i}] has no points")
        series.append(Series(name=s.get("name"), points=pts))
    if not series:
        raise ValueError(f"{src}: no series — fill in the real values (see _TEMPLATE.json)")
    return ChartData(
        chart_type=ct,
        title=label.get("title"),
        x_axis=_axis(label.get("x_axis")),
        y_axis=_axis(label.get("y_axis")),
        series=series,
    )


def build(dirpath: str) -> dict:
    """Convert ``<dir>/labels/*.json`` (+ ``<dir>/images``) into test.jsonl and
    test.modal.jsonl. Returns a small summary dict (also printed)."""
    root = Path(dirpath)
    images_dir, labels_dir = root / "images", root / "labels"
    if not labels_dir.is_dir():
        raise SystemExit(f"no labels/ dir under {root} — see {root}/README.md")

    label_files = sorted(p for p in labels_dir.glob("*.json") if not p.name.startswith("_"))
    if not label_files:
        raise SystemExit(
            f"no label files in {labels_dir} — drop chart images into {images_dir}/ and a "
            f"filled copy of {labels_dir}/_TEMPLATE.json per chart, then re-run."
        )

    rows_local, rows_modal, seen = [], [], set()
    for lf in label_files:
        label = json.loads(lf.read_text(encoding="utf-8"))
        img_name = label.get("image") or (lf.stem + ".png")
        img_path = images_dir / img_name
        if not img_path.exists():
            raise SystemExit(f"{lf}: image {img_path} not found — drop it into {images_dir}/")
        stem = img_path.stem  # the row id (load_eval_samples uses Path(image).stem)
        if stem in seen:
            raise SystemExit(f"duplicate image stem {stem!r} — give each chart a unique filename")
        seen.add(stem)

        gt = label_to_chartdata(label, str(lf))
        label_json = canonical_json(gt)
        meta = {
            "labels_shown": bool(label.get("labels_shown", False)),
            "chart_type": gt.chart_type,
            "augmented": False,  # real charts aren't synthetically degraded
            "source": label.get("source"),
            "ground_truth_review": label.get("ground_truth_review"),
        }
        validate_ground_truth_review(label_json, meta, img_path)
        source_file = label.get("source_data_file")
        if not isinstance(source_file, str) or not source_file.strip():
            raise ValueError(f"{lf}: source_data_file must identify the saved source data")
        source_bytes = (root / source_file).read_bytes()
        if (
            hashlib.sha256(source_bytes).hexdigest()
            != meta["ground_truth_review"]["source_data_sha256"]
        ):
            raise ValueError(f"{lf}: source data changed since review")
        rel = f"{root.as_posix()}/images/{img_name}"  # data/real_v0/images/x.png
        vol = f"{VOL_ROOT}/{rel}"  # /vol/data/real_v0/images/x.png (matches the upload target)
        rows_local.append(_row(f"images/{img_name}", label_json, meta))
        rows_modal.append(_row(vol, label_json, meta))

    for name, rows in (("test.jsonl", rows_local), ("test.modal.jsonl", rows_modal)):
        with open(root / name, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    by_type = Counter(r["meta"]["chart_type"] for r in rows_local)
    n_free = sum(1 for r in rows_local if r["meta"]["labels_shown"] is False)
    summary = {
        "n": len(rows_local),
        "label_free": n_free,
        "labeled": len(rows_local) - n_free,
        "by_type": dict(by_type),
    }
    print(f"built {summary['n']} real charts -> {root}/test.jsonl  (+ test.modal.jsonl for Modal)")
    print(
        f"  labeled={summary['labeled']}  label_free={summary['label_free']} "
        f"by_type={summary['by_type']}"
    )
    return summary


def main():
    p = argparse.ArgumentParser(description="Build a real-chart eval set from hand-labeled charts.")
    p.add_argument("--dir", default="data/real_v0", help="dataset dir with images/ and labels/")
    build(p.parse_args().dir)


if __name__ == "__main__":
    main()
