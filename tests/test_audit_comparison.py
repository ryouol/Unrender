import copy

import pytest

from tests.test_metric_contract import row, write_predictions
from unrender.eval.paired_bootstrap import compare, verdict
from unrender.eval.report import build


@pytest.mark.parametrize("damage", ["image", "missing", "source", "review"])
def test_comparisons_reject_different_sources(tmp_path, damage):
    a = row() | {"image_sha256": "a" * 64}
    b = copy.deepcopy(a)
    if damage == "image":
        b["image_sha256"] = "b" * 64
    elif damage == "missing":
        del b["image_sha256"]
    elif damage == "source":
        b["meta"]["source_group"] = "different-table"
    else:
        b["meta"]["source_review"] = {"status": "different"}
    with pytest.raises(ValueError, match="identity mismatch"):
        compare([a], [b], ["a"], iters=10)
    write_predictions(tmp_path, "a", [a])
    write_predictions(tmp_path, "b", [b])
    with pytest.raises(ValueError, match="identity mismatch"):
        build([str(tmp_path)], "")


def test_one_chart_and_historical_scores_cannot_promote():
    result = compare([row()], [row(raw="bad")], ["a"], iters=10)
    assert result["gap_pp"] == 100
    assert not result["source_identity_complete"]
    assert result["purpose"] == "descriptive_only"
    assert verdict(result)[0] is False
    # Editing the result flag cannot turn this descriptive interface into a gate.
    result["promotion_eligible"] = True
    assert verdict(result)[0] is False


def test_shared_source_is_bootstrapped_as_a_group():
    a = [row("a"), row("b")]
    for r in a:
        r["meta"]["source_group"] = "same-table"
    b = copy.deepcopy(a)
    b[1]["raw"] = "bad"
    result = compare(a, b, ["a", "b"], iters=30)
    assert result["n_groups"] == 1
    assert result["resampling_unit"] == "source_group"
    assert result["ci95_pp"][0] == result["ci95_pp"][1]
    assert not verdict(result)[0]


def test_conflicting_internal_image_receipt_is_rejected():
    a = row() | {"image_sha256": "a" * 64}
    a["meta"]["generation"] = {"image_sha256": "b" * 64}
    with pytest.raises(ValueError, match="conflicting"):
        compare([a], [a], ["a"], iters=10)
