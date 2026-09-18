"""The public evidence must be sufficient, intact and independently rescorable."""

import json
import shutil

import pytest

from analysis.reproduce_common300 import (
    BUNDLE,
    ROOT,
    audit_evidence,
    load_evidence,
    numerical_table_signature,
    reproduce,
)
from unrender.schema.chart_schema import ChartData, Point, Series


def test_recovered_raw_outputs_reproduce_the_recorded_strict_scores():
    expected = json.loads((ROOT / "release/evaluation-v2/summary.json").read_text())
    report = reproduce()
    names = {
        "base": "base 4B (pinned)",
        "fair": "table-LoRA (fair)",
        "numeric": "table-LoRA + numeric-loss",
    }
    for arm, name in names.items():
        actual = report["ladder"][arm]
        saved = expected["ladder"][name]
        for metric in ("cell_precision", "cell_recall", "cell_f1", "chart_exact_rate"):
            assert actual["metrics"][metric] == pytest.approx(saved["metrics"][metric])
        assert actual["raw_validity"] == saved["raw_validity"]
    assert report["fair_vs_base"]["ci95_pp"][0] > 0
    assert report["numeric_vs_fair"]["ci95_pp"][1] < 0
    assert report["audit"]["training_overlap"]["train_v0"]["id_overlap"] == 158
    assert report["audit"]["training_overlap"]["train_v1"]["id_overlap"] == 0


@pytest.mark.parametrize("damage", ["missing", "changed", "changed_metadata"])
def test_missing_or_modified_source_artifact_fails_closed(tmp_path, damage):
    bundle = tmp_path / "evidence"
    shutil.copytree(BUNDLE, bundle)
    path = bundle / ("fair.meta.json" if damage == "changed_metadata" else "fair.jsonl.gz")
    if damage == "missing":
        path.unlink()
        error = FileNotFoundError
    else:
        path.write_bytes(path.read_bytes() + b" ")
        error = ValueError
    with pytest.raises(error):
        load_evidence(bundle)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_truth",
        "missing_prediction",
        "extra_prediction",
        "duplicate_prediction",
        "wrong_truth",
        "wrong_metadata",
    ],
)
def test_bad_coverage_or_truth_cannot_produce_a_comparison(damage):
    evidence = load_evidence()
    rows = evidence["rows"]["fair"]
    if damage == "missing_truth":
        rid = rows[0]["id"]
        evidence["rows"]["test_v1"] = [
            row
            for row in evidence["rows"]["test_v1"]
            if not row["images"][0].endswith(f"/{rid}.png")
        ]
    elif damage == "missing_prediction":
        rows.pop()
    elif damage == "extra_prediction":
        rows.append({**rows[0], "id": "not-common300"})
    elif damage == "duplicate_prediction":
        rows.append(rows[0])
    elif damage == "wrong_metadata":
        rows[0]["meta"]["labels_shown"] = not rows[0]["meta"]["labels_shown"]
    else:
        truth = json.loads(rows[0]["gt"])
        truth["series"][0]["points"][0]["y"] += 1
        rows[0]["gt"] = json.dumps(truth)
    with pytest.raises(ValueError):
        audit_evidence(evidence)


def test_overlap_check_detects_a_renamed_reordered_rerender():
    base = ChartData(
        chart_type="grouped_bar",
        series=[
            Series(name="A", points=[Point(x="a", y=1.0), Point(x="b", y=2.0)]),
            Series(name="B", points=[Point(x="a", y=3.0)]),
        ],
    )
    changed = base.model_copy(deep=True)
    changed.chart_type = "multi_line"
    changed.title = "New title"
    changed.series.reverse()
    for series in changed.series:
        series.name = "Renamed " + series.name
        series.points.reverse()
    assert numerical_table_signature(base) == numerical_table_signature(changed)
    changed.series[0].points[0].y += 0.0000001
    assert numerical_table_signature(base) != numerical_table_signature(changed)
