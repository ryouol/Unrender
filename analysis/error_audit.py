"""Explain historical Common300 errors without changing targets or scoring rules.

The visibility rules describe the historical renderer at commit 904e87d. They
identify known annotation defects, not a complete visual recoverability audit.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from contextlib import suppress
from pathlib import Path

from analysis.reproduce_common300 import ARMS, ROOT, audit_evidence, load_evidence, sha256
from unrender.eval.metrics import (
    METRIC_VERSION,
    _norm,
    _unique_matches,
    _unit,
    _value_correct,
    aggregate,
)
from unrender.eval.score import score_prediction
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import PARSER_VERSION, strict_json

PARTITION_ORDER = (
    "infrastructure_error",
    "raw_unparseable",
    "series_identity_unmatched",
    "point_identity_unmatched",
    "chart_type",
    "units",
    "numeric_value",
    "correct",
)


def visibility_defects(gt: ChartData) -> list[str]:
    """Historical renderer hides every single-series legend and unit-only label."""
    defects = []
    if gt.chart_type in {"bar", "horizontal_bar", "line", "pie"} and any(
        series.name is not None for series in gt.series
    ):
        defects.append("unprinted_single_series_name")
    if gt.y_axis.unit and not gt.y_axis.label:
        defects.append("unprinted_unit")
    return defects


def clipped_stack_points(gt: ChartData, spec: dict | None) -> list[list[int]]:
    if (
        not spec
        or gt.chart_type != "stacked_bar"
        or spec["y_top"] is None
        or spec["value_labels_shown"]
    ):
        return []
    clipped = []
    for point_index in range(len(gt.series[0].points)):
        top = 0.0
        for series_index, series in enumerate(gt.series):
            top += series.points[point_index].y
            if top > spec["y_top"]:
                clipped.append([series_index, point_index])
    return clipped


def explain_row(row: dict, spec: dict | None = None) -> tuple[dict, dict]:
    sample, outcome = score_prediction(row, 0.05)
    gt = ChartData.model_validate_json(row["gt"])
    counts: Counter = Counter()
    aligned = 0
    aligned_numeric_hits = 0
    pred = None
    if outcome["status"] != "infra_error":
        with suppress(ValueError):
            pred = ChartData.model_validate(strict_json(row["raw"]), strict=True)
    if not sample["is_proxy"]:
        if pred is None:
            reason = (
                "infrastructure_error" if outcome["status"] == "infra_error" else "raw_unparseable"
            )
            counts[reason] = sample["n_gt_points"]
        else:
            series_map = _unique_matches(
                [_norm(s.name) for s in gt.series], [_norm(s.name) for s in pred.series]
            )
            units_ok = all(
                _unit(getattr(gt, axis).unit) == _unit(getattr(pred, axis).unit)
                for axis in ("x_axis", "y_axis")
            )
            for gi, gs in enumerate(gt.series):
                if gi not in series_map:
                    counts["series_identity_unmatched"] += len(gs.points)
                    continue
                ps = pred.series[series_map[gi]]
                point_map = _unique_matches(
                    [_norm(p.x) for p in gs.points], [_norm(p.x) for p in ps.points]
                )
                for gi_point, point in enumerate(gs.points):
                    if gi_point not in point_map:
                        counts["point_identity_unmatched"] += 1
                        continue
                    aligned += 1
                    numeric_hit = _value_correct(ps.points[point_map[gi_point]].y, point.y, 0.05)
                    aligned_numeric_hits += numeric_hit
                    if pred.chart_type != gt.chart_type:
                        reason = "chart_type"
                    elif not units_ok:
                        reason = "units"
                    elif not numeric_hit:
                        reason = "numeric_value"
                    else:
                        reason = "correct"
                    counts[reason] += 1
        if sum(counts.values()) != sample["n_gt_points"]:
            raise ValueError(f"error attribution did not cover every target point: {row['id']}")
        if counts["correct"] != sample["n_correct_points"]:
            raise ValueError(f"error attribution disagrees with the primary scorer: {row['id']}")
    defects = visibility_defects(gt)
    clipped = clipped_stack_points(gt, spec)
    if clipped:
        defects.append("clipped_unlabeled_stack_values")
    return {
        "id": str(row["id"]),
        "chart_type": gt.chart_type,
        "labels_shown": outcome["labels_shown"],
        "augmented": (row.get("meta") or {}).get("augmented"),
        "is_proxy": sample["is_proxy"],
        "known_visibility_defects": defects,
        "clipped_value_endpoints": clipped,
        "raw_schema_valid": outcome["raw_schema_valid"],
        "raw_semantic_valid": outcome["raw_semantic_valid"],
        "semantic_errors": outcome["semantic_errors"],
        "target_points": sample["n_gt_points"],
        "predicted_points": sample["n_pred_points"],
        "point_partition": {key: counts[key] for key in PARTITION_ORDER},
        "identity_aligned_points": aligned if not sample["is_proxy"] else None,
        "identity_unmatched_predicted_points": sample["n_pred_points"] - aligned
        if not sample["is_proxy"]
        else None,
        "aligned_numeric_hits_ignoring_type_units": aligned_numeric_hits
        if not sample["is_proxy"]
        else None,
        "truth_series_names": [s.name for s in gt.series],
        "predicted_series_names": [s.name for s in pred.series] if pred else None,
        "truth_units": [gt.x_axis.unit, gt.y_axis.unit],
        "predicted_units": [pred.x_axis.unit, pred.y_axis.unit] if pred else None,
    }, sample


def summarize(explained: list[tuple[dict, dict]]) -> dict:
    rows = [row for row, _ in explained]
    exact = [row for row in rows if not row["is_proxy"]]
    counts = {key: sum(row["point_partition"][key] for row in exact) for key in PARTITION_ORDER}
    return {
        "charts": len(rows),
        "exact_numeric_charts": len(exact),
        "proxy_charts": len(rows) - len(exact),
        "target_points": sum(row["target_points"] for row in exact),
        "predicted_points": sum(row["predicted_points"] for row in exact),
        "point_partition": counts,
        "identity_unmatched_predicted_points": sum(
            row["identity_unmatched_predicted_points"] for row in exact
        ),
        "frozen_target_metrics": aggregate([sample for _, sample in explained]),
    }


def build() -> dict:
    evidence = load_evidence()
    audit_evidence(evidence)
    proof_root = ROOT / "release/model-error-audit"
    proof_manifest = json.loads((proof_root / "observability-proofs.json").read_text())
    spec_source = proof_manifest["reconstructed_specs"]
    compressed = (proof_root / spec_source["file"]).read_bytes()
    if sha256(compressed) != spec_source["compressed_sha256"]:
        raise ValueError("reconstructed-spec compressed hash mismatch")
    raw = gzip.decompress(compressed)
    if sha256(raw) != spec_source["sha256"]:
        raise ValueError("reconstructed-spec content hash mismatch")
    spec_rows = [json.loads(line) for line in raw.splitlines()]
    specs = {row["id"]: row for row in spec_rows}
    if len(specs) != len(spec_rows) or set(specs) != set(evidence["subset"]["ids"]):
        raise ValueError("reconstructed-spec coverage mismatch")
    for row in evidence["rows"]["fair"]:
        if specs[row["id"]]["target_sha256"] != sha256(row["gt"].encode()):
            raise ValueError("reconstructed-spec target mismatch")
    result = {
        "metric_version": METRIC_VERSION,
        "parser_version": PARSER_VERSION,
        "tol": 0.05,
        "status": "diagnostic_on_frozen_targets_with_known_visibility_defects",
        "partition_order": PARTITION_ORDER,
        "partition_note": "First blocking condition, not causal attribution; errors can overlap.",
        "manifest_sha256": sha256((ROOT / "release/common300-evidence/manifest.json").read_bytes()),
        "reconstructed_spec_sha256": spec_source["sha256"],
        "source_hashes": {
            name: sha256((ROOT / name).read_bytes())
            for name in (
                "analysis/error_audit.py",
                "unrender/eval/score.py",
                "unrender/eval/metrics.py",
                "unrender/schema/validate.py",
            )
        },
        "arms": {},
        "dataset_visibility": {},
    }
    common_ids = set(evidence["subset"]["ids"])
    for name in ("train_v0", "train_v1", "test_v1"):
        rows = evidence["rows"][name]
        flags = [
            visibility_defects(ChartData.model_validate_json(row["messages"][1]["content"]))
            for row in rows
        ]
        result["dataset_visibility"][name] = {
            "rows": len(rows),
            "any_known_visibility_defect": sum(bool(item) for item in flags),
            "by_defect": dict(Counter(flag for item in flags for flag in item)),
            "clipping_audited": False,
        }
    common_flags = [
        visibility_defects(ChartData.model_validate_json(row["gt"]))
        for row in evidence["rows"]["fair"]
        if row["id"] in common_ids
    ]
    result["dataset_visibility"]["common300"] = {
        "rows": len(common_flags),
        "any_known_visibility_defect": sum(bool(item) for item in common_flags),
        "by_defect": dict(Counter(flag for item in common_flags for flag in item)),
        "scope": "metadata-only; see arm per-chart records for clipping checks",
    }
    for arm in ARMS:
        explained = [explain_row(row, specs[row["id"]]["spec"]) for row in evidence["rows"][arm]]
        result["arms"][arm] = {
            "overall": summarize(explained),
            "known_visibility_defect": summarize(
                [(row, sample) for row, sample in explained if row["known_visibility_defects"]]
            ),
            "no_known_visibility_defect": summarize(
                [(row, sample) for row, sample in explained if not row["known_visibility_defects"]]
            ),
            "by_chart_type": {
                family: summarize([(r, s) for r, s in explained if r["chart_type"] == family])
                for family in sorted({r["chart_type"] for r, _ in explained})
            },
            "per_chart": [row for row, _ in explained],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/model-error-audit.json")
    args = parser.parse_args()
    report = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for arm, data in report["arms"].items():
        print(arm, data["overall"]["point_partition"])
    print(f"Diagnostic report: {args.out}")


if __name__ == "__main__":
    main()
