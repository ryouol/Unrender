"""Verify the scorer discriminates correctly — without any API calls.

Uses the mock providers' logic: a perfect prediction must score ~100%, a
value error beyond tolerance must drop a cell, and unparseable output must
register as schema-invalid with zero accuracy.
"""

import math
import random

from unrender.data_gen.chart_specs import random_spec
from unrender.eval.metrics import aggregate, score_sample
from unrender.eval.providers import noisy_provider, perfect_provider
from unrender.schema.chart_schema import (
    Axis,
    ChartData,
    Point,
    Series,
    canonical_json,
)
from unrender.schema.validate import parse_chart_json


def _gt():
    return ChartData(
        chart_type="bar",
        title="Revenue by Year",
        x_axis=Axis(label="Year"),
        y_axis=Axis(label="Revenue", unit="USD"),
        series=[Series(name="Revenue", points=[
            Point(x="2020", y=100.0), Point(x="2021", y=200.0), Point(x="2022", y=300.0)])],
    )


def test_perfect_prediction_scores_full():
    gt = _gt()
    s = score_sample(gt, gt)
    assert s["schema_valid"] == 1
    assert s["n_correct_points"] == s["n_gt_points"] == 3
    assert s["chart_exact"] == 1
    agg = aggregate([s])
    assert agg["cell_accuracy"] == 1.0
    assert agg["chart_exact_rate"] == 1.0


def test_value_beyond_tolerance_drops_cell():
    gt = _gt()
    pred = gt.model_copy(deep=True)
    pred.series[0].points[1].y = 215.0   # +7.5% on a gt of 200 -> outside 5%
    s = score_sample(pred, gt, tol=0.05)
    assert s["n_correct_points"] == 2 and s["chart_exact"] == 0
    # Same error is fine under a 10% tolerance.
    assert score_sample(pred, gt, tol=0.10)["n_correct_points"] == 3


def test_series_alignment_survives_reordering():
    gt = ChartData(chart_type="multi_line", series=[
        Series(name="North", points=[Point(x="Q1", y=10.0), Point(x="Q2", y=20.0)]),
        Series(name="South", points=[Point(x="Q1", y=30.0), Point(x="Q2", y=40.0)])])
    pred = ChartData(chart_type="multi_line", series=[
        Series(name="South", points=[Point(x="Q2", y=40.0), Point(x="Q1", y=30.0)]),
        Series(name="North", points=[Point(x="Q1", y=10.0), Point(x="Q2", y=20.0)])])
    s = score_sample(pred, gt)
    assert s["n_correct_points"] == 4   # matched by name + x despite shuffling


def test_unparseable_prediction_is_total_miss():
    gt = _gt()
    pred, _ = parse_chart_json("not json at all")
    assert pred is None
    s = score_sample(pred, gt)
    assert s["schema_valid"] == 0 and s["n_correct_points"] == 0
    assert aggregate([s])["cell_accuracy"] == 0.0


def test_mock_providers_bracket_the_metric():
    """perfect -> 1.0; noisy -> strictly between 0 and 1 across a batch."""
    perfect_scores, noisy_scores = [], []
    rng = random.Random(0)
    for seed in range(60):
        gt = random_spec(random.Random(seed)).to_chart_data()
        gt_json = canonical_json(gt)

        p_pred, _ = parse_chart_json(perfect_provider("", "", "", gt_json=gt_json))
        perfect_scores.append(score_sample(p_pred, gt))

        n_pred, _ = parse_chart_json(noisy_provider("", "", "", gt_json=gt_json, rng=rng))
        noisy_scores.append(score_sample(n_pred, gt))

    assert aggregate(perfect_scores)["cell_accuracy"] == 1.0
    noisy_acc = aggregate(noisy_scores)["cell_accuracy"]
    assert 0.0 < noisy_acc < 1.0, noisy_acc


def test_series_alignment_survives_unnamed_predicted_series():
    """Reordered prediction with one missing series name must still align by
    name where it can and positionally for the rest (regression guard)."""
    gt = ChartData(chart_type="multi_line", series=[
        Series(name="North", points=[Point(x="Q1", y=10.0), Point(x="Q2", y=20.0)]),
        Series(name="South", points=[Point(x="Q1", y=30.0), Point(x="Q2", y=40.0)])])
    pred = ChartData(chart_type="multi_line", series=[
        Series(name="South", points=[Point(x="Q2", y=40.0), Point(x="Q1", y=30.0)]),
        Series(name=None, points=[Point(x="Q1", y=10.0), Point(x="Q2", y=20.0)])])
    assert score_sample(pred, gt)["n_correct_points"] == 4


def test_nonfinite_prediction_is_miss_not_poison():
    """A NaN/Inf predicted value counts as a miss and must not turn aggregate
    error metrics into NaN."""
    gt = _gt()
    pred = gt.model_copy(deep=True)
    pred.series[0].points[1].y = float("inf")
    s = score_sample(pred, gt)
    agg = aggregate([s])
    assert s["n_correct_points"] == 2
    assert math.isfinite(agg["mae"]) and math.isfinite(agg["median_rel_err"])


def test_score_cli_handles_empty_predictions(tmp_path):
    """An all-failed (empty) predictions file must report n=0, not crash."""
    from unrender.eval.score import score

    pred_file = tmp_path / "predictions.jsonl"
    pred_file.write_text("")
    report = score(str(pred_file))
    assert report["tracks"]["0.05"]["metrics"]["n"] == 0


def test_classify_status():
    from unrender.eval.metrics import classify_status
    assert classify_status("RateLimitError: 429", None) == "infra_error"
    assert classify_status(None, None) == "model_invalid"
    assert classify_status(None, {"chart_type": "bar"}) == "ok"


def test_repair_maps_key_synonyms():
    """category/label/name->x, value/amount->y, data/values->points (A2)."""
    raw = ('{"chart_type":"bar","series":[{"name":"Rev",'
           '"data":[{"category":"Jan","value":10},{"label":"Feb","amount":20}]}]}')
    parsed, _ = parse_chart_json(raw)
    assert parsed is not None
    pts = parsed.series[0].points
    assert parsed.series[0].name == "Rev"          # series 'name' preserved
    assert (pts[0].x, pts[0].y) == ("Jan", 10.0)   # category->x, value->y
    assert (pts[1].x, pts[1].y) == ("Feb", 20.0)   # label->x, amount->y


def test_pie_label_free_scored_on_proportions():
    """A label-free pie with correct proportions but wrong absolute scale scores
    100% (proportions are all that's recoverable); a labeled pie does not (A3)."""
    gt = ChartData(chart_type="pie", series=[Series(name=None, points=[
        Point(x="A", y=200.0), Point(x="B", y=300.0), Point(x="C", y=500.0)])])
    pred = ChartData(chart_type="pie", series=[Series(name=None, points=[  # same shares, /10 scale
        Point(x="A", y=20.0), Point(x="B", y=30.0), Point(x="C", y=50.0)])])
    free = score_sample(pred, gt, labels_shown=False)
    assert free["n_correct_points"] == 3            # proportions match
    labeled = score_sample(pred, gt, labels_shown=True)
    assert labeled["n_correct_points"] == 0         # absolute values are 10x off
