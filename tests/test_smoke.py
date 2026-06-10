"""Fast round-trip checks for the data engine + schema layer.

Run: pytest -q
"""

import random

from unrender.data_gen.chart_specs import random_spec
from unrender.data_gen.render import render_chart
from unrender.schema.chart_schema import MULTI_SERIES_TYPES, canonical_json
from unrender.schema.json_to_csv import chart_to_csv
from unrender.schema.validate import parse_chart_json, repair_json


def test_spec_renders_and_label_roundtrips():
    """Every generated spec must render and its label must survive serialize->parse."""
    for seed in range(40):
        spec = random_spec(random.Random(seed))
        img = render_chart(spec)
        assert img.size[0] > 0 and img.size[1] > 0

        gt = spec.to_chart_data()
        parsed, errors = parse_chart_json(canonical_json(gt))
        assert parsed is not None, f"seed {seed} failed to parse: {errors}"
        assert parsed.chart_type == gt.chart_type
        assert parsed.model_dump() == gt.model_dump()


def test_pie_values_are_positive_across_seeds():
    """Regression: a pie whose values all round to 0 has a zero total, which
    crashes matplotlib's ax.pie (NaN slice angles). random_spec must never emit
    a non-positive pie. (3000 specs, no rendering — fast.)"""
    for seed in range(3000):
        spec = random_spec(random.Random(seed))
        if spec.chart_type == "pie":
            vals = spec.values[0]
            assert vals and all(v > 0 for v in vals) and sum(vals) > 0, (seed, vals)


def test_csv_export_shape():
    """CSV header reflects single vs multi series; rows are non-empty."""
    for seed in range(40):
        spec = random_spec(random.Random(seed))
        gt = spec.to_chart_data()
        csv_text = chart_to_csv(gt)
        lines = [ln for ln in csv_text.splitlines() if ln.strip()]
        assert len(lines) >= 2  # header + at least one row
        header_cols = lines[0].count(",") + 1
        if gt.chart_type in MULTI_SERIES_TYPES:
            assert header_cols == len(gt.series) + 1


def test_repair_strips_fences_and_prose():
    raw = 'Here is the data:\n```json\n{"chart_type":"bar","series":[],}\n```\nDone.'
    parsed, _ = parse_chart_json(raw)
    assert parsed is not None
    assert parsed.chart_type == "bar"
    # raw also exercises trailing-comma + fence repair directly
    assert repair_json(raw).endswith("}")
