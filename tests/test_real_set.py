"""Verify the real-chart set builder produces rows the eval harness reads back
identically — and fails loudly on a malformed label (a bad GT must never slip
through as a plausible-but-wrong ground truth)."""

import hashlib
import json

import pytest

from unrender.eval.build_real_set import build, label_to_chartdata
from unrender.eval.dataset import annotation_sha256, load_eval_samples
from unrender.schema.chart_schema import ChartData, canonical_json


def _write_set(root, label):
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    (root / "images" / label["image"]).write_bytes(b"\x89PNG\r\n")  # presence only; not parsed
    source = b"year,value\n2019,3.7\n2020,8.1\n2021,5.3\n"
    (root / "source.csv").write_bytes(source)
    label["source_data_file"] = "source.csv"
    gt = canonical_json(label_to_chartdata(label, "fixture"))
    label["ground_truth_review"] = {
        "contract": "real-ground-truth-review-v1",
        "status": "verified",
        "reviewer": "test fixture",
        "reviewed_at": "2026-09-18T12:00:00Z",
        "image_sha256": hashlib.sha256((root / "images" / label["image"]).read_bytes()).hexdigest(),
        "annotation_sha256": annotation_sha256(gt, label),
        "source_data_sha256": hashlib.sha256(source).hexdigest(),
        "visible_metadata_checked": True,
        "source_values_checked": True,
        "scale_units_checked": True,
        "recoverability_checked": True,
    }
    (root / "labels" / "chart1.json").write_text(json.dumps(label))


def _label():
    return {
        "image": "chart1.png",
        "chart_type": "line",
        "title": "US Unemployment Rate",
        "x_axis": {"label": "Year", "unit": None},
        "y_axis": {"label": "Rate", "unit": "%"},
        "labels_shown": False,
        "source": "FRED UNRATE",
        "series": [{"name": "UNRATE", "points": [["2019", 3.7], ["2020", 8.1], ["2021", 5.3]]}],
    }


def test_build_roundtrips_to_eval_sample(tmp_path):
    root = tmp_path / "real_v0"
    _write_set(root, _label())

    summary = build(str(root))
    assert summary == {"n": 1, "label_free": 1, "labeled": 0, "by_type": {"line": 1}}
    root = root / "published"
    assert (root / "test.jsonl").exists()
    assert not (root / "test.modal.jsonl").exists()

    # The harness loader reads the row back exactly like a synthetic one.
    samples = load_eval_samples(str(root / "test.jsonl"))
    assert len(samples) == 1
    s = samples[0]
    assert s.id == "chart1"  # id = image stem (matches the synthetic convention)
    assert s.image == f"{root.as_posix()}/images/chart1.png"
    assert s.meta == {
        "labels_shown": False,
        "chart_type": "line",
        "augmented": False,
        "source": "FRED UNRATE",
        "ground_truth_review": s.meta["ground_truth_review"],
    }
    gt = ChartData.model_validate_json(s.gt_json)
    assert gt.chart_type == "line"
    assert [(p.x, p.y) for p in gt.series[0].points] == [
        ("2019", 3.7),
        ("2020", 8.1),
        ("2021", 5.3),
    ]


def test_bad_chart_type_raises():
    bad = _label() | {"chart_type": "scatter3d"}
    with pytest.raises(ValueError, match="chart_type"):
        label_to_chartdata(bad, "bad.json")


def test_malformed_point_raises():
    bad = _label()
    bad["series"][0]["points"] = [["2019", 3.7, 9]]  # not an [x, y] pair
    with pytest.raises(ValueError, match=r"\[x, y\]"):
        label_to_chartdata(bad, "bad.json")


def test_parse_fred_csv_skips_missing_and_keeps_year():
    from unrender.eval.fetch_real_set import parse_fred_csv

    text = "observation_date,UNRATE\n2019-01-01,3.7\n2020-01-01,.\n2021-01-01,5.35\n"
    assert parse_fred_csv(text) == [["2019", 3.7], ["2021", 5.35]]


def test_parse_owid_csv_filters_country_year_and_value_col():
    from unrender.eval.fetch_real_set import parse_owid_csv

    # value is column index 3 (after Year), NOT the last column (a region string on
    # some indicators); rows are filtered to the ISO code and the [lo, hi] window.
    text = (
        "Entity,Code,Year,GDP per capita,World region\n"
        "United States,USA,2001,37000,North America\n"  # kept
        "Afghanistan,AFG,2001,1200,Asia\n"  # dropped: not USA
        "United States,USA,1990,30000,North America\n"
    )  # dropped: 1990 < lo
    assert parse_owid_csv(text) == [["2001", 37000.0]]


