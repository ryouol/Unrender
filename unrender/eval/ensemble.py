"""Self-consistency merge: k sampled eval runs -> one voted predictions.jsonl.

The frontier-beating inference lever that needs NO retraining: run the same
model k times with sampling (do_sample, temperature ~0.7 — different draws per
run), then vote. A cell (series, x) survives if it appears in >= half of the
parseable runs; its value is the MEDIAN of the sampled values. Sampling noise
cancels; consistent reads survive. Cost scales k x a 4B — still far cheaper
than one frontier call.

The merged row's `raw` is the canonical JSON of the voted chart, so the
standard scorer consumes it exactly like any model output (same repairs, same
metrics — no scorer changes, and the vote never sees GT).

Usage (after k eval runs of the same split with --do-sample, distinct out dirs):
    python -m unrender.eval.ensemble --runs outputs/e1 outputs/e2 outputs/e3 \\
        --out outputs/merged
    python -m unrender.eval.score --predictions outputs/merged/predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Optional

from unrender.eval.metrics import _norm
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import Axis, ChartData, Point, Series, canonical_json
from unrender.schema.validate import parse_chart_json


def _majority(values, default=None):
    """Most common non-None value (ties break by first occurrence)."""
    vals = [v for v in values if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else default


def merge_parses(parses: List[ChartData]) -> Optional[ChartData]:
    """Vote k parsed charts into one. Series align by normalized name (or by
    index for unnamed/single-series); points align by normalized x. A cell
    needs >= ceil(k/2) appearances; y is the median. Surface forms (name/x
    spelling) take the majority variant."""
    if not parses:
        return None
    k = len(parses)
    need = (k + 1) // 2

    # series key -> x key -> list of (y, surface_x); plus name surface forms & order
    cells = defaultdict(lambda: defaultdict(list))
    name_forms = defaultdict(list)
    series_order: List[str] = []
    for p in parses:
        for i, s in enumerate(p.series):
            skey = _norm(s.name) or f"__series_{i}"
            if skey not in series_order:
                series_order.append(skey)
            name_forms[skey].append(s.name)
            for pt in s.points:
                cells[skey][_norm(pt.x)].append((pt.y, pt.x))

    series = []
    for skey in series_order:
        pts = []
        for xkey, ys in cells[skey].items():
            if len(ys) >= need:
                pts.append(Point(x=_majority([x for _, x in ys], xkey),
                                 y=float(statistics.median(y for y, _ in ys))))
        if pts:
            series.append(Series(name=_majority(name_forms[skey]), points=pts))
    if not series:
        return None

    return ChartData(
        chart_type=_majority([p.chart_type for p in parses]),
        title=_majority([p.title for p in parses]),
        x_axis=Axis(label=_majority([p.x_axis.label for p in parses]),
                    unit=_majority([p.x_axis.unit for p in parses])),
        y_axis=Axis(label=_majority([p.y_axis.label for p in parses]),
                    unit=_majority([p.y_axis.unit for p in parses])),
        series=series,
    )


def merge_runs(run_dirs: List[str], out: str) -> Path:
    """Merge k predictions.jsonl files by id -> <out>/predictions.jsonl."""
    runs = [{r["id"]: r for r in read_jsonl(str(Path(d) / "predictions.jsonl"))} for d in run_dirs]
    ids = [i for i in runs[0] if all(i in r for r in runs)]  # vote needs all k present
    dropped = len(runs[0]) - len(ids)
    if dropped:
        print(f"⚠ {dropped} id(s) missing from some run(s) — excluded from the merge")

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    n_voted = 0
    with open(out_dir / "predictions.jsonl", "w", encoding="utf-8") as f:
        for i in ids:
            base = dict(runs[0][i])  # id/image/gt/meta carried from run 1
            parses = [p for r in runs if (p := parse_chart_json(r[i].get("raw") or "")[0])]
            merged = merge_parses(parses)
            if merged is not None:
                base["raw"] = canonical_json(merged)
                base["status"] = "ok"
                base["error"] = None
                n_voted += 1
            f.write(json.dumps(base) + "\n")
    (out_dir / "meta.json").write_text(json.dumps(
        {"ensemble_of": run_dirs, "k": len(run_dirs), "n": len(ids), "n_voted": n_voted},
        indent=2) + "\n")
    print(f"merged {len(run_dirs)} runs over {len(ids)} charts ({n_voted} voted) -> {out_dir}/predictions.jsonl")
    return out_dir / "predictions.jsonl"


def main():
    p = argparse.ArgumentParser(description="Self-consistency merge of k eval runs.")
    p.add_argument("--runs", nargs="+", required=True, help="k eval output dirs (each holding predictions.jsonl)")
    p.add_argument("--out", required=True, help="output dir for the merged predictions.jsonl")
    args = p.parse_args()
    merge_runs(args.runs, args.out)


if __name__ == "__main__":
    main()
