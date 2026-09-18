"""Build a reviewed real-chart evaluation set from images and source-backed labels.

Each label must include the real-ground-truth-review-v1 receipt documented in
data/real_v0/README.md. It binds actual visible metadata, values, units and
recoverability checks to the image, annotation and retained source data. Missing,
incomplete or stale reviews fail before publication.

Publishes a new snapshot with one portable test.jsonl and retained source bytes.
Historical real_v0 annotations
are rejected; use a new dataset version for corrected, independently reviewed data.

    python -m unrender.eval.build_real_set --dir data/real_dev_v1 --out data/real_eval_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
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


def _build_staged(dirpath: str) -> dict:
    """Validate staged inputs and write their single portable test split."""
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

    rows_local, seen = [], set()
    for lf in label_files:
        label = json.loads(lf.read_text(encoding="utf-8"))
        img_name = label.get("image") or (lf.stem + ".png")
        if not isinstance(img_name, str) or Path(img_name).name != img_name:
            raise ValueError("image must name a file inside images/")
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
        source_path = root / source_file
        if Path(source_file).is_absolute() or not source_path.resolve().is_relative_to(
            root.resolve()
        ):
            raise ValueError("source_data_file must stay inside the dataset")
        source_bytes = source_path.read_bytes()
        if (
            hashlib.sha256(source_bytes).hexdigest()
            != meta["ground_truth_review"]["source_data_sha256"]
        ):
            raise ValueError(f"{lf}: source data changed since review")
        rows_local.append(_row(f"images/{img_name}", label_json, meta))

    (root / "test.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows_local), encoding="utf-8"
    )

    by_type = Counter(r["meta"]["chart_type"] for r in rows_local)
    n_free = sum(1 for r in rows_local if r["meta"]["labels_shown"] is False)
    summary = {
        "n": len(rows_local),
        "label_free": n_free,
        "labeled": len(rows_local) - n_free,
        "by_type": dict(by_type),
    }
    print(f"built {summary['n']} real charts -> {root}/test.jsonl")
    print(
        f"  labeled={summary['labeled']}  label_free={summary['label_free']} "
        f"by_type={summary['by_type']}"
    )
    return summary


def build(dirpath: str, outdir: str | None = None) -> dict:
    """Publish a complete reviewed snapshot atomically in a new directory.

    Inputs are copied into staging, then validated there. A single portable split
    works locally and on Modal. Failed builds never expose a partial test split;
    repeated builds refuse to replace any published directory.
    """
    from unrender.eval.ledger import run_owner

    root = Path(dirpath).resolve()
    destination = Path(outdir).resolve() if outdir else root / "published"
    if destination == root or root.is_relative_to(destination):
        raise ValueError("publication must be separate from the source directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with run_owner(destination.parent / f".{destination.name}.publish-lock"):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("published dataset already exists; choose a new version")
        stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            labels = sorted(
                p for p in (root / "labels").glob("*.json") if not p.name.startswith("_")
            )
            if not labels:
                raise ValueError("no source labels to publish")
            if (root / "collection.json").exists():
                collection = json.loads((root / "collection.json").read_bytes())
                attempts = collection.get("attempts", [])
                ids = [a["id"] for a in attempts]
                if (
                    collection.get("status") != "complete"
                    or not ids
                    or len(set(ids)) != len(ids)
                    or any(a.get("state") != "collected" for a in attempts)
                    or set(ids) != {p.stem for p in labels}
                ):
                    raise ValueError(
                        "collection incomplete; cannot silently omit attempted sources"
                    )
                shutil.copyfile(root / "collection.json", stage / "collection.json")
            for label_path in labels:
                label = json.loads(label_path.read_bytes())
                image = label.get("image") or label_path.stem + ".png"
                source = label.get("source_data_file")
                if not isinstance(source, str) or not source:
                    raise ValueError("reviewed source_data_file is required")
                paths = [label_path.relative_to(root), Path("images") / image, Path(source)]
                for relative in paths:
                    origin = root / relative
                    if relative.is_absolute() or not origin.resolve().is_relative_to(root):
                        raise ValueError("review artifacts must stay inside the source dataset")
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(origin, target)
            summary = _build_staged(str(stage))
            files = {
                p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(stage.rglob("*"))
                if p.is_file()
            }
            (stage / "publication.json").write_text(
                json.dumps(
                    {
                        "contract": "reviewed-real-dataset-v1",
                        "files": files,
                        "n": summary["n"],
                        "status": "complete",
                    },
                    indent=2,
                )
                + "\n"
            )
            for path in stage.rglob("*"):
                if path.is_file():
                    with path.open("rb") as stream:
                        os.fsync(stream.fileno())
            os.rename(stage, destination)
            descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            print(f"Published reviewed snapshot: {destination}")
            return summary
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def main():
    p = argparse.ArgumentParser(description="Build a real-chart eval set from hand-labeled charts.")
    p.add_argument("--dir", required=True, help="reviewed draft with images/ and labels/")
    p.add_argument("--out", required=True, help="new immutable published dataset directory")
    args = p.parse_args()
    build(args.dir, args.out)


if __name__ == "__main__":
    main()
