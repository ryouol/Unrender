"""Compare saved predictions on a fixed input set, retaining failed outcomes.

Without --subset, all providers must have identical coverage. An explicit subset
must exist in every file. No success-conditioned or automatic intersection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unrender.eval.dataset import require_reviewed_predictions
from unrender.eval.ledger import (
    LEDGER_NAME,
    load_predictions,
    prediction_metadata,
    require_terminal_attempts,
)
from unrender.eval.metrics import METRIC_VERSION
from unrender.eval.score import TRACKS, score_rows, validate_rows


def _load_providers(report_paths: list[str]) -> list[dict]:
    files = set()
    for name in report_paths:
        path = Path(name)
        if path.is_dir():
            files.update(path.rglob("predictions.jsonl"))
            files.update(ledger.parent / "predictions.jsonl" for ledger in path.rglob(LEDGER_NAME))
        else:
            files.add(path.parent / "predictions.jsonl")
    providers = []
    for path in sorted(files):
        rows = validate_rows(load_predictions(path))
        require_terminal_attempts(rows)
        if not rows:
            raise ValueError(f"empty predictions: {path}")
        meta = prediction_metadata(path)
        name = f"{meta.get('provider') or '?'}:{meta.get('model') or path.parent.name}"
        providers.append({"name": name, "rows": rows, "ids": {str(r["id"]) for r in rows}})
    if not providers:
        raise ValueError("no prediction artifacts found; refusing to write an empty comparison")
    if len({p["name"] for p in providers}) != len(providers):
        raise ValueError("duplicate model names; label each run distinctly in meta.json")
    return providers


def _pct(value) -> str:
    return f"{value * 100:.2f}%" if value is not None else "—"


def build(
    report_paths: list[str],
    out: str,
    title: str = "Unrender — chart-to-data extraction",
    only_ids=None,
) -> str:
    providers = _load_providers(report_paths)
    if only_ids is None:
        ids = providers[0]["ids"]
        if any(p["ids"] != ids for p in providers):
            raise ValueError(
                "coverage differs across providers; supply a preselected complete --subset"
            )
    else:
        ids = list(only_ids)
    reference = None
    for provider in providers:
        selected = validate_rows(provider["rows"], ids)
        require_reviewed_predictions(selected)
        ground_truth = {
            str(r["id"]): (json.loads(r["gt"]), (r.get("meta") or {}).get("labels_shown"))
            for r in selected
        }
        if reference is not None and ground_truth != reference:
            raise ValueError("ground truth differs across providers")
        reference = ground_truth
    lines = [
        f"# {title}",
        "",
        f"Scorer: `{METRIC_VERSION}`. Fixed input set: **N={len(ids)}**.",
        "All recorded failures stay in the primary denominator. Repaired table outputs",
        "earn no primary credit; recovery is diagnostic only. Exact-numeric cell F1",
        "requires matching series, category/date, chart type, units, and value tolerance.",
        "Extra predictions reduce precision. Unlabeled pie proportions are a separate proxy.",
        "Chart exactness requires exact values and all chart metadata; order is immaterial.",
        "",
    ]
    for tol in TRACKS:
        lines += [
            f"## Cell quality at {tol:.0%} tolerance",
            "",
            "| Model | Precision | Recall | F1 | Macro F1 | "
            "Tables within tolerance | Exact charts |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for provider in providers:
            result = score_rows(provider["rows"], tol, only_ids=ids)
            metrics = result["metrics"]
            keys = (
                "cell_precision",
                "cell_recall",
                "cell_f1",
                "macro_cell_f1",
                "table_within_tolerance_rate",
                "chart_exact_rate",
            )
            lines.append(
                "| " + provider["name"] + " | " + " | ".join(_pct(metrics[k]) for k in keys) + " |"
            )
        lines += [""]
    lines += [
        "## Outcomes and diagnostics",
        "",
        "| Model | Raw JSON | Raw schema | Raw semantics | Scored semantics | "
        "Repaired | Model invalid | Infrastructure failure | Conditional F1 | Pie proxy F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in providers:
        result = score_rows(provider["rows"], 0.05, only_ids=ids)
        validity = result["raw_validity"]
        values = [
            provider["name"],
            *[
                _pct(validity[k])
                for k in ("raw_json_valid", "raw_schema_valid", "raw_semantic_valid")
            ],
            _pct(result["metrics"]["semantic_valid_rate"]),
            str(result["n_repaired"]),
            str(result["n_model_invalid"]),
            str(result["n_infra_error"]),
            _pct(result["conditional_model_metrics"].get("cell_f1")),
            _pct(result["metrics"]["pie_proportion_f1"]),
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "Conditional F1 excludes infrastructure failures only and is not the headline.",
        "Per-chart outcomes, denominators and chart-family slices are in the JSON scorer output.",
    ]
    text = "\n".join(lines) + "\n"
    if out:
        Path(out).write_text(text)
    print(text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", nargs="+", default=["outputs/eval_reports"])
    parser.add_argument("--out", default="outputs/eval_reports/COMPARISON.md")
    parser.add_argument("--title", default="Unrender — chart-to-data extraction")
    parser.add_argument("--subset", help="Preselected JSON file with an ids list")
    args = parser.parse_args()
    ids = json.loads(Path(args.subset).read_text())["ids"] if args.subset else None
    build(args.reports, args.out, args.title, ids)


if __name__ == "__main__":
    main()