@pytest.mark.parametrize(
    "damage",
    ["unreviewed", "image", "title", "labels_shown", "source", "source_bytes", "incomplete_check"],
)
def test_build_refuses_unreviewed_or_changed_inputs_before_writing(tmp_path, damage):
    root = tmp_path / "charts"
    _write_set(root, _label())
    label_path = root / "labels/chart1.json"
    label = json.loads(label_path.read_text())
    if damage == "unreviewed":
        del label["ground_truth_review"]
    elif damage == "image":
        (root / "images/chart1.png").write_bytes(b"changed image")
    elif damage == "source_bytes":
        (root / "source.csv").write_bytes(b"changed values")
    elif damage == "incomplete_check":
        label["ground_truth_review"]["scale_units_checked"] = False
    elif damage == "labels_shown":
        label["labels_shown"] = True
    else:
        label[damage] = "changed"
    label_path.write_text(json.dumps(label))
    with pytest.raises(ValueError, match="review"):
        build(str(root))
    assert not (root / "test.jsonl").exists()
    assert not (root / "test.modal.jsonl").exists()


def test_historical_real_v0_cannot_start_a_new_evaluation():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="unverified real-chart ground truth"):
        load_eval_samples(str(root / "data/real_v0/test.jsonl"))


def test_loader_rechecks_review_after_dataset_build(tmp_path):
    root = tmp_path / "charts"
    _write_set(root, _label())
    build(str(root))
    root = root / "published"
    (root / "images/chart1.png").write_bytes(b"different chart")
    with pytest.raises(ValueError, match="published artifact changed"):
        load_eval_samples(str(root / "test.jsonl"))


def test_fetcher_labels_are_explicitly_unreviewed():
    from unrender.eval.fetch_real_set import make_line_label

    label = make_line_label("id", "Title", "Y", "%", "series", [["a", 1]], "source")
    assert label["ground_truth_review"] == {"status": "needs_visual_review"}


def test_fetcher_retains_original_source_bytes_for_annotation_review(tmp_path, monkeypatch):
    from unrender.eval import fetch_real_set

    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir()
    labels.mkdir()
    csv = b"date,value\r\n2019-01-01,3.70\r\n2020-01-01,8.10\r\n2021-01-01,5.30\r\n"
    monkeypatch.setattr(
        fetch_real_set, "_download", lambda url: b"\x89PNG\r\n\x1a\n" if url == "image" else csv
    )
    assert (
        fetch_real_set._fetch_one(
            "sample",
            "image",
            "csv",
            fetch_real_set.parse_fred_csv,
            "Draft title",
            "Draft axis",
            "%",
            "Draft series",
            "Source citation",
            images,
            labels,
        )
        == "sample"
    )
    label = json.loads((labels / "sample.json").read_text())
    assert (tmp_path / label["source_data_file"]).read_bytes() == csv
    with pytest.raises(ValueError, match="unverified real-chart ground truth"):
        build(str(tmp_path))


def test_collection_never_overwrites_and_accounts_for_all_failures(tmp_path, monkeypatch):
    from unrender.eval import fetch_real_set

    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "test.jsonl").write_bytes(b"previous published evidence")
    calls = []

    def fail(url):
        calls.append(url)
        raise OSError("injected network failure")

    monkeypatch.setattr(fetch_real_set, "_download", fail)
    with pytest.raises(FileExistsError):
        fetch_real_set.fetch(str(existing), sources="owid")
    assert not calls
    assert (existing / "test.jsonl").read_bytes() == b"previous published evidence"
    draft = tmp_path / "failed"
    assert fetch_real_set.fetch(str(draft), sources="owid") == 0
    receipt = json.loads((draft / "collection.json").read_bytes())
    assert len(receipt["attempts"]) == len(fetch_real_set.OWID)
    assert all(a["state"] == "failed" for a in receipt["attempts"])
    assert receipt["status"] == "incomplete"
    assert not (draft / "test.jsonl").exists()


def test_interrupted_collection_retains_schedule(tmp_path, monkeypatch):
    from unrender.eval import fetch_real_set

    def interrupt(url):
        raise KeyboardInterrupt()

    monkeypatch.setattr(fetch_real_set, "_download", interrupt)
    draft = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        fetch_real_set.fetch(str(draft), sources="owid")
    receipt = json.loads((draft / "collection.json").read_bytes())
    assert receipt["attempts"][0]["state"] == "in_flight"
    assert all(a["state"] == "pending" for a in receipt["attempts"][1:])
    assert not (draft / "test.jsonl").exists()


def test_published_snapshot_is_independent_and_cannot_be_replaced(tmp_path):
    root = tmp_path / "draft"
    _write_set(root, _label())
    build(str(root))
    published = root / "published"
    previous = (published / "test.jsonl").read_bytes()
    (root / "source.csv").write_bytes(b"changed draft")
    assert len(load_eval_samples(str(published / "test.jsonl"))) == 1
    with pytest.raises(FileExistsError):
        build(str(root))
    assert (published / "test.jsonl").read_bytes() == previous
    (published / "source.csv").write_bytes(b"changed publication")
    with pytest.raises(ValueError, match="published artifact changed"):
        load_eval_samples(str(published / "test.jsonl"))


def test_partial_collection_cannot_publish_only_successes(tmp_path):
    root = tmp_path / "draft"
    _write_set(root, _label())
    (root / "collection.json").write_text(
        json.dumps(
            {
                "status": "incomplete",
                "attempts": [
                    {"id": "chart1", "state": "collected"},
                    {"id": "chart2", "state": "failed"},
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="collection incomplete"):
        build(str(root))
    assert not (root / "published").exists()
