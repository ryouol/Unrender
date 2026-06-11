"""Dump the worst-scored charts for eyeballing — the input to your next two weeks.

Scores every sample in a predictions.jsonl, sorts by cell accuracy (worst first),
and writes a markdown gallery: the chart image, the ground-truth table, and the
model's prediction, so you can see *how* it fails (misread axis scale? dropped a
series? hallucinated values?) and aim the next data-generation round at it.

    python -m unrender.eval.failures --predictions outputs/eval_reports/<model>/predictions.jsonl --n 15
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from unrender.eval.metrics import score_sample
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import ChartData
from unrender.schema.json_to_csv import chart_to_csv


def _cell_acc(sd: dict) -> float:
    return sd["n_correct_points"] / sd["n_gt_points"] if sd["n_gt_points"] else 1.0


def _csv_block(data: ChartData) -> str:
    return "```csv\n" + chart_to_csv(data).strip() + "\n```"


def dump(predictions: str, n: int, tol: float, out: str = "") -> Path:
    pred_path = Path(predictions)
    out_path = Path(out) if out else pred_path.parent / "FAILURES.md"

    scored = []
    for r in read_jsonl(pred_path):
        if r.get("status") == "infra_error":
            continue  # transport failure, not a model attempt — don't show as a failure
        try:
            gt = ChartData.model_validate_json(r["gt"])
        except Exception:
            continue
        try:
            pred = ChartData.model_validate(r["pred"]) if r.get("pred") else None
        except Exception:
            pred = None
        sd = score_sample(pred, gt, tol=tol, labels_shown=(r.get("meta") or {}).get("labels_shown"))
        scored.append((_cell_acc(sd), sd, r, gt, pred))
    scored.sort(key=lambda t: (t[0], -t[1]["n_gt_points"]))  # worst first; bigger charts break ties

    lines = [f"# Worst {min(n, len(scored))} predictions — {pred_path.parent.name}",
             f"\n_Sorted by cell accuracy (within {tol:.0%}). {len(scored)} scored total._\n"]
    for rank, (acc, sd, r, gt, pred) in enumerate(scored[:n], 1):
        meta = r.get("meta") or {}
        rel_img = os.path.relpath(r["image"], out_path.parent)
        lines.append(f"\n## {rank}. `{r['id']}` — cell acc {acc:.0%}  "
                     f"(type={gt.chart_type}, labels_shown={meta.get('labels_shown')}, "
                     f"augmented={meta.get('augmented')})")
        lines.append(f"\n![{r['id']}]({rel_img})\n")
        lines.append("**Ground truth:**\n" + _csv_block(gt))
        if pred is not None:
            lines.append("\n**Prediction:**\n" + _csv_block(pred))
        else:
            raw = (r.get("raw") or "").strip() or "(empty)"
            err = r.get("error") or (r.get("parse_errors") or [""])[0]
            lines.append(f"\n**Prediction:** unparseable — {err}\n```\n{raw[:600]}\n```")

    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_path}  ({min(n, len(scored))} of {len(scored)} samples)")
    return out_path


def main():
    p = argparse.ArgumentParser(description="Dump the worst-scored charts as a markdown gallery.")
    p.add_argument("--predictions", required=True, help="path to predictions.jsonl")
    p.add_argument("--n", type=int, default=15, help="how many worst samples to show")
    p.add_argument("--tol", type=float, default=0.05, help="relative-error tolerance")
    p.add_argument("--out", default="", help="output markdown (default FAILURES.md next to predictions)")
    args = p.parse_args()
    dump(args.predictions, args.n, args.tol, args.out)


if __name__ == "__main__":
    main()
