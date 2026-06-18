"""Paired chart-level bootstrap comparing two models on the SAME fixed subset.

This is the preregistered analysis for the base-vs-LoRA gate (PREREGISTRATION.md):
the two models are scored on the identical `common300` charts, paired by id, and
the difference in pooled cell@5% is bootstrapped by resampling charts (not points)
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
from pathlib import Path

from unrender.eval.metrics import aggregate, score_sample
from unrender.eval.score import row_status
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import parse_chart_json

# Frozen gate (see PREREGISTRATION.md). A = candidate (LoRA), B = control (base).
MIN_GAP_PP = 3.0          # A must beat B by at least this many points at cell@5%
CI_MUST_EXCLUDE_ZERO = True
A_INVALID_NOT_WORSE = True


def _score_one(row: dict, tol: float, decode: str = "table"):
    """Per-chart score, identical to score_rows: re-derive from the saved raw
    (table JSON or geometry program), score against gt. Returns (score_dict,
    n_correct, n_gt, invalid)."""
    from unrender.eval.score import _decode_raw
    gt = ChartData.model_validate_json(row["gt"])
    pred, _ = _decode_raw(row.get("raw") or "", decode)
    m = row.get("meta") or {}
    s = score_sample(pred, gt, tol=tol, labels_shown=m.get("labels_shown"))
    return s, s["n_correct_points"], s["n_gt_points"], pred is None


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


def _index(rows, label):
    by_id = {}
    for r in rows:
        rid = str(r["id"])
        if rid in by_id:
            raise SystemExit(f"{label}: duplicate id {rid} in predictions — dedup before comparing.")
        by_id[rid] = r
    return by_id


def compare(a_rows, b_rows, ids, tol=0.05, iters=10000, seed=0, decode_a="table", decode_b="table"):
    a_by, b_by = _index(a_rows, "A"), _index(b_rows, "B")
    ids = [str(i) for i in ids]
    if len(ids) != len(set(ids)):
        raise SystemExit("subset has duplicate ids.")
    for label, by in (("A", a_by), ("B", b_by)):
        missing = set(ids) - set(by)
        if missing:
            raise SystemExit(f"coverage failure: {len(missing)}/{len(ids)} subset ids absent "
                             f"from model {label} (e.g. {sorted(missing)[:5]}).")

    nc_a, ng_a, nc_b, ng_b = [], [], [], []
    inv_a = inv_b = 0
    sa_all, sb_all = [], []
    for rid in ids:
        sa, ca, ga, ia = _score_one(a_by[rid], tol, decode_a)
        sb, cb, gb, ib = _score_one(b_by[rid], tol, decode_b)
        nc_a.append(ca); ng_a.append(ga); nc_b.append(cb); ng_b.append(gb)
        inv_a += int(ia); inv_b += int(ib)
        sa_all.append(sa); sb_all.append(sb)

    def pooled(nc, ng, idxs):
        tot = sum(ng[i] for i in idxs)
        return (sum(nc[i] for i in idxs) / tot) if tot else 0.0

    n = len(ids)
    all_idx = list(range(n))
    acc_a = pooled(nc_a, ng_a, all_idx)
    acc_b = pooled(nc_b, ng_b, all_idx)

    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        idxs = [rng.randrange(n) for _ in range(n)]  # resample CHARTS with replacement
        diffs.append(pooled(nc_a, ng_a, idxs) - pooled(nc_b, ng_b, idxs))
    diffs.sort()
    ci_lo, ci_hi = _percentile(diffs, 0.025), _percentile(diffs, 0.975)
    mean_diff = sum(diffs) / len(diffs)
    p_gt0 = sum(d > 0 for d in diffs) / len(diffs)

    return {
        "n": n, "tol": tol, "iters": iters, "seed": seed,
        "cell_a": acc_a, "cell_b": acc_b, "gap_pp": (acc_a - acc_b) * 100,
        "boot_mean_pp": mean_diff * 100, "ci95_pp": [ci_lo * 100, ci_hi * 100],
        "p_a_gt_b": p_gt0,
        "invalid_a": inv_a / n, "invalid_b": inv_b / n,
        "median_rel_err_a": aggregate(sa_all)["median_rel_err"],
        "median_rel_err_b": aggregate(sb_all)["median_rel_err"],
    }


def verdict(res: dict) -> tuple:
    gap_ok = res["gap_pp"] >= MIN_GAP_PP
    ci_ok = (res["ci95_pp"][0] > 0) if CI_MUST_EXCLUDE_ZERO else True
    inv_ok = (res["invalid_a"] <= res["invalid_b"]) if A_INVALID_NOT_WORSE else True
    passed = gap_ok and ci_ok and inv_ok
    reasons = [
        f"gap>={MIN_GAP_PP}pp: {'yes' if gap_ok else 'NO'} ({res['gap_pp']:+.2f})",
        f"95% CI excludes 0: {'yes' if ci_ok else 'NO'} (lo={res['ci95_pp'][0]:+.2f})",
        f"A invalid not worse: {'yes' if inv_ok else 'NO'} ({res['invalid_a']*100:.1f}% vs {res['invalid_b']*100:.1f}%)",
    ]
    return passed, reasons


def main():
    p = argparse.ArgumentParser(description="Paired chart-level bootstrap: model A vs model B on a fixed subset.")
    p.add_argument("--a", required=True, help="predictions.jsonl for model A (candidate, e.g. LoRA)")
    p.add_argument("--b", required=True, help="predictions.jsonl for model B (control, e.g. base)")
    p.add_argument("--subset", required=True, help="JSON with an 'ids' list — the shared eval subset")
    p.add_argument("--label-a", default="A")
    p.add_argument("--label-b", default="B")
    p.add_argument("--tol", type=float, default=0.05)
    p.add_argument("--iters", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--decode-a", choices=["table", "geometry"], default="table", help="how to decode model A's raw (e.g. geometry for the geometry-LoRA)")
    p.add_argument("--decode-b", choices=["table", "geometry"], default="table", help="how to decode model B's raw")
    p.add_argument("--out", default="", help="optional path to write the result JSON")
    args = p.parse_args()

    ids = json.loads(Path(args.subset).read_text())["ids"]
    res = compare(read_jsonl(args.a), read_jsonl(args.b), ids,
                  tol=args.tol, iters=args.iters, seed=args.seed,
                  decode_a=args.decode_a, decode_b=args.decode_b)
    passed, reasons = verdict(res)
    la, lb = args.label_a, args.label_b

    print(f"\n=== paired bootstrap: {la} vs {lb}  (N={res['n']}, tol={res['tol']:.0%}, "
          f"{res['iters']} resamples, seed={res['seed']}) ===")
    print(f"  cell@5%      {la}={res['cell_a']*100:.2f}%   {lb}={res['cell_b']*100:.2f}%")
    print(f"  {la} - {lb}   gap={res['gap_pp']:+.2f} pp   boot mean={res['boot_mean_pp']:+.2f} pp   "
          f"95% CI=[{res['ci95_pp'][0]:+.2f}, {res['ci95_pp'][1]:+.2f}]   P({la}>{lb})={res['p_a_gt_b']:.3f}")
    print(f"  invalid       {la}={res['invalid_a']*100:.1f}%   {lb}={res['invalid_b']*100:.1f}%")
    print(f"  median |err|  {la}={res['median_rel_err_a']*100:.1f}%   {lb}={res['median_rel_err_b']*100:.1f}%")
    print(f"\n  preregistered gate: {'PASS — fine-tuning helped' if passed else 'FAIL / inconclusive'}")
    for r in reasons:
        print(f"    - {r}")

    if args.out:
        Path(args.out).write_text(json.dumps({**res, "passed": passed, "reasons": reasons,
                                              "label_a": la, "label_b": lb}, indent=2) + "\n")
        print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
