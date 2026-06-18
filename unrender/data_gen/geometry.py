"""Capture EXACT renderer geometry for a ChartSpec — the privileged supervision
the synthetic renderer can provide but no real-chart corpus has.

For each chart we read back, from the same figure render.py rasterizes:
  - plot_bbox: the axes rectangle in figure-fraction coords [0,1]
  - ticks: every value-axis tick as (axis_fraction, value) — the calibration anchors
  - per-mark value-axis fraction in CANONICAL order (series in legend order; within
    a series left-to-right by category), so a deterministic affine fit recovers the
    value from a mark's pixel: value = fit(fraction).

All coordinates are figure-FRACTION (DPI-independent, [0,1], matplotlib origin
bottom-left). The deterministic decoder (unrender/eval/geometry_decode.py) only
needs ticks and marks on the SAME axis, so the orientation convention is internal.

`render_with_geometry(spec)` returns (image, geometry) so the training-data
serializer emits both; `capture_geometry(spec)` returns geometry alone.
"""

from __future__ import annotations

import io
from typing import Dict, List

import numpy as np
from PIL import Image

import matplotlib.pyplot as plt

from unrender.data_gen.chart_specs import ChartSpec
from unrender.data_gen.render import _build_figure


def _frac(fig, ax, xy) -> tuple:
    """data (x,y) -> figure-fraction (xf, yf) in [0,1]."""
    disp = ax.transData.transform(xy)
    xf, yf = fig.transFigure.inverted().transform(disp)
    return float(xf), float(yf)


def _value_axis_ticks(fig, ax, horizontal: bool) -> List[list]:
    """Every major tick within the view, as [axis_fraction, value]."""
    if horizontal:
        lo, hi = ax.get_xlim()
        ticks = [t for t in ax.get_xticks() if min(lo, hi) - 1e-9 <= t <= max(lo, hi) + 1e-9]
        ymid = sum(ax.get_ylim()) / 2
        return [[_frac(fig, ax, (t, ymid))[0], float(t)] for t in ticks]
    lo, hi = ax.get_ylim()
    ticks = [t for t in ax.get_yticks() if min(lo, hi) - 1e-9 <= t <= max(lo, hi) + 1e-9]
    xmid = sum(ax.get_xlim()) / 2
    return [[_frac(fig, ax, (xmid, t))[1], float(t)] for t in ticks]


def capture_geometry(spec: ChartSpec) -> Dict:
    """Render `spec` and read back its exact geometry program (figure-fraction)."""
    with plt.rc_context({"font.family": spec.font_family}):
        fig, ax = _build_figure(spec)
        try:
            fig.canvas.draw()  # finalize transforms after tight_layout
            return _read_geometry(fig, ax, spec)
        finally:
            plt.close(fig)


def render_with_geometry(spec: ChartSpec):
    """Return (PIL image, geometry dict) from a single render — for the training
    serializer, so image and geometry can never drift."""
    with plt.rc_context({"font.family": spec.font_family}):
        fig, ax = _build_figure(spec)
        try:
            fig.canvas.draw()
            geom = _read_geometry(fig, ax, spec)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=spec.dpi)
            buf.seek(0)
            return Image.open(buf).convert("RGB"), geom
        finally:
            plt.close(fig)


def _read_geometry(fig, ax, spec: ChartSpec) -> Dict:
    ct = spec.chart_type
    cats = spec.categories
    x = np.arange(len(cats))
    bbox = ax.get_position()  # figure-fraction Bbox
    geom: Dict = {
        "chart_type": ct,
        "plot_bbox": [float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)],
    }

    if ct == "pie":
        total = float(sum(spec.values[0])) or 1.0
        geom["value_axis"] = None
        geom["ticks"] = []
        geom["series"] = [{
            "name": spec.series_names[0],
            "kind": "pie",
            "marks": [{"x": cats[j], "prop": float(spec.values[0][j]) / total} for j in range(len(cats))],
        }]
        return geom

    horizontal = ct == "horizontal_bar"
    geom["value_axis"] = "x" if horizontal else "y"
    geom["ticks"] = _value_axis_ticks(fig, ax, horizontal)

    def vfrac(xy):  # value-axis fraction of a data point
        xf, yf = _frac(fig, ax, xy)
        return xf if horizontal else yf

    series = []
    if ct in ("bar", "horizontal_bar"):
        row = spec.values[0]
        marks = [{"x": cats[j], "kind": "bar",
                  "f": vfrac((row[j], j) if horizontal else (j, row[j]))} for j in range(len(cats))]
        series.append({"name": spec.series_names[0], "marks": marks})
    elif ct == "grouped_bar":
        n_series = len(spec.values)
        width = 0.8 / n_series
        for i, vrow in enumerate(spec.values):
            offset = (i - (n_series - 1) / 2) * width
            marks = [{"x": cats[j], "kind": "bar", "f": vfrac((x[j] + offset, vrow[j]))}
                     for j in range(len(cats))]
            series.append({"name": spec.series_names[i], "marks": marks})
    elif ct == "stacked_bar":
        bottom = np.zeros(len(cats))
        for i, vrow in enumerate(spec.values):
            marks = []
            for j in range(len(cats)):
                f_bot = vfrac((j, bottom[j]))
                f_top = vfrac((j, bottom[j] + vrow[j]))
                marks.append({"x": cats[j], "kind": "stack_seg", "f_bot": f_bot, "f_top": f_top})
            series.append({"name": spec.series_names[i], "marks": marks})
            bottom += np.array(vrow, dtype=float)
    elif ct in ("line", "multi_line"):
        for i, vrow in enumerate(spec.values):
            marks = [{"x": cats[j], "kind": "point", "f": vfrac((x[j], vrow[j]))}
                     for j in range(len(cats))]
            series.append({"name": spec.series_names[i], "marks": marks})
    else:
        raise ValueError(f"capture_geometry: unhandled chart_type {ct!r}")

    geom["series"] = series
    return geom
