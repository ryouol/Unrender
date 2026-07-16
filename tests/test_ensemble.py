"""Self-consistency merge tests: median voting, majority cells, surface forms.

Run: pytest -q tests/test_ensemble.py
"""

import json

from unrender.eval.ensemble import merge_parses, merge_runs
from unrender.schema.validate import parse_chart_json


def _raw(points, ctype="bar", name=None):
    return json.dumps({"chart_type": ctype, "title": "T",
                       "x_axis": {"label": None, "unit": None},
                       "y_axis": {"label": None, "unit": None},
                       "series": [{"name": name, "points": points}]})


def _parse(raw):
    p, _ = parse_chart_json(raw)
    assert p is not None
    return p


def test_median_vote_kills_outlier():
    parses = [_parse(_raw([{"x": "A", "y": y}])) for y in (100, 102, 900)]  # one wild sample
    m = merge_parses(parses)
    assert m.series[0].points[0].y == 102.0  # median, not mean (333.7)


def test_minority_cell_dropped_majority_kept():
    parses = [_parse(_raw([{"x": "A", "y": 1}, {"x": "B", "y": 2}])),
              _parse(_raw([{"x": "A", "y": 1}])),
              _parse(_raw([{"x": "A", "y": 1}]))]
    m = merge_parses(parses)
    xs = {p.x for p in m.series[0].points}
    assert xs == {"A"}  # "B" appeared 1/3 < majority -> dropped


def test_chart_type_majority_and_x_surface_form():
    parses = [_parse(_raw([{"x": "Jan", "y": 5}], ctype="bar")),
              _parse(_raw([{"x": "January", "y": 5}], ctype="bar")),
              _parse(_raw([{"x": "Jan", "y": 6}], ctype="line"))]
    m = merge_parses(parses)
    assert m.chart_type == "bar"
    assert m.series[0].points[0].x == "Jan"     # majority surface form
    assert m.series[0].points[0].y == 5.0       # median of 5,5,6


def test_merge_runs_end_to_end(tmp_path):
    for j, y in enumerate((10, 11, 30)):
        d = tmp_path / f"run{j}"
        d.mkdir()
        (d / "predictions.jsonl").write_text(json.dumps(
            {"id": "0001", "image": "x.png", "gt": "{}", "meta": {},
             "raw": _raw([{"x": "A", "y": y}]), "status": "ok", "error": None}) + "\n")
    out = merge_runs([str(tmp_path / f"run{j}") for j in range(3)], str(tmp_path / "merged"))
    row = json.loads(out.read_text())
    merged, _ = parse_chart_json(row["raw"])
    assert merged.series[0].points[0].y == 11.0  # median across runs
