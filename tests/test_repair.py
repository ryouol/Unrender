"""Formatting recovery must preserve complete chart data or reject the output."""

import json

import pytest

from unrender.eval.metrics import _norm
from unrender.schema.validate import PARSER_VERSION, parse_chart_json, repair_json


def chart(points=None, **changes):
    return {
        "chart_type": "bar",
        "series": [{"name": "Revenue", "points": points or [{"x": "A", "y": 5}]}],
        **changes,
    }


def test_complete_chart_has_no_repairs():
    data = chart(title="Revenue", y_axis={"label": "Revenue", "unit": "USD millions"})
    parsed, errors = parse_chart_json(json.dumps(data))
    assert parsed is not None
    assert not errors
    assert parsed.y_axis.unit == "USD millions"
    assert PARSER_VERSION == "chart-json-v2"


@pytest.mark.parametrize(
    "value",
    [None, True, False, "1,200", "1.2B", "12%", "$3,400", "−42", "12", "N/A", {"value": 12}, [12]],
)
def test_invalid_or_unit_bearing_numbers_never_drop_or_convert_a_point(value):
    parsed, errors = parse_chart_json(
        json.dumps(chart([{"x": "A", "y": 5}, {"x": "B", "y": value}]))
    )
    assert parsed is None
    assert errors == ["invalid_chart_values"]


@pytest.mark.parametrize(
    "tail", ["1e", "1e+", "1e-", "12.", "-", "12", "null", "fal", '"unfinished', "", '{"x":"B",']
)
def test_unfinished_json_never_guesses_or_publishes_a_partial_chart(tail):
    raw = '{"chart_type":"bar","series":[{"points":[{"x":"A","y":5},{"x":"B","y":' + tail
    parsed, errors = parse_chart_json(raw)
    assert parsed is None
    assert errors == ["invalid_json"]


def test_every_proper_prefix_of_a_table_is_rejected():
    raw = json.dumps(chart([{"x": "A", "y": 5}, {"x": 'B } ] \\"', "y": -1.2e8}]))
    for end in range(len(raw)):
        parsed, errors = parse_chart_json(raw[:end])
        assert parsed is None, (end, raw[:end])
        assert errors


@pytest.mark.parametrize(
    "label", ["None", "True", "False", ",}", ",]", 'x \\" ,} None', "braces { [ ] }"]
)
def test_syntax_repairs_leave_quoted_labels_untouched(label):
    raw = json.dumps(chart([{"x": label, "y": 12}]))
    raw = "Here is the table:\n```json\n" + raw[:-1] + ",}\n```\nDone."
    parsed, errors = parse_chart_json(raw)
    assert parsed is not None
    assert parsed.series[0].points[0].x == label
    assert parsed.series[0].points[0].y == 12
    assert errors == ["syntax_repaired"]


@pytest.mark.parametrize(
    "raw",
    [
        '{"chart_type":"bar","series":[{"points":[{"x":"A","y":1,"y":2}]}]}',
        '{"chart_type":"bar","chart_type":"pie","series":[{"points":[{"x":"A","y":1}]}]}',
    ],
)
def test_duplicate_keys_are_not_silently_overwritten(raw):
    assert parse_chart_json(raw) == (None, ["duplicate_json_key"])
    assert parse_chart_json("```json\n" + raw + "\n```") == (None, ["duplicate_json_key"])


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_nonfinite_numbers_are_rejected(value):
    raw = '{"chart_type":"bar","series":[{"points":[{"x":"A","y":' + value + "}]}]}"
    parsed, errors = parse_chart_json(raw)
    assert parsed is None
    assert errors


@pytest.mark.parametrize(
    "raw",
    [
        '{"chart_type":"banana","series":[]}',
        '{"chart_type":"bar","series":[]}',
        '{"chart_type":"bar","series":[{"points":[]}]}',
        '{"chart_type":"bar","series":[{"data":[{"x":"A","y":5}]}]}',
        '{"chart_type":"bar","series":[{"points":[{"x":"A","y":5,"unit":"EUR"}]}]}',
        '{"chart_type":"bar","series":[{"points":[{"x":"A","y":5},null]}]}',
    ],
)
def test_noncanonical_structures_are_not_coerced(raw):
    parsed, errors = parse_chart_json(raw)
    assert parsed is None
    assert errors == ["invalid_chart_structure"]


def test_wrappers_and_python_repr_are_not_alternate_output_schemas():
    assert parse_chart_json(json.dumps({"chart": chart()}))[0] is None
    assert parse_chart_json(str(chart()))[0] is None


@pytest.mark.parametrize(
    "suffix", [" {}", " [1]", ' {"unfinished":', ', "series":', " 123", "}", " true", " null"]
)
def test_complete_prefix_cannot_hide_extra_or_truncated_objects(suffix):
    raw = json.dumps(chart()) + suffix
    assert parse_chart_json(raw)[0] is None


def test_string_aware_trailing_comma_removal():
    raw = '{"chart_type":"bar","title":",}","series":[{"points":[{"x":",]","y":5,},],},],}'
    repaired = repair_json(raw)
    assert json.loads(repaired) == chart([{"x": ",]", "y": 5}], title=",}") | {
        "series": [{"points": [{"x": ",]", "y": 5}]}]
    }
    parsed, errors = parse_chart_json(raw)
    assert parsed.series[0].points[0].x == ",]"
    assert errors == ["syntax_repaired"]


def test_diagnostics_do_not_echo_private_content():
    raw = json.dumps(chart([{"x": "PRIVATE_LABEL", "y": "PRIVATE_VALUE"}]))
    assert "PRIVATE" not in json.dumps(parse_chart_json(raw)[1])


def test_norm_thousands_and_months():
    assert _norm("1,200") == _norm("1200")
    assert _norm("1,234,567.5") == "1234567.5"
    assert _norm("January") == _norm("Jan")
    assert _norm("September 2020") == _norm("Sep 2020")
    assert _norm("Sept") == "sep"
    assert _norm(2020.0) == "2020"
    assert _norm(" Product  A ") == "Product A"
    assert _norm("Mayfield") == "Mayfield"


@pytest.mark.parametrize("prefix", ["{} ", "[] ", "true ", "null ", "123 "])
def test_json_prefix_is_not_mistaken_for_a_prose_envelope(prefix):
    assert parse_chart_json(prefix + json.dumps(chart()))[0] is None
