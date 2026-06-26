"""Score a predictions.jsonl against its embedded ground truth.

Reads the file written by run_baselines.py and produces a metrics report. Runs
offline and instantly — re-run with different tolerances for free, no API calls.

Two tolerance tracks are always computed (A5): 5% (headline) and 2% (strict).
infra_error rows (rate-limit/quota/network — see classify_status) are EXCLUDED
from N; model_invalid rows ARE counted as misses. Label-free pies are scored on
proportions (see score_sample).

    python -m unrender.eval.score --predictions outputs/eval_reports/<dir>/predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from unrender.eval.metrics import aggregate, classify_status, score_sample
from unrender.io_utils import fingerprint_ids, read_jsonl
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import parse_chart_json


def _decode_raw(raw: str, mode: str):
    """Turn a saved raw model response into a ChartData. `table` = parse JSON
    directly (the default arm); `geometry` = parse the geometry program and run
    the deterministic pixel->value decode (the geometry-supervision arm). Both
    re-derive from the SAVED RAW, so re-scoring stays free."""
    if mode == "geometry":
        from unrender.data_gen.geometry_target import from_target
        from unrender.eval.geometry_decode import decode_geometry

        geom = from_target(raw or "")
        return (decode_geometry(geom) if geom else None), []
    return parse_chart_json(raw or "")


TRACKS = (0.05, 0.02)  # headline, strict


def row_status(r: dict) -> str:
    """Status of a saved row, deriving it for old rows that predate the field."""
    return r.get("status") or classify_status(r.get("error"), r.get("pred"))


def _slice(scored: list) -> dict:
    """Break per-sample scores out by labels_shown and chart type (+ the
    label-free cross per type, where the wedge would live)."""

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
                    lambda m, ct=ct: (
                        m.get("chart_type") == ct and m.get("labels_shown") is False
                    )
                ),
            }
            for ct in chart_types
        },
    }


def score_rows(
    rows: Iterable[dict],
    tol: float,
    only_ids: Optional[set] = None,
    decode: str = "table",
) -> dict:
    """Score a set of prediction rows at one tolerance. Shared by the per-provider
    report and the cross-provider intersection table.

    only_ids: if given, score only rows whose id is in the set (intersection, A6).
    decode: "table" (parse raw as ChartData JSON) or "geometry" (parse the geometry
            program and deterministically decode values — the geometry arm).
    """
    scored, n_infra, n_invalid, n_skipped = [], 0, 0, 0
    for r in rows:
        if only_ids is not None and r["id"] not in only_ids:
            continue
        if row_status(r) == "infra_error":  # never saw the image — not a miss (A1)
            n_infra += 1
            continue
        try:
            gt = ChartData.model_validate_json(r["gt"])
        except Exception:
            n_skipped += 1
            continue
        # Re-derive from the SAVED RAW (A4) instead of trusting the stored pred —
        # so scorer/repair/decoder improvements re-score for free.
        pred, _ = _decode_raw(r.get("raw") or "", decode)
        n_invalid += int(pred is None)
        m = r.get("meta") or {}
        slice_meta = {
            "labels_shown": m.get("labels_shown"),
            "chart_type": gt.chart_type,
        }
        scored.append(
            (
                slice_meta,
                score_sample(pred, gt, tol=tol, labels_shown=m.get("labels_shown")),
            )
        )
    return {
        "metrics": aggregate([s for _, s in scored]),
        "slices": _slice(scored),
        "n_infra_error": n_infra,
        "n_model_invalid": n_invalid,
        "n_skipped_gt": n_skipped,
    }


def score(
    predictions: str, out: str = "", tols=TRACKS, only_ids=None, decode: str = "table"
) -> dict:
    pred_path = Path(predictions)
    rows = read_jsonl(pred_path)
    dup = [i for i, c in Counter(str(r["id"]) for r in rows).items() if c > 1]
    if dup:
        raise SystemExit(
            f"{pred_path} has {len(dup)} duplicate id(s) (e.g. {dup[:5]}) — "
            f"double-counted charts skew the metric. Dedup the file before scoring."
        )
    subset_fp = None
    if only_ids is not None:
        only_ids = {str(i) for i in only_ids}
        subset_fp = fingerprint_ids(only_ids)
        # STRICT subset-coverage: a subset rescore must find every requested id in
        # the predictions, else N is silently smaller than intended (the dev300 bug).
        missing = only_ids - {str(r["id"]) for r in rows}
        if missing:
            raise SystemExit(
                f"subset-coverage failure: {len(missing)}/{len(only_ids)} subset ids are absent "
                f"from {pred_path} (e.g. {sorted(missing)[:5]}). Wrong predictions/subset pair — "
                f"refusing to score a smaller, unbalanced N."
            )
    tracks = {
        f"{t}": score_rows(rows, t, only_ids=only_ids, decode=decode) for t in tols
    }

    meta_path = pred_path.parent / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    report = {
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "dataset_fp": fingerprint_ids(r["id"] for r in rows),
        "subset_fp": subset_fp,
        "tracks": tracks,
    }

    # Never clobber the full-set report.json with a subset rescore (the score.py:99
    # bug): a subset score defaults to a distinct, self-describing filename.
    if out:
        out_path = Path(out)
    elif only_ids is not None:
        out_path = pred_path.parent / f"report.subset-{subset_fp}.json"
    else:
        out_path = pred_path.parent / "report.json"
    out_path.write_text(json.dumps(report, indent=2))

    label = (
        f"{report['provider']}:{report['model']}"
        if report["provider"]
        else pred_path.parent.name
    )
    head = tracks[f"{tols[0]}"]
    infra, inval = head["n_infra_error"], head["n_model_invalid"]
    n = head["metrics"]["n"]
    if infra:
        print(
            f"⚠  excluded {infra} infra_error call(s) from N (rate limit/quota/network)"
        )
    if not n:
        print(f"=== {label}: no scorable predictions in {pred_path} ===")
        return report
    print(f"\n=== {label}   (N={n}, model_invalid={inval}) ===")
    for t in tols:
        m = tracks[f"{t}"]["metrics"]
        sl = tracks[f"{t}"]["slices"]
        print(
            f"  -- {t:.0%} tol --  cell={m['cell_accuracy'] * 100:.1f}%  "
            f"cell_exact={m.get('cell_accuracy_exact', 0) * 100:.1f}%  "
            f"exact_chart={m['chart_exact_rate'] * 100:.1f}%  "
            f"labeled={sl['labeled'].get('cell_accuracy', 0) * 100:.1f}%  "
            f"label_free={sl['label_free'].get('cell_accuracy', 0) * 100:.1f}%"
        )
    print(
        f"  schema_valid={head['metrics']['schema_valid_rate'] * 100:.1f}%  -> {out_path}"
    )
    return report


def main():
    p = argparse.ArgumentParser(
        description="Score a predictions.jsonl (5% + 2% tracks)."
    )
    p.add_argument("--predictions", required=True)
    p.add_argument("--out", default="")
    p.add_argument(
        "--subset",
        default=None,
        help="JSON file with an 'ids' list — score ONLY those (free re-score on a fixed subset)",
    )
    p.add_argument(
        "--decode",
        choices=["table", "geometry"],
        default="table",
        help="how to turn raw into values: table=ChartData JSON (default); geometry=geometry program + deterministic decode",
    )
    args = p.parse_args()
    only_ids, out = None, args.out
    if args.subset:
        only_ids = json.loads(Path(args.subset).read_text())["ids"]
        if not out:  # name the report after the subset so it never clobbers report.json
            out = str(
                Path(args.predictions).parent / f"report.{Path(args.subset).stem}.json"
            )
    score(args.predictions, out, only_ids=only_ids, decode=args.decode)


if __name__ == "__main__":
    main()
