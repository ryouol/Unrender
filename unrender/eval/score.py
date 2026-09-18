"""Score a predictions.jsonl against its embedded ground truth.

Reads the file written by run_baselines.py and produces a metrics report. Runs
offline and instantly — re-run with different tolerances for free, no API calls.

Two tolerance tracks are always computed (A5): 5% (headline) and 2% (strict).
All scheduled rows, including infrastructure failures, remain in the primary
denominator. Conditional model metrics are separate. Label-free pies are a
separate proportion proxy (see score_sample).

    python -m unrender.eval.score --predictions outputs/eval_reports/<dir>/predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from unrender.eval.metrics import (
    METRIC_VERSION,
    aggregate,
    classify_status,
    score_sample,
    semantic_errors,
)
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

        try:
            geom = from_target(raw or "")
            return (decode_geometry(geom) if geom else None), []
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            return None, ["invalid_geometry"]
    return parse_chart_json(raw or "")


TRACKS = (0.05, 0.02)  # headline, strict


def row_status(r: dict) -> str:
    """Provider errors take precedence over a stale stored prediction/status."""
    if r.get("error"):
        return "infra_error"
    status = r.get("status") or classify_status(None, r.get("pred"))
    if status not in {"ok", "model_invalid", "infra_error"}:
        raise ValueError(f"unknown outcome status: {status}")
    return status


def validate_rows(rows: Iterable[dict], only_ids=None) -> list[dict]:
    """Library and CLI share duplicate and coverage guards; never shrink N."""
    rows = list(rows)
    ids = [str(row["id"]) for row in rows]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate prediction ids: {duplicates[:5]}")
    if only_ids is None:
        return rows
    requested = [str(key) for key in only_ids]
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("subset must contain unique, nonempty ids")
    missing = set(requested) - set(ids)
    if missing:
        raise ValueError(
            f"subset-coverage failure: {len(missing)} missing ids: {sorted(missing)[:5]}"
        )
    requested_set = set(requested)
    return [row for row in rows if str(row["id"]) in requested_set]


def _strict_json(raw: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def score_prediction(row: dict, tol: float, decode: str = "table") -> tuple[dict, dict]:
    """The same per-attempt definition is used by reports and paired comparisons."""
    try:
        gt = ChartData.model_validate(_strict_json(row["gt"]), strict=True)
        if errors := semantic_errors(gt):
            raise ValueError(", ".join(errors))
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"invalid ground truth for {row['id']}: {exc}") from exc
    infra = row_status(row) == "infra_error"
    raw = row.get("raw") or ""
    raw_json = raw_schema = raw_semantic = False
    strict = None
    if not infra and decode == "table":
        try:
            obj = _strict_json(raw)
            raw_json = True
            strict = ChartData.model_validate(obj, strict=True)
            raw_schema = True
            raw_semantic = not semantic_errors(strict)
        except ValueError:
            pass
    if decode not in {"table", "geometry"}:
        raise ValueError(f"unknown decode mode: {decode}")
    if infra:
        recovered, errors = None, []
    else:
        recovered, errors = _decode_raw(raw, decode)
    # Primary table quality never credits repaired/coerced values. The old parser
    # can alter numeric content; recovery is exposed as a diagnostic only.
    pred = strict if decode == "table" else recovered
    structural = semantic_errors(pred) if pred is not None else ["unparseable"]
    sample = score_sample(pred, gt, tol, (row.get("meta") or {}).get("labels_shown"))
    outcome = {
        "id": str(row["id"]),
        "chart_type": gt.chart_type,
        "labels_shown": (row.get("meta") or {}).get("labels_shown"),
        "status": "infra_error" if infra else ("model_invalid" if structural else "ok"),
        "raw_json_valid": raw_json if decode == "table" else None,
        "raw_schema_valid": raw_schema if decode == "table" else None,
        "raw_semantic_valid": raw_semantic if decode == "table" else None,
        "repaired": bool(recovered is not None and not raw_schema) if decode == "table" else None,
        "recovered_semantic_valid": bool(recovered is not None and not semantic_errors(recovered)),
        "parse_diagnostic_count": len(errors),
        "semantic_errors": structural if not infra else [],
    }
    return sample, outcome


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
                    lambda m, ct=ct: m.get("chart_type") == ct and m.get("labels_shown") is False
                ),
            }
            for ct in chart_types
        },
    }


def score_rows(
    rows: Iterable[dict],
    tol: float,
    only_ids: set | None = None,
    decode: str = "table",
) -> dict:
    rows = validate_rows(rows, only_ids)
    scored, outcomes, conditional = [], [], []
    for row in rows:
        sample, outcome = score_prediction(row, tol, decode)
        outcomes.append(outcome)
        scored.append((outcome, sample))
        if outcome["status"] != "infra_error":
            conditional.append(sample)
    count = len(rows)
    return {
        "metric_version": METRIC_VERSION,
        "metrics": aggregate([sample for _, sample in scored]),
        "conditional_model_metrics": aggregate(conditional),
        "slices": _slice(scored),
        "n_infra_error": sum(o["status"] == "infra_error" for o in outcomes),
        "n_model_invalid": sum(o["status"] == "model_invalid" for o in outcomes),
        "raw_validity": {
            key: sum(bool(o[key]) for o in outcomes) / count
            if count and decode == "table"
            else None
            for key in ("raw_json_valid", "raw_schema_valid", "raw_semantic_valid")
        },
        "n_repaired": sum(bool(o["repaired"]) for o in outcomes),
        "outcomes": outcomes,
    }


def score(
    predictions: str, out: str = "", tols=TRACKS, only_ids=None, decode: str = "table"
) -> dict:
    pred_path = Path(predictions)
    rows = read_jsonl(pred_path)
    try:
        validate_rows(rows, only_ids)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    subset_fp = fingerprint_ids(only_ids) if only_ids is not None else None
    tracks = {f"{t}": score_rows(rows, t, only_ids=only_ids, decode=decode) for t in tols}

    meta_path = pred_path.parent / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    report = {
        "metric_version": METRIC_VERSION,
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
        f"{report['provider']}:{report['model']}" if report["provider"] else pred_path.parent.name
    )
    head = tracks[f"{tols[0]}"]
    infra, inval = head["n_infra_error"], head["n_model_invalid"]
    n = head["metrics"]["n"]
    if infra:
        print(f"Included {infra} infrastructure failure(s) in N; conditional metrics are separate.")
    if not n:
        print(f"=== {label}: no scorable predictions in {pred_path} ===")
        return report
    print(f"\n=== {label}   (N={n}, model_invalid={inval}) ===")
    for t in tols:
        m = tracks[f"{t}"]["metrics"]
        sl = tracks[f"{t}"]["slices"]
        print(
            f"  -- {t:.0%} tol --  semantic_cell_f1={m['cell_f1'] * 100:.1f}%  "
            f"cell_recall={m['cell_recall'] * 100:.1f}%  "
            f"exact_chart={m['chart_exact_rate'] * 100:.1f}%  "
            f"labeled={sl['labeled'].get('cell_accuracy', 0) * 100:.1f}%  "
            f"label_free={sl['label_free'].get('cell_accuracy', 0) * 100:.1f}%"
        )
    print(f"  schema_valid={head['metrics']['schema_valid_rate'] * 100:.1f}%  -> {out_path}")
    return report


def main():
    p = argparse.ArgumentParser(description="Score a predictions.jsonl (5% + 2% tracks).")
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
        help=(
            "table=raw ChartData JSON (default); geometry=geometry program + deterministic decode"
        ),
    )
    args = p.parse_args()
    only_ids, out = None, args.out
    if args.subset:
        only_ids = json.loads(Path(args.subset).read_text())["ids"]
        if not out:  # name the report after the subset so it never clobbers report.json
            out = str(Path(args.predictions).parent / f"report.{Path(args.subset).stem}.json")
    score(args.predictions, out, only_ids=only_ids, decode=args.decode)


if __name__ == "__main__":
    main()
