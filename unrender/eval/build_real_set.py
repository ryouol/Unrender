"""Build a REAL-chart eval set (harness row format) from hand-labeled charts.

The synthetic eval proves the pipeline works; THIS set is what decides whether any
of it transfers to charts the model never trained on — the question MODEL_STATUS_
REVIEW.md and the audit both flag as the unmet gate. You supply, per chart, the
image plus the EXACT underlying values. Those values are the one thing only a
human with the real data can provide: read them off a source that publishes the
numbers (FRED/OWID/a table), never machine-estimate them off the pixels, or the
"benchmark" would just be measuring a model against another model's guess.

    data/real_v0/
      images/   us_unemployment.png        ...   # the real chart images you drop in
      labels/   us_unemployment.json       ...   # the TRUE values, one file per image

Each label file (copy labels/_TEMPLATE.json):

    {
      "image": "us_unemployment.png",            # filename in images/
      "chart_type": "line",                      # one of CHART_TYPES
      "title": "US Unemployment Rate",           # or null
      "x_axis": {"label": "Year", "unit": null},
      "y_axis": {"label": "Rate", "unit": "%"},
      "labels_shown": false,                      # are exact values PRINTED on the chart?
      "source": "FRED series UNRATE",            # provenance of the true numbers
      "series": [{"name": "UNRATE",
                  "points": [["2019", 3.7], ["2020", 8.1]]}]   # [x, y] pairs
    }

`labels_shown` drives the labeled-vs-label-free slice — the slice the whole thesis
turns on — so set it honestly per chart.

Emits two files with IDENTICAL rows, differing only in image path:
  * test.jsonl        — repo-relative paths, for the LOCAL frontier run (Gemini).
  * test.modal.jsonl  — /vol paths, for the Modal base/LoRA run after upload.
Both use split_dataset._row, so the rows are byte-for-byte the shape training and
the synthetic eval use — run_baselines.py / score.py work unchanged.

    python -m unrender.eval.build_real_set --dir data/real_v0
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Reuse the EXACT row shape the train/val/test splits use (canonical prompt +
# GT JSON + meta). Importing it (rather than re-emitting) is what guarantees a
# real row is indistinguishable from a synthetic one to the loader and scorer.
from unrender.data_gen.split_dataset import _row
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
                raise ValueError(f"{src}: series[{i}] y value {y!r} is not a number")
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
        }
        rel = f"{root.as_posix()}/images/{img_name}"  # data/real_v0/images/x.png
        vol = f"{VOL_ROOT}/{rel}"  # /vol/data/real_v0/images/x.png (matches the upload target)
        rows_local.append(_row(rel, label_json, meta))
        rows_modal.append(_row(vol, label_json, meta))

    for name, rows in (("test.jsonl", rows_local), ("test.modal.jsonl", rows_modal)):
        with open(root / name, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    by_type = Counter(r["meta"]["chart_type"] for r in rows_local)
    n_free = sum(1 for r in rows_local if r["meta"]["labels_shown"] is False)
    summary = {"n": len(rows_local), "label_free": n_free, "labeled": len(rows_local) - n_free,
               "by_type": dict(by_type)}
    print(f"built {summary['n']} real charts -> {root}/test.jsonl  (+ test.modal.jsonl for Modal)")
    print(f"  labeled={summary['labeled']}  label_free={summary['label_free']}  by_type={summary['by_type']}")
    return summary


def main():
    p = argparse.ArgumentParser(description="Build a real-chart eval set from hand-labeled charts.")
    p.add_argument("--dir", default="data/real_v0", help="dataset dir with images/ and labels/")
    build(p.parse_args().dir)


if __name__ == "__main__":
    main()
