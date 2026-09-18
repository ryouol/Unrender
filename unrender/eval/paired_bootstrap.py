"""Paired chart-level bootstrap comparing two models on the SAME fixed subset.

Version 2 compares semantic cell F1 and retains every attempted input.
Historical preregistration results must be reproduced at their original commit.

The candidate-selection gate uses the following procedure:
the two models are scored on the identical `common300` charts, paired by id, and
the difference in pooled semantic cell F1 is bootstrapped by resampling charts (not points)
with replacement. Reusing `score_sample` keeps the metric identical to the scorer.

    python -m unrender.eval.paired_bootstrap \
        --a outputs/modal/qwen3vl4b-lora/predictions.jsonl --label-a LoRA \
        --b outputs/modal/base4b/predictions.jsonl        --label-b base-4B \
        --subset unrender/eval/subsets/common300.json

Prints pooled cell@5%, the bootstrap mean/95% CI of (A - B), each model's invalid
rate and median relative error, and a PASS/FAIL against the frozen decision rule.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from unrender.eval.metrics import METRIC_VERSION
from unrender.eval.score import score_prediction, validate_rows
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import ChartData

# v2 candidate-selection requirements, not the historical preregistration.
MIN_GAP_PP = 3.0
CI_MUST_EXCLUDE_ZERO = True
A_INVALID_NOT_WORSE = True


def _percentile(sorted_vals, q: float) -> float:
    """Linear-interpolation percentile (q in [0,1]); avoids a numpy dependency."""
    if not sorted_vals:
        return float("nan")
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    if lo >= len(sorted_vals) - 1:
        return sorted_vals[-1]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[lo + 1] * frac


def compare(a_rows, b_rows, ids, tol=0.05, iters=10000, seed=0, decode_a="table", decode_b="table"):
    """Paired chart bootstrap of exact-numeric cell F1, including failed attempts."""
    ids = [str(i) for i in ids]
    if iters < 1:
        raise ValueError("bootstrap iterations must be positive")
    a_by = {str(row["id"]): row for row in validate_rows(a_rows, ids)}
    b_by = {str(row["id"]): row for row in validate_rows(b_rows, ids)}
    counts_a, counts_b = [], []
    invalid_a = invalid_b = 0
    for rid in ids:
        a, b = a_by[rid], b_by[rid]
        if ChartData.model_validate_json(a["gt"]) != ChartData.model_validate_json(b["gt"]) or (
            a.get("meta") or {}
        ).get("labels_shown") != (b.get("meta") or {}).get("labels_shown"):
            raise ValueError(f"ground truth mismatch for paired id {rid}")
        sa, oa = score_prediction(a, tol, decode_a)
        sb, ob = score_prediction(b, tol, decode_b)
        for sample, counts in ((sa, counts_a), (sb, counts_b)):
            counts.append(
                (0, 0)
                if sample["is_proxy"]
                else (
                    2 * sample["n_correct_points"],
                    sample["n_gt_points"] + sample["n_pred_points"],
                )
            )
        invalid_a += oa["status"] != "ok"
        invalid_b += ob["status"] != "ok"
    if not any(den for _, den in counts_a):
        raise ValueError("paired cell F1 requires at least one exact-numeric chart")

    def pooled(counts, indices):
        den = sum(counts[i][1] for i in indices)
        return sum(counts[i][0] for i in indices) / den if den else 0.0

    n = len(ids)
    indices = list(range(n))
    acc_a, acc_b = pooled(counts_a, indices), pooled(counts_b, indices)
    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        sample = [rng.randrange(n) for _ in range(n)]
        diffs.append(pooled(counts_a, sample) - pooled(counts_b, sample))
    diffs.sort()
    return {
        "metric_version": METRIC_VERSION,
        "metric": "cell_f1",
        "n": n,
        "tol": tol,
        "iters": iters,
        "seed": seed,
        "cell_a": acc_a,
        "cell_b": acc_b,
        "gap_pp": (acc_a - acc_b) * 100,
        "boot_mean_pp": statistics.mean(diffs) * 100,
        "ci95_pp": [_percentile(diffs, 0.025) * 100, _percentile(diffs, 0.975) * 100],
        "p_a_gt_b": sum(d > 0 for d in diffs) / iters,
        "invalid_a": invalid_a / n,
        "invalid_b": invalid_b / n,
    }


def verdict(res: dict) -> tuple:
    gap_ok = res["gap_pp"] >= MIN_GAP_PP
    ci_ok = (res["ci95_pp"][0] > 0) if CI_MUST_EXCLUDE_ZERO else True
    inv_ok = (res["invalid_a"] <= res["invalid_b"]) if A_INVALID_NOT_WORSE else True
    passed = gap_ok and ci_ok and inv_ok
    reasons = [
        f"gap>={MIN_GAP_PP}pp: {'yes' if gap_ok else 'NO'} ({res['gap_pp']:+.2f})",
        f"95% CI excludes 0: {'yes' if ci_ok else 'NO'} (lo={res['ci95_pp'][0]:+.2f})",
        f"A invalid not worse: {'yes' if inv_ok else 'NO'} "
        f"({res['invalid_a'] * 100:.1f}% vs {res['invalid_b'] * 100:.1f}%)",
    ]
    return passed, reasons


def main():
    p = argparse.ArgumentParser(
        description="Paired chart-level bootstrap: model A vs model B on a fixed subset."
    )
    p.add_argument(
        "--a", required=True, help="predictions.jsonl for model A (candidate, e.g. LoRA)"
    )
    p.add_argument("--b", required=True, help="predictions.jsonl for model B (control, e.g. base)")
    p.add_argument(
        "--subset", required=True, help="JSON with an 'ids' list — the shared eval subset"
    )
    p.add_argument("--label-a", default="A")
    p.add_argument("--label-b", default="B")
    p.add_argument("--tol", type=float, default=0.05)
    p.add_argument("--iters", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--decode-a",
        choices=["table", "geometry"],
        default="table",
        help="how to decode model A's raw (e.g. geometry for the geometry-LoRA)",
    )
    p.add_argument(
        "--decode-b",
        choices=["table", "geometry"],
        default="table",
        help="how to decode model B's raw",
    )
    p.add_argument("--out", default="", help="optional path to write the result JSON")
    args = p.parse_args()

    ids = json.loads(Path(args.subset).read_text())["ids"]
    res = compare(
        read_jsonl(args.a),
        read_jsonl(args.b),
        ids,
        tol=args.tol,
        iters=args.iters,
        seed=args.seed,
        decode_a=args.decode_a,
        decode_b=args.decode_b,
    )
    passed, reasons = verdict(res)
    la, lb = args.label_a, args.label_b

    print(
        f"\n=== paired bootstrap: {la} vs {lb}  (N={res['n']}, tol={res['tol']:.0%}, "
        f"{res['iters']} resamples, seed={res['seed']}) ==="
    )
    print(f"  cell F1      {la}={res['cell_a'] * 100:.2f}%   {lb}={res['cell_b'] * 100:.2f}%")
    print(
        f"  {la} - {lb}   gap={res['gap_pp']:+.2f} pp   boot mean={res['boot_mean_pp']:+.2f} pp   "
        f"95% CI=[{res['ci95_pp'][0]:+.2f}, {res['ci95_pp'][1]:+.2f}] "
        f"P({la}>{lb})={res['p_a_gt_b']:.3f}"
    )
    print(
        f"  invalid       {la}={res['invalid_a'] * 100:.1f}%   {lb}={res['invalid_b'] * 100:.1f}%"
    )
    print(f"\n  v2 selection gate: {'PASS' if passed else 'FAIL / inconclusive'}")
    for r in reasons:
        print(f"    - {r}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {**res, "passed": passed, "reasons": reasons, "label_a": la, "label_b": lb},
                indent=2,
            )
            + "\n"
        )
        print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
