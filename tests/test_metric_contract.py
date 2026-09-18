"""Adversarial, all-attempt acceptance tests for the v2 evaluation contract."""

import json

import pytest

from unrender.eval.metrics import METRIC_VERSION, _norm, aggregate, score_sample
from unrender.eval.paired_bootstrap import compare
from unrender.eval.report import build
from unrender.eval.score import score_rows
from unrender.schema.chart_schema import ChartData


def chart():
    return ChartData.model_validate(
        {
            "chart_type": "bar",
            "title": "Revenue",
            "x_axis": {"label": "Month"},
            "y_axis": {"label": "Revenue", "unit": "USD millions"},
            "series": [
                {
                    "name": "Revenue",
                    "points": [{"x": "2024-01", "y": 10}, {"x": "2024-02", "y": 20}],
                }
            ],
        }
    )


def row(key="a", *, raw=None, error=None):
    return {
        "id": key,
        "gt": chart().model_dump_json(),
        "raw": chart().model_dump_json() if raw is None else raw,
        "status": "infra_error" if error else "ok",
        "error": error,
        "meta": {"labels_shown": True},
    }


@pytest.mark.parametrize("key", ["2024-03", "2024-011", "2025-01"])
def test_nearby_date_is_a_different_cell(key):
    pred = chart()
    pred.series[0].points[0].x = key
    metric = aggregate([score_sample(pred, chart())])
    assert metric["cell_f1"] == 0.5
    assert metric["chart_exact_rate"] == 0


def test_extra_points_and_series_reduce_precision():
    pred = chart()
    pred.series[0].points.append(pred.series[0].points[0].model_copy(update={"x": "Invented"}))
    pred.series.append(pred.series[0].model_copy(deep=True, update={"name": "Extra"}))
    metric = aggregate([score_sample(pred, chart())])
    assert metric["cell_recall"] == 1
    assert metric["cell_precision"] == pytest.approx(2 / 6)
    assert metric["cell_f1"] == 0.5
    assert metric["table_within_tolerance_rate"] == 0
    assert metric["chart_exact_rate"] == 0


@pytest.mark.parametrize("unit", [None, "EUR millions", "USD", "USD Millions"])
def test_wrong_units_cannot_be_called_correct_cells(unit):
    pred = chart()
    pred.y_axis.unit = unit
    metric = aggregate([score_sample(pred, chart())])
    assert metric["numeric_recall"] == 1  # explicitly diagnostic
    assert metric["cell_f1"] == 0
    assert metric["chart_exact_rate"] == 0


def test_missing_series_identity_is_not_guessed():
    pred = chart()
    pred.series[0].name = None
    assert score_sample(pred, chart())["n_correct_points"] == 0


def test_duplicate_categories_are_ambiguous_and_not_exact():
    pred = chart()
    pred.series[0].points.append(pred.series[0].points[0].model_copy())
    sample = score_sample(pred, chart())
    assert sample["semantic_valid"] == 0
    assert sample["n_correct_points"] == 1
    assert sample["chart_exact"] == 0


def test_duplicate_series_names_do_not_earn_credit():
    pred = chart()
    pred.series.append(pred.series[0].model_copy(deep=True))
    sample = score_sample(pred, chart())
    assert sample["semantic_valid"] == 0
    assert sample["n_correct_points"] == 0


def test_exact_chart_means_exact_values_and_metadata():
    gt = chart()
    pred = chart()
    pred.series[0].points[0].y = 10.1
    sample = score_sample(pred, gt)
    assert sample["table_within_tolerance"] == 1
    assert sample["chart_exact"] == 0
    pred = chart()
    pred.title = "Incorrect"
    assert score_sample(pred, gt)["chart_exact"] == 0
    pred = chart()
    pred.x_axis.label = "Incorrect"
    assert score_sample(pred, gt)["table_within_tolerance"] == 0


def test_zero_does_not_borrow_another_values_magnitude():
    gt = chart()
    gt.series[0].points[0].y = 0
    pred = gt.model_copy(deep=True)
    pred.series[0].points[0].y = 0.5
    assert score_sample(pred, gt)["n_correct_points"] == 1


