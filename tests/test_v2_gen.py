"""synthetic_v2 generator tests + frozen-recipe regression.

The frozen fingerprints were captured from the code as of commit 49f2366 (before
any v2 change): if random_spec's easy or hard path ever produces different specs
for the same seed, regenerating eval-v0/eval-v1 would silently stop matching the
committed ground truth. This test makes that failure loud.

Run: pytest -q tests/test_v2_gen.py
"""

import dataclasses
import hashlib
import json
import random

from unrender.data_gen.chart_specs import _v2_spec, random_spec
from unrender.data_gen.render import render_chart
from unrender.schema.chart_schema import canonical_json
from unrender.schema.validate import parse_chart_json

# Captured 2026-07-01 from the pre-v2 code (see module docstring).
_FROZEN_EASY = {0: "c1bd2b999bb1d065", 1: "5b441b48572326b2", 2: "4676bbe9a412a0ce",
                3: "769efebb40468e69", 4: "08526fdc05ee7ed0", 5: "0a99e461151e1f0f"}
_FROZEN_HARD = {0: "cb0c87bb164f9b1a", 1: "93d9f39ae02471d8", 2: "3a1345c2fe2f955d",
                3: "25ce323c6a6b84ca", 4: "043b81acbd84f5e0", 5: "3b69993e3dbd640a"}


_V2_ONLY_FIELDS = ("tick_format", "x_numeric", "theme")


def _fp(seed: int, hard: bool) -> str:
    s = random_spec(random.Random(seed), hard=hard)
    d = dataclasses.asdict(s)
    for f in _V2_ONLY_FIELDS:  # added after the freeze; must stay inert on frozen paths
        assert d.pop(f) in (None, False), f"frozen path set v2 field {f}: {d}"
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def test_frozen_recipes_unchanged():
    """v0 (easy) and v1 (hard) spec sequences must be byte-identical pre/post v2
    (hashes cover every pre-v2 field, i.e. everything that reaches pixels or GT)."""
    assert {s: _fp(s, False) for s in _FROZEN_EASY} == _FROZEN_EASY
    assert {s: _fp(s, True) for s in _FROZEN_HARD} == _FROZEN_HARD


def _v2_specs(n=400):
    return [_v2_spec(random.Random(10_000 + i)) for i in range(n)]


def test_v2_reaches_real_world_magnitudes():
    """The whole point of v2: values at 1e8-1e9 (the real-chart failure zone)
    must actually occur, and the B tick suffix must be reachable."""
    specs = _v2_specs()
    vmax = [max(abs(v) for row in s.values for v in row) for s in specs]
    assert any(v >= 1e8 for v in vmax), "no 1e8+ charts generated"
    assert any(v >= 5e8 for v in vmax), "no ~1e9 charts generated"
    assert any(s.tick_suffix == "B" for s in specs), "B suffix still unreachable"
    assert any(s.tick_format == "comma" for s in specs)
    assert any(s.tick_format == "plain" for s in specs)
    assert any(s.x_numeric for s in specs), "continuous year x-axis never sampled"
    themes = {s.theme for s in specs}
    assert {"owid", "dark", "news"} <= themes


def test_v2_label_free_fraction_sane():
    specs = _v2_specs()
    frac = sum(not s.value_labels_shown for s in specs) / len(specs)
    assert 0.45 <= frac <= 0.65  # ~55% label-free by design


def test_v2_big_values_are_integers():
    """Real-world big-magnitude series are integer-valued; fractional 1e9s would
    also make printed labels absurd."""
    for s in _v2_specs(200):
        if max(abs(v) for row in s.values for v in row) >= 1000:
            assert all(float(v).is_integer() for row in s.values for v in row), s.values


def test_v2_renders_and_roundtrips():
    """Every v2 feature combination must render without crashing and its GT must
    survive serialize->parse. Seeds chosen to cover themes, x_numeric, B-suffix,
    comma/plain formats (asserted below so coverage can't silently vanish)."""
    seen = set()
    for i in range(60):
        spec = _v2_spec(random.Random(20_000 + i))
        img = render_chart(spec)
        assert img.size[0] > 0 and img.size[1] > 0
        gt = spec.to_chart_data()
        parsed, errors = parse_chart_json(canonical_json(gt))
        assert parsed is not None, f"seed {20_000 + i}: {errors}"
        assert parsed.model_dump() == gt.model_dump()
        seen.add(spec.theme)
        if spec.x_numeric:
            seen.add("x_numeric")
        if spec.tick_suffix:
            seen.add("suffix")
        if spec.tick_format:
            seen.add(spec.tick_format)
    assert {"owid", "dark", "news", "x_numeric", "suffix"} <= seen, seen


def _lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_dark_theme_marks_are_visible():
    """Visual-audit regression (2026-07-06): a #22223b bar on the dark theme's
    #1c1e26 background is invisible — every dark-theme palette color must clear
    the background luminance (~0.012) by a wide margin."""
    for i in range(3000):
        s = _v2_spec(random.Random(90_000 + i))
        if s.theme == "dark":
            assert all(_lum(c) >= 0.15 for c in s.palette), (i, s.palette)


def test_no_unreadable_dense_big_labels():
    """Visual-audit regression: 8-10-digit printed labels on dense charts
    collide into unreadable ink — those specs must flip to label-free."""
    for i in range(3000):
        s = _v2_spec(random.Random(95_000 + i))
        vmax = max(abs(v) for row in s.values for v in row)
        dense = len(s.categories) > 12 or len(s.values) * len(s.categories) > 24
        assert not (s.value_labels_shown and vmax >= 1e7 and dense), (i, vmax)
