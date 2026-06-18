"""R000 — oracle-geometry ceiling (the $0 go/no-go gate from RESEARCH_REVIEW.md).

For every chart the existing LoRA was scored on, regenerate its exact ChartSpec
from its seed, capture the renderer's GROUND-TRUTH geometry, decode values
deterministically at several emittable precisions, and score cell@5_exact. This
is the *ceiling*: best case if the model localized geometry perfectly at that
precision. If even this can't clear ~70% on the cardinality-MATCHED bucket
(where the LoRA already gets structure right), the geometry mechanism is too
weak to matter — STOP before any GPU.

    python analysis/r000_oracle_ceiling.py [--preds <predictions.jsonl>] [--seed 5678]
"""

from __future__ import annotations

import argparse
import random
from collections import defaultdict

from unrender.data_gen.chart_specs import random_spec
from unrender.data_gen.geometry import capture_geometry
from unrender.eval.geometry_decode import decode_geometry
from unrender.eval.metrics import aggregate, score_sample
from unrender.eval.score import row_status
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import ChartData, canonical_json
from unrender.schema.validate import parse_chart_json

QUANTS = [None, 4, 3, 2]          # fraction precision (decimals); None = exact
TICKMODES = ["all", 2]            # over-determined LSQ vs brittle 2-anchor


def bucket_of(row) -> str:
    if row_status(row) != "ok":
        return "invalid"
    pred, _ = parse_chart_json(row.get("raw") or "")
    if pred is None:
        return "invalid"
    gt = ChartData.model_validate_json(row["gt"])
    ngt = sum(len(s.points) for s in gt.series)
    npred = sum(len(s.points) for s in pred.series)
    return "matched" if npred == ngt else ("under" if npred < ngt else "over")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preds", default="outputs/modal/qwen3vl4b-lora/predictions.jsonl")
    p.add_argument("--seed", type=int, default=5678)
    p.add_argument("--hard", action="store_true", default=True)
    args = p.parse_args()

    rows = read_jsonl(args.preds)
    print(f"loaded {len(rows)} prediction rows from {args.preds}")

    # scored[(quant, ticks)][bucket] -> list of per-sample score dicts
    scored = {(q, t): defaultdict(list) for q in QUANTS for t in TICKMODES}
    n_specmismatch = n_decodefail = 0

    for row in rows:
        idx = int(row["id"])
        spec = random_spec(random.Random(args.seed + idx), hard=args.hard)
        gt = spec.to_chart_data()
        # correctness check: regenerated spec must reproduce the stored GT exactly
        if canonical_json(gt) != (row["gt"] if isinstance(row["gt"], str) else canonical_json(ChartData.model_validate(row["gt"]))):
            try:
                if canonical_json(gt) != canonical_json(ChartData.model_validate_json(row["gt"])):
                    n_specmismatch += 1
                    continue
            except Exception:
                n_specmismatch += 1
                continue
        b = bucket_of(row)
        labels_shown = (row.get("meta") or {}).get("labels_shown")
        geom = capture_geometry(spec)
        for q in QUANTS:
            for t in TICKMODES:
                dec = decode_geometry(geom, quant=q, n_ticks=t)
                if dec is None:
                    n_decodefail += 1
                    s = score_sample(None, gt, tol=0.05, labels_shown=labels_shown)
                else:
                    s = score_sample(dec, gt, tol=0.05, labels_shown=labels_shown)
                scored[(q, t)][b].append(s)

    print(f"spec-regen mismatches: {n_specmismatch} | decode fails: {n_decodefail}\n")
    qlabel = lambda q: "exact" if q is None else f"{q}dp"

    print("=== R000 oracle-geometry ceiling: cell@5_EXACT (excludes label-free-pie proxy) ===")
    print(f"{'quant':6}{'ticks':6}{'ALL':>9}{'matched':>9}{'under':>9}{'over':>9}{'med_rel%':>10}")
    for q in QUANTS:
        for t in TICKMODES:
            by_b = scored[(q, t)]
            alls = [s for ss in by_b.values() for s in ss]
            a = aggregate(alls)
            row_str = f"{qlabel(q):6}{str(t):6}"
            row_str += f"{a['cell_accuracy_exact']*100:>8.1f}%"
            for b in ("matched", "under", "over"):
                ab = aggregate(by_b[b]) if by_b[b] else {"cell_accuracy_exact": 0}
                row_str += f"{ab.get('cell_accuracy_exact',0)*100:>8.1f}%"
            row_str += f"{a['median_rel_err']*100:>9.2f}%"
            print(row_str)

    # headline gate number: realistic precision (3dp) + over-determined fit, matched bucket
    gate = aggregate(scored[(3, "all")]["matched"])
    val = gate.get("cell_accuracy_exact", 0) * 100
    print(f"\nGATE (3dp, all-tick, matched bucket): cell@5_exact = {val:.1f}%  "
          f"-> {'PASS (>=70)' if val >= 70 else 'FAIL (<70) — STOP geometry'}")
    # bucket sizes
    sizes = {b: len(scored[(None, 'all')][b]) for b in ('matched', 'under', 'over', 'invalid')}
    print(f"bucket sizes: {sizes}")


if __name__ == "__main__":
    main()