def test_numeric_normalization_does_not_round_distinct_large_keys():
    assert _norm("123456789012345678901234567890") != _norm("123456789012345678901234567891")
    assert _norm("1200.0") == _norm("1,200") == _norm(1200)
    assert _norm("001") != _norm("1")
    assert _norm("1e999999999") != _norm("2e999999999")


def test_failures_stay_in_primary_denominator():
    result = score_rows([row(), row("b", error="429"), row("c", raw="not JSON")], 0.05)
    assert result["metric_version"] == METRIC_VERSION
    assert result["metrics"]["n"] == 3
    assert result["metrics"]["cell_recall"] == pytest.approx(1 / 3)
    assert result["metrics"]["cell_f1"] == 0.5
    assert result["conditional_model_metrics"]["n"] == 2
    assert result["n_infra_error"] == result["n_model_invalid"] == 1
    assert len(result["outcomes"]) == 3


def test_repair_and_schema_are_not_semantic_validity():
    repaired = "```json\n" + chart().model_dump_json() + "\n```"
    result = score_rows(
        [row(raw=repaired), row("b", raw='{"chart_type":"banana","series":[]}')], 0.05
    )
    assert result["raw_validity"]["raw_json_valid"] == 0.5
    assert result["raw_validity"]["raw_schema_valid"] == 0.5
    assert result["raw_validity"]["raw_semantic_valid"] == 0
    assert result["n_repaired"] == 1
    assert result["metrics"]["cell_f1"] == 0


def test_unsafe_repair_cannot_create_primary_quality_credit():
    r = row(raw='{"chart_type":"bar","series":[{"points":[{"x":"A","y":1e')
    r["gt"] = '{"chart_type":"bar","series":[{"points":[{"x":"A","y":1}]}]}'
    result = score_rows([r], 0.05)
    assert result["n_repaired"] == 0
    assert result["metrics"]["cell_f1"] == 0


def test_invalid_truth_duplicate_ids_and_missing_coverage_fail_closed():
    with pytest.raises(ValueError, match="duplicate"):
        score_rows([row(), row()], 0.05)
    with pytest.raises(ValueError, match="coverage"):
        score_rows([row()], 0.05, only_ids={"a", "b"})
    invalid = row()
    invalid["gt"] = '{"chart_type":"banana","series":[]}'
    with pytest.raises(ValueError, match="ground truth"):
        score_rows([invalid], 0.05)


def test_errors_precede_stale_success_payload():
    bad = row(error="timeout")
    bad["status"] = "ok"
    result = score_rows([bad], 0.05)
    assert result["metrics"]["cell_f1"] == 0
    assert result["n_infra_error"] == 1


def test_paired_bootstrap_includes_failures_and_checks_ground_truth():
    result = compare([row(), row("b")], [row(), row("b", error="timeout")], ["a", "b"], iters=200)
    assert result["metric"] == "cell_f1"
    assert result["cell_a"] == 1 and result["cell_b"] == pytest.approx(2 / 3)
    assert result["invalid_b"] == 0.5
    wrong = row()
    gt = chart()
    gt.series[0].points[0].y = 999
    wrong["gt"] = gt.model_dump_json()
    with pytest.raises(ValueError, match="ground truth mismatch"):
        compare([row()], [wrong], ["a"], iters=10)
    with pytest.raises(ValueError, match="coverage"):
        compare([row()], [row()], ["a", "missing"], iters=10)


