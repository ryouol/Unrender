"""Verify the real-chart set builder produces rows the eval harness reads back
identically — and fails loudly on a malformed label (a bad GT must never slip
through as a plausible-but-wrong ground truth)."""

import json

import pytest

from unrender.eval.build_real_set import build, label_to_chartdata
from unrender.eval.dataset import load_eval_samples
from unrender.schema.chart_schema import ChartData


def _write_set(root, label):
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    (root / "images" / label["image"]).write_bytes(b"\x89PNG\r\n")  # presence only; not parsed
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
    assert (root / "test.jsonl").exists() and (root / "test.modal.jsonl").exists()

    # The harness loader reads the row back exactly like a synthetic one.
    samples = load_eval_samples(str(root / "test.jsonl"))
    assert len(samples) == 1
    s = samples[0]
    assert s.id == "chart1"  # id = image stem (matches the synthetic convention)
    assert s.image == f"{root.as_posix()}/images/chart1.png"
    assert s.meta == {"labels_shown": False, "chart_type": "line", "augmented": False,
                      "source": "FRED UNRATE"}
    gt = ChartData.model_validate_json(s.gt_json)
    assert gt.chart_type == "line"
    assert [(p.x, p.y) for p in gt.series[0].points] == [("2019", 3.7), ("2020", 8.1), ("2021", 5.3)]

    # The Modal variant carries the same row with a /vol-absolute image path.
    modal = load_eval_samples(str(root / "test.modal.jsonl"))[0]
    assert modal.image == f"/vol/{root.as_posix()}/images/chart1.png"
    assert modal.gt_json == s.gt_json


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
    text = ("Entity,Code,Year,GDP per capita,World region\n"
            "United States,USA,2001,37000,North America\n"   # kept
            "Afghanistan,AFG,2001,1200,Asia\n"               # dropped: not USA
            "United States,USA,1990,30000,North America\n")  # dropped: 1990 < lo
    assert parse_owid_csv(text) == [["2001", 37000.0]]
