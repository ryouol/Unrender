"""Score a predictions.jsonl against its embedded ground truth.

Reads the file written by run_baselines.py and produces a metrics report. Runs
offline and instantly — re-run with a different --tol to see sensitivity, no
API calls involved.

    python -m unrender.eval.score --predictions outputs/eval_reports/anthropic__claude-opus-4-8/predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unrender.eval.metrics import aggregate, score_sample
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import ChartData

# Metrics shown as percentages in the printed summary.
_PCT_KEYS = [
    "schema_valid_rate", "cell_accuracy", "chart_exact_rate", "chart_type_acc",
    "title_acc", "x_label_acc", "y_label_acc", "series_name_f1",
]


def score(predictions: str, tol: float, out: str = "") -> dict:
    pred_path = Path(predictions)
    rows = read_jsonl(pred_path)

    scored, skipped = [], 0   # each item: (slice_meta, score_dict)
    for r in rows:
        try:
            gt = ChartData.model_validate_json(r["gt"])  # one bad GT row shouldn't abort the run
        except Exception:
            skipped += 1
            continue
        try:
            pred = ChartData.model_validate(r["pred"]) if r.get("pred") else None
        except Exception:
            pred = None
        m = r.get("meta") or {}
        # chart_type from the GT is authoritative; labels_shown only exists in meta.
        slice_meta = {"labels_shown": m.get("labels_shown"), "chart_type": gt.chart_type}
        scored.append((slice_meta, score_sample(pred, gt, tol=tol)))

    metrics = aggregate([s for _, s in scored])
    slices = _slice(scored)

    meta_path = pred_path.parent / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    report = {"provider": meta.get("provider"), "model": meta.get("model"),
              "tol": tol, "metrics": metrics, "slices": slices}

    out_path = Path(out) if out else pred_path.parent / "report.json"
    out_path.write_text(json.dumps(report, indent=2))

    label = f"{report['provider']}:{report['model']}" if report["provider"] else pred_path.parent.name
    if skipped:
        print(f"⚠  skipped {skipped} row(s) with unparseable ground truth")
    if not metrics["n"]:
        print(f"=== {label}: no scorable predictions in {pred_path} ===")
        return report
    print(f"\n=== {label}   (n={metrics['n']}, tol={tol:.0%}) ===")
    for k in _PCT_KEYS:
        print(f"  {k:<22} {metrics[k]*100:6.2f}%")
    print(f"  {'median_rel_err':<22} {metrics['median_rel_err']*100:6.2f}%")
    print(f"  {'mae':<22} {metrics['mae']:.3f}")
    # The headline slice: how far label-free sits below labeled is the wedge.
    lab, lf = slices["labeled"], slices["label_free"]
    print(f"  {'cell_acc[labeled]':<22} {lab.get('cell_accuracy',0)*100:6.2f}%  (n={lab.get('n',0)})")
    print(f"  {'cell_acc[label-free]':<22} {lf.get('cell_accuracy',0)*100:6.2f}%  (n={lf.get('n',0)})")
    print(f"  -> report: {out_path}")
    return report


def _slice(scored: list) -> dict:
    """Break the per-sample scores out by the dimensions that matter: whether
    values were printed on the chart, and the chart type (with the label-free
    cross, since that's where the wedge against frontier models lives)."""
    def agg_where(pred):
        return aggregate([s for m, s in scored if pred(m)])

    chart_types = sorted({m["chart_type"] for m, _ in scored if m.get("chart_type")})
    return {
        "labeled": agg_where(lambda m: m.get("labels_shown") is True),
        "label_free": agg_where(lambda m: m.get("labels_shown") is False),
        "by_chart_type": {
            ct: {
                "all": agg_where(lambda m, ct=ct: m.get("chart_type") == ct),
                "label_free": agg_where(
                    lambda m, ct=ct: m.get("chart_type") == ct and m.get("labels_shown") is False),
            }
            for ct in chart_types
        },
    }


def main():
    p = argparse.ArgumentParser(description="Score a predictions.jsonl file.")
    p.add_argument("--predictions", required=True, help="path to predictions.jsonl")
    p.add_argument("--tol", type=float, default=0.05, help="relative-error tolerance for a correct cell")
    p.add_argument("--out", default="", help="report path (default report.json next to predictions)")
    args = p.parse_args()
    score(args.predictions, args.tol, args.out)


if __name__ == "__main__":
    main()
