"""Native-layout failures, evidence retention and raster/geometry agreement."""

import gzip
import json
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest
from PIL import Image, ImageDraw

from unrender.data_gen.augment import _rotate
from unrender.data_gen.chart_specs import ChartSpec
from unrender.data_gen.geometry import render_with_geometry
from unrender.data_gen.render import (
    _build_figure,
    render_chart,
    render_style,
    render_with_diagnostics,
)

ROOT = Path(__file__).resolve().parents[1]


def stored_specs():
    raw = gzip.decompress(
        (ROOT / "release/synthetic-contract-v1/varied.manifest.jsonl.gz").read_bytes()
    )
    return {row["id"]: ChartSpec(**row["spec"]) for row in map(json.loads, raw.splitlines())}


@pytest.mark.parametrize("chart_id", ["0000003", "0000005", "0000006", "0000015"])
def test_retained_failure_examples_keep_all_targets_without_native_text_collisions(chart_id):
    spec = stored_specs()[chart_id]
    before = spec.to_chart_data()
    image, report = render_with_diagnostics(spec)
    assert spec.to_chart_data() == before
    assert image.size == tuple(report["native_size"])
    assert report["status"] == "clear", report
    assert report["legend_covers_plot"] is False
    printed = [item for item in report["text"] if item["id"].startswith("value:")]
    assert len(printed) == (sum(map(len, spec.values)) if spec.value_labels_shown else 0)
    categories = [item["text"] for item in report["text"] if item["id"].startswith("x_tick:")]
    assert categories == spec.categories


def test_legends_are_outside_data_rectangle_and_inside_image():
    spec = stored_specs()["0000015"]
    for location in ("best", "upper right", "upper left", "lower right", "lower left"):
        with plt.rc_context(render_style(spec)):
            fig, ax = _build_figure(replace(spec, legend_loc=location))
            try:
                fig.canvas.draw()
                box = ax.get_legend().get_window_extent(fig.canvas.get_renderer())
                data = ax.get_window_extent(fig.canvas.get_renderer())
                assert box.x0 > data.x1
                assert 0 <= box.x0 < box.x1 <= fig.bbox.width
                assert 0 <= box.y0 < box.y1 <= fig.bbox.height
            finally:
                plt.close(fig)


def test_unresolved_layout_is_recorded_not_dropped_or_relabelled():
    spec = replace(stored_specs()["0000015"], title="Wide title " * 150)
    expected = spec.to_chart_data()
    _, report = render_with_diagnostics(spec)
    assert report["status"] == "issues"
    assert report["clipped_text"]
    assert spec.to_chart_data() == expected
    assert any(item["text"] == spec.title for item in report["text"])


@pytest.mark.parametrize("chart_id", ["0000005", "0000006", "0000014", "0000015"])
def test_geometry_and_normal_raster_use_identical_style_dpi_and_layout(chart_id):
    spec = stored_specs()[chart_id]
    regular = render_chart(spec)
    geometry_image, geometry = render_with_geometry(spec)
    assert np.array_equal(np.asarray(regular), np.asarray(geometry_image))
    assert geometry["chart_type"] == spec.chart_type
    assert all(0 <= coordinate <= 1 for coordinate in geometry["plot_bbox"])


def test_rotation_retains_edge_content_and_dark_background():
    image = Image.new("RGB", (200, 100), "black")
    draw = ImageDraw.Draw(image)
    for x, y in ((2, 2), (191, 2), (2, 91), (191, 91)):
        draw.rectangle((x, y, x + 6, y + 6), fill="red")

    class Angle:
        def uniform(self, _lo, _hi):
            return 2.5

    rotated = _rotate(image, Angle())
    assert rotated.width > image.width and rotated.height > image.height
    assert rotated.getpixel((0, 0)) == (0, 0, 0)
    pixels = np.asarray(rotated)
    red = (pixels[:, :, 0] > 128) & (pixels[:, :, 1] < 30)
    # Each corner marker survives interpolation; fixed-canvas rotation crops them.
    for piece in np.array_split(red, 2, axis=0):
        assert all(part.sum() >= 40 for part in np.array_split(piece, 2, axis=1))


def test_generated_layout_flags_survive_splitting_and_loading(tmp_path):
    from unrender.data_gen.generate import generate
    from unrender.data_gen.split_dataset import split
    from unrender.eval.dataset import load_eval_samples

    generate(4, str(tmp_path), base_seed=47000, v2=True, workers=1)
    split(str(tmp_path), val_size=1, test_size=1)
    manifest = {
        row["id"]: row
        for row in map(json.loads, (tmp_path / "manifest.jsonl").read_text().splitlines())
    }
    for name in ("train", "val", "test"):
        for sample in load_eval_samples(str(tmp_path / f"{name}.jsonl")):
            entry = manifest[sample.id]
            assert sample.meta["layout_status"] == entry["layout"]["status"]
            assert sample.meta["final_font_pixels_estimate"] == entry["final_font_pixels_estimate"]
            assert sample.meta["visual_review"] == "not_reviewed"


def test_canvas_budget_fails_loudly_without_silently_reducing_targets():
    spec = replace(stored_specs()["0000015"], figsize=(31, 5))
    with pytest.raises(ValueError, match="bounded native layout canvas"):
        render_with_diagnostics(spec)
    assert not plt.get_fignums()


def test_geometry_calibration_preserves_exact_encoded_tick_anchors():
    from unrender.eval.geometry_decode import decode_geometry

    geom = {
        "chart_type": "bar",
        "ticks": [[0.248, 0], [0.366, 0.2], [0.484, 0.4], [0.603, 0.6]],
        "series": [
            {
                "name": None,
                "marks": [
                    {"x": "zero", "kind": "bar", "f": 0.248},
                    {"x": "tick", "kind": "bar", "f": 0.366},
                    {"x": "nearby", "kind": "bar", "f": 0.249},
                ],
            }
        ],
    }
    points = decode_geometry(geom).series[0].points
    assert points[0].y == 0
    assert points[1].y == 0.2
    assert points[2].y != 0  # no tolerance-based snapping of different coordinates


def test_geometry_calibration_does_not_restore_rejected_or_unused_anchors():
    from unrender.eval.geometry_decode import _fit_axis

    ticks = [[0, 0], [0.2, 0.2], [0.4, 100], [0.6, 0.6], [0.8, 0.8], [1, 1]]
    assert _fit_axis(ticks, None, "all", True)(0.4) == pytest.approx(0.4)
    assert _fit_axis(ticks, None, 2, True)(0.4) == pytest.approx(0.4)