def write_predictions(root, name, rows):
    folder = root / name
    folder.mkdir()
    (folder / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return folder


def test_comparison_does_not_select_success_intersection(tmp_path):
    write_predictions(tmp_path, "first", [row(), row("b")])
    write_predictions(tmp_path, "second", [row(), row("b", error="timeout")])
    text = build([str(tmp_path)], "")
    assert "N=2" in text
    assert "66.67%" in text
    assert "100.00%" in text


def test_comparison_missing_coverage_does_not_overwrite_report(tmp_path):
    write_predictions(tmp_path, "first", [row(), row("b")])
    write_predictions(tmp_path, "second", [row()])
    output = tmp_path / "report.md"
    output.write_text("preserve this evidence")
    with pytest.raises(ValueError, match="coverage"):
        build([str(tmp_path)], str(output))
    assert output.read_text() == "preserve this evidence"


def test_missing_scoreboard_artifacts_fail_closed(tmp_path):
    from analysis.scoreboard import build as scoreboard

    with pytest.raises(ValueError, match="missing evidence"):
        scoreboard(tmp_path, tmp_path)


def test_runner_preserves_failure_on_resume_and_never_retries_it(tmp_path, monkeypatch):
    from unrender.eval import providers
    from unrender.eval.run_baselines import run

    calls = []

    def failed(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("429 rate limit")

    monkeypatch.setitem(providers.PROVIDERS, "perfect", failed)
    data = tmp_path / "data.jsonl"
    data.write_text(
        json.dumps(
            {
                "images": ["data/a.png"],
                "messages": [
                    {"role": "user", "content": "Read the chart"},
                    {"role": "assistant", "content": chart().model_dump_json()},
                ],
                "meta": {"labels_shown": True},
            }
        )
        + "\n"
    )
    output = tmp_path / "run"
    path = run("perfect", "mock", str(data), str(output), 0, 0)
    before = path.read_bytes()
    run("perfect", "mock", str(data), str(output), 0, 0)
    assert calls == [1]
    assert path.read_bytes() == before
    assert json.loads(before)["status"] == "infra_error"


def test_distinct_letter_case_categories_are_not_collapsed():
    gt = chart()
    gt.series[0].points[0].x = "Product A"
    gt.series[0].points[1].x = "Product a"
    assert aggregate([score_sample(gt, gt)])["cell_f1"] == 1
    pred = gt.model_copy(deep=True)
    pred.series[0].points.reverse()
    assert aggregate([score_sample(pred, gt)])["cell_f1"] == 1
    pred.series[0].points[0].y, pred.series[0].points[1].y = 10, 20
    assert aggregate([score_sample(pred, gt)])["cell_f1"] == 0


def test_scoreboard_comparison_direction_matches_named_ladder(tmp_path, monkeypatch):
    from analysis import scoreboard

    monkeypatch.setattr(scoreboard, "COMMON300", ["a", "b"])
    for label, directory in scoreboard.COMMON.items():
        rows = [row(), row("b")]
        if label == "base 4B (pinned)":
            rows = [row(raw="invalid"), row("b", raw="invalid")]
        write_predictions(tmp_path, directory, rows)
    for directory in scoreboard.FRONTIER.values():
        write_predictions(tmp_path, directory, [row()])
    for directory in scoreboard.REAL.values():
        write_predictions(tmp_path, directory, [row()])
    result = scoreboard.build(tmp_path, tmp_path)
    gate = result["fair_vs_base"]
    assert gate["cell_a"] == result["ladder"]["table-LoRA (fair)"]["metrics"]["cell_f1"]
    assert gate["cell_b"] == result["ladder"]["base 4B (pinned)"]["metrics"]["cell_f1"]
    assert gate["gap_pp"] == 100
    assert result["numeric_vs_fair"]["gap_pp"] == 0
    for frontier in result["frontier"].values():
        assert frontier["missing_ids"] == ["b"]
        assert "paired_fair_minus_frontier" not in frontier
    assert result["real_v0_review"]["status"] == "withheld_pending_visual_metadata_audit"


def test_runner_rejects_changed_truth_with_same_ids(tmp_path):
    from unrender.eval.run_baselines import run

    data = tmp_path / "data.jsonl"
    source = {
        "images": ["data/a.png"],
        "messages": [
            {"role": "user", "content": "Read the chart"},
            {"role": "assistant", "content": chart().model_dump_json()},
        ],
    }
    data.write_text(json.dumps(source) + "\n")
    run("perfect", "mock", str(data), str(tmp_path / "run"), 0, 0)
    changed = chart()
    changed.series[0].points[0].y = 999
    source["messages"][1]["content"] = changed.model_dump_json()
    data.write_text(json.dumps(source) + "\n")
    with pytest.raises(SystemExit, match="dataset_sha256"):
        run("perfect", "mock", str(data), str(tmp_path / "run"), 0, 0)
