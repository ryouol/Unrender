"""Unreviewed external annotations must not become model-comparison claims."""

import hashlib
import json
from pathlib import Path

import pytest

from unrender.eval.paired_bootstrap import compare
from unrender.eval.report import build
from unrender.eval.score import score_rows

ROOT = Path(__file__).resolve().parents[1]


def historical_rows():
    rows = []
    for line in (ROOT / "data/real_v0/test.jsonl").read_text().splitlines():
        source = json.loads(line)
        gt = source["messages"][1]["content"]
        rows.append(
            {
                "id": Path(source["images"][0]).stem,
                "gt": gt,
                "raw": gt,
                "status": "ok",
                "meta": source["meta"],
            }
        )
    return rows


def test_perfect_predictions_against_bad_truth_are_diagnostic_only(tmp_path):
    rows = historical_rows()
    diagnostic = score_rows(rows, 0.05)
    assert diagnostic["metrics"]["cell_f1"] == 1
    assert diagnostic["ground_truth_review"]["unverified_ids"] == [row["id"] for row in rows]
    assert not diagnostic["ground_truth_review"]["review_gate_passed"]
    with pytest.raises(ValueError, match="comparison withheld"):
        compare(rows, rows, [row["id"] for row in rows])
    (tmp_path / "predictions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    out = tmp_path / "report.md"
    out.write_text("previous report")
    with pytest.raises(ValueError, match="comparison withheld"):
        build([str(tmp_path)], str(out))
    assert out.read_text() == "previous report"


def test_visual_audit_is_bound_to_all_eight_recovered_images_and_original_targets():
    bundle = ROOT / "release/real-v0-audit"
    audit = json.loads((bundle / "audit.json").read_text())
    rows = {row["id"]: row for row in historical_rows()}
    assert {chart["id"] for chart in audit["charts"]} == set(rows)
    for chart in audit["charts"]:
        raw = (bundle / chart["image"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == chart["image_sha256"]
        gt_raw = rows[chart["id"]]["gt"]
        assert hashlib.sha256(gt_raw.encode()).hexdigest() == chart["original_target_sha256"]
        gt = json.loads(gt_raw)
        assert gt["title"] != chart["observed"]["title"]
        assert [series["name"] for series in gt["series"]] != chart["observed"]["series_names"]
    assert audit["status"] == "rejected_visual_metadata"
    assert all(
        arm["rows_using_defective_truth"] == 8 for arm in audit["affected_saved_predictions"]
    )
