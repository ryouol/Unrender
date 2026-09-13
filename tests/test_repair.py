"""P0 free-win tests: repair/coercion in validate.py + the scorer's x-ruler.

Every case here was a measured failure shape from the 2026-07-01 sweep: values
like "1,200"/"1.2B"/"12%" or one null y zeroed an ENTIRE chart; max-token
truncation was unrecoverable; "January" vs "Jan" killed numerically-correct
cells. All repairs are pure string surgery, identical for every provider,
never GT-aware. Run: pytest -q tests/test_repair.py
"""

from unrender.eval.metrics import _norm
from unrender.schema.validate import _balance_json, _coerce_num, parse_chart_json


def _chart(points_json: str) -> str:
    return ('{"chart_type": "bar", "title": null, '
            '"x_axis": {"label": null, "unit": null}, "y_axis": {"label": null, "unit": null}, '
            '"series": [{"name": null, "points": [' + points_json + "]}]}")


# --- numeric-string coercion -------------------------------------------------

def test_coerce_num_formats():
    assert _coerce_num("1,200") == 1200.0
    assert _coerce_num("1,234,567.89") == 1234567.89
    assert _coerce_num("1.2B") == 1.2e9
    assert _coerce_num("3.4k") == 3400.0
    assert _coerce_num("2M") == 2e6
    assert _coerce_num("1.5T") == 1.5e12
    assert _coerce_num("12%") == 12.0
    assert _coerce_num("$3,400") == 3400.0
    assert _coerce_num("€2.5M") == 2.5e6
    assert _coerce_num("−42") == -42.0            # unicode minus
    assert _coerce_num(7) == 7 and _coerce_num(7.5) == 7.5
    assert _coerce_num(None) is None
    assert _coerce_num("N/A") is None
    assert _coerce_num("about 12") is None        # prose stays unusable
    assert _coerce_num(True) is None              # bool y is not a number


def test_suffix_value_no_longer_kills_chart():
    pred, errs = parse_chart_json(_chart('{"x": "A", "y": "1.2B"}, {"x": "B", "y": "3,400"}'))
    assert pred is not None
    assert [p.y for p in pred.series[0].points] == [1.2e9, 3400.0]


def test_null_y_drops_point_not_chart():
    pred, errs = parse_chart_json(_chart('{"x": "A", "y": 5}, {"x": "B", "y": null}'))
    assert pred is not None                       # chart survives
    assert len(pred.series[0].points) == 1        # bad point dropped (a miss, not a wipeout)
    assert any("dropped 1 point" in e for e in errs)


# --- truncated / malformed JSON ----------------------------------------------

def test_truncated_after_first_point_recovers():
    full = _chart('{"x": "A", "y": 5}, {"x": "B", "y": 7}')
    raw = full[: full.index('{"x": "B"')]          # cutoff right before point B
    pred, _ = parse_chart_json(raw)
    assert pred is not None and pred.chart_type == "bar"
    assert [p.y for p in pred.series[0].points] == [5.0]


def test_truncated_mid_point_drops_half_point():
    full = _chart('{"x": "A", "y": 5}, {"x": "B", "y": 7}')
    raw = full[: full.index('"y": 7')]             # point B left as {"x": "B", }
    pred, errs = parse_chart_json(raw)
    assert pred is not None
    assert [p.y for p in pred.series[0].points] == [5.0]
    assert any("dropped" in e for e in errs)


def test_balance_json_shapes():
    assert _balance_json('{"a": [1, 2') == '{"a": [1, 2]}'
    assert _balance_json('{"a": {"b": "unterminat') == '{"a": {"b": null}}'
    assert _balance_json('{"a": 1,') == '{"a": 1}'
    assert _balance_json('{"a":') == '{"a": null}'
    assert _balance_json('{"a": fal') == '{"a": null}'
    assert _balance_json('{"a": 12.') == '{"a": 12}'
    assert _balance_json('{"a": 1}') == '{"a": 1}'   # balanced -> no-op


def test_python_literals_and_single_quotes():
    raw = "{'chart_type': 'bar', 'title': None, 'x_axis': {'label': None, 'unit': None}, " \
          "'y_axis': {'label': None, 'unit': None}, 'series': [{'name': None, 'points': " \
          "[{'x': 'A', 'y': 5}]}]}"
    pred, _ = parse_chart_json(raw)
    assert pred is not None and pred.series[0].points[0].y == 5.0


def test_wrapper_unwrapped():
    pred, _ = parse_chart_json('{"chart": ' + _chart('{"x": "A", "y": 5}') + "}")
    assert pred is not None and pred.chart_type == "bar"


def test_existing_repairs_still_work():
    raw = (
        'Here you go:\n```json\n{"chart_type":"bar","title":null,'
        '"x_axis":{"label":null,"unit":null},"y_axis":{"label":null,"unit":null},'
        '"series":[{"name":null,"points":[{"x":"A","y":1},]}]}\n```'
    )
    pred, _ = parse_chart_json(raw)
    assert pred is not None


# --- scorer x-ruler (symmetric) ----------------------------------------------

def test_norm_thousands_and_months():
    assert _norm("1,200") == _norm("1200")
    assert _norm("1,234,567.5") == "1234567.5"
    assert _norm("January") == _norm("Jan")
    assert _norm("September 2020") == _norm("Sep 2020")
    assert _norm("Sept") == "sep"
    # unchanged behaviors
    assert _norm(2020.0) == "2020"
    assert _norm(" Product  A ") == "product a"
    assert _norm("Mayfield") == "mayfield"        # month words only replaced whole-word
