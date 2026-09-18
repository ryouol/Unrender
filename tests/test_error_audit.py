"""Error attribution must conserve the scorer's cells and never relax identity."""

import hashlib
import json

import pytest

from analysis.error_audit import ROOT, build, clipped_stack_points, explain_row
from unrender.schema.chart_schema import ChartData


def row_with(prediction):
    truth = {
        "chart_type": "bar",
        "title": "Sales",
        "x_axis": {"label": "Quarter", "unit": None},
        "y_axis": {"label": "Sales", "unit": "USD"},
        "series": [{"name": None, "points": [{"x": "Q1", "y": 10.0}, {"x": "Q2", "y": 20.0}]}],
    }
    prediction = prediction(truth) if callable(prediction) else prediction
    return {
        "id": "sample",
        "gt": json.dumps(truth),
        "raw": json.dumps(prediction),
        "meta": {"labels_shown": True},
        "status": "ok",
    }


@pytest.mark.parametrize(
    "change,expected",
    [
        (lambda gt: gt, {"correct": 2}),
        (None, {"raw_unparseable": 2}),
        (lambda gt: {**gt, "chart_type": "line"}, {"chart_type": 2}),
        (lambda gt: {**gt, "y_axis": {"unit": "EUR"}}, {"units": 2}),
        (
            lambda gt: {**gt, "series": [{**gt["series"][0], "name": "Invented"}]},
            {"series_identity_unmatched": 2},
        ),
        (
            lambda gt: {**gt, "series": [{"name": None, "points": [{"x": "Q1", "y": 99.0}]}]},
            {"numeric_value": 1, "point_identity_unmatched": 1},
        ),
        (
            lambda gt: {
                **gt,
                "series": [
                    {"name": None, "points": [{"x": "Q1", "y": 10.0}, {"x": "Q1", "y": 20.0}]}
                ],
            },
            {"point_identity_unmatched": 2},
        ),
    ],
)
def test_first_blocking_condition_matches_strict_scorer(change, expected):
    explained, sample = explain_row(row_with(change))
    actual = {key: value for key, value in explained["point_partition"].items() if value}
    assert actual == expected
    assert sum(actual.values()) == sample["n_gt_points"]
    assert actual.get("correct", 0) == sample["n_correct_points"]


def test_clipping_uses_cumulative_stack_height_and_separates_value_labels():
    gt = ChartData.model_validate(
        {
            "chart_type": "stacked_bar",
            "series": [
                {"name": "A", "points": [{"x": "a", "y": 6.0}]},
                {"name": "B", "points": [{"x": "a", "y": 7.0}]},
                {"name": "C", "points": [{"x": "a", "y": 3.0}]},
            ],
        }
    )
    assert clipped_stack_points(gt, {"y_top": 10, "value_labels_shown": False}) == [[1, 0], [2, 0]]
    assert clipped_stack_points(gt, {"y_top": 10, "value_labels_shown": True}) == []


def test_saved_error_audit_conserves_frozen_scores_and_exposes_visibility_defects():
    report = build()
    expected = {"base": 543, "fair": 2387, "numeric": 2177}
    for arm, correct in expected.items():
        overall = report["arms"][arm]["overall"]
        assert sum(overall["point_partition"].values()) == overall["target_points"] == 8431
        assert overall["point_partition"]["correct"] == correct
    visibility = report["dataset_visibility"]["common300"]
    assert visibility["any_known_visibility_defect"] == 95
    assert visibility["by_defect"] == {"unprinted_single_series_name": 78, "unprinted_unit": 24}
    rows = report["arms"]["fair"]["per_chart"]
    assert sum(bool(row["clipped_value_endpoints"]) for row in rows) == 14
    assert sum(len(row["clipped_value_endpoints"]) for row in rows) == 281


def test_counterfactual_proof_artifacts_are_intact_and_targets_differ():
    root = ROOT / "release/model-error-audit"
    manifest = json.loads((root / "observability-proofs.json").read_text())
    for proof in manifest["original_vs_counterfactual_proofs"]:
        image = (root / proof["image"]).read_bytes()
        labels = (root / proof["targets"]).read_bytes()
        assert hashlib.sha256(image).hexdigest() == proof["image_sha256"]
        assert hashlib.sha256(labels).hexdigest() == proof["targets_sha256"]
        targets = json.loads(labels)
        assert targets["original"] != targets["counterfactual"]
