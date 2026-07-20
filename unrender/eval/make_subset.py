"""Build a fixed, stratified evaluation subset (Next-Experiment-Queue item 1).

A full hf eval is ~9h/1000 charts on an L4, which throttles iteration. This emits
a frozen ~300-chart subset that mirrors the full test distribution across the
slices the review found decisive — chart_type x labels_shown x density band — so
one cheap run is representative of the headline number, and base/LoRA/8B are all
scored on the *identical* charts.

Allocation is proportional to the full set (so the subset's aggregate tracks the
full 1000) with a floor of 1 per non-empty cell, sampled deterministically. The
output is a small JSON of image ids, committed so every run is reproducible.

    python -m unrender.eval.make_subset \
        --data data/synthetic_v1/test.jsonl --n 300 \
        --candidates unrender/eval/subsets/common_pool_494.json \
        --out unrender/eval/subsets/common300.json

`--candidates` restricts the eligible pool to charts that are test in BOTH the
local and Modal splits (the 494 intersection), so common300 cannot contain a
Modal train/val leak the way the unconstrained dev300 did.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from unrender.eval.dataset import load_eval_samples
from unrender.io_utils import fingerprint_ids

# Density bands match MODEL_STATUS_REVIEW.md's table so subset slices line up
# with the full-set diagnosis. n_points = total points across all series.
BANDS = [(20, "<=20"), (35, "21-35"), (50, "36-50"), (10**9, ">50")]


def _band(n_points: int) -> str:
    for hi, name in BANDS:
        if n_points <= hi:
            return name
    return ">50"


def _n_points(sample) -> int:
    return sum(len(s.points) for s in sample.gt.series)


def _key(sample) -> tuple:
    return (sample.meta.get("chart_type"), bool(sample.meta.get("labels_shown")), _band(_n_points(sample)))


def build(data: str, n: int, seed: int, candidates=None, candidates_source=None) -> dict:
    """Draw a stratified subset of ~n ids from `data`, allocated proportional to
    the FULL distribution so the subset's aggregate tracks the full set.

    If `candidates` is given (an id list), only those ids are eligible — used to
    draw common300 from the local∩Modal test intersection so no chart is a Modal
    train/val leak — while target proportions are still measured against the full
    data. Reports total-variation distance to the full distribution and any strata
    the candidate pool could not fill.
    """
    samples = load_eval_samples(data)
    total = len(samples)
    pool = {str(i) for i in candidates} if candidates is not None else None

    cells: dict = defaultdict(list)
    for s in samples:
        cells[_key(s)].append(s.id)

    rng = random.Random(seed)
    chosen: list = []
    shortfall: dict = {}
    # Proportional allocation against FULL cell sizes (floor 1 per non-empty cell),
    # sampling from the eligible candidates in each cell.
    for key in sorted(cells, key=lambda k: tuple(str(x) for x in k)):
        ids_full = cells[key]
        cand = sorted(i for i in ids_full if pool is None or i in pool)
        rng.shuffle(cand)
        take = max(1, round(n * len(ids_full) / total))
        got = cand[:take]
        chosen.extend(got)
        if len(got) < take:
            shortfall["|".join(str(x) for x in key)] = {"want": take, "have": len(got)}
    # Proportional rounding rarely lands exactly on n; trim deterministically.
    rng.shuffle(chosen)
    if len(chosen) > n:
        chosen = chosen[:n]
    chosen_set = set(chosen)

    # Subset strata and total-variation distance to the full distribution.
    sub_counts: dict = defaultdict(int)
    full_counts: dict = defaultdict(int)
    for s in samples:
        k = "|".join(str(x) for x in _key(s))
        full_counts[k] += 1
        if s.id in chosen_set:
            sub_counts[k] += 1

    def fractions(counter):
        tot = sum(counter.values()) or 1
        return {k: v / tot for k, v in counter.items()}

    fp_full, fp_sub = fractions(full_counts), fractions(sub_counts)
    tv = 0.5 * sum(abs(fp_sub.get(k, 0.0) - fp_full.get(k, 0.0)) for k in set(fp_full) | set(fp_sub))

    return {
        "data": data,
        "n_requested": n,
        "n_actual": len(chosen),
        "seed": seed,
        "candidates_source": candidates_source,
        "n_candidates": (len(pool) if pool is not None else None),
        "dataset_fp": fingerprint_ids(s.id for s in samples),
        "subset_fp": fingerprint_ids(chosen),
        "tv_to_full": round(tv, 4),
        "shortfall": dict(sorted(shortfall.items())),
        "strata": dict(sorted(sub_counts.items())),
        "ids": sorted(chosen),
    }


def main():
    p = argparse.ArgumentParser(description="Build a stratified eval subset (frozen id list).")
    p.add_argument("--data", default="data/synthetic_v1/test.jsonl")
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--candidates", default=None,
                   help="JSON with an 'ids' list; restrict the eligible pool to these "
                        "(e.g. the local∩Modal intersection, so common300 has no train/val leak)")
    p.add_argument("--out", default="unrender/eval/subsets/common300.json")
    args = p.parse_args()

    candidates = json.loads(Path(args.candidates).read_text())["ids"] if args.candidates else None
    spec = build(args.data, args.n, args.seed, candidates=candidates, candidates_source=args.candidates)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}  (n={spec['n_actual']} of {args.n} requested, "
          f"{len(spec['strata'])} strata, TV_to_full={spec['tv_to_full']})")
    if spec["shortfall"]:
        print(f"  ⚠ {len(spec['shortfall'])} strata under-filled from the candidate pool:")
        for k, v in spec["shortfall"].items():
            print(f"    {k}: wanted {v['want']}, had {v['have']}")
    for k, v in spec["strata"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
