"""Deterministic pixel->value decode of a geometry program (the "compute, don't
guess" half of the method). Pure Python + numpy; no model, no learning.

Given the geometry captured by data_gen/geometry.py (or, at inference, emitted by
the VLM), fit the value axis from its tick (fraction, value) anchors and map each
mark's fraction through that fit:  value = fit(fraction).

`quant` simulates the precision a model can realistically emit fractions at
(round to `quant` decimals; None = exact). `n_ticks="all"` does an over-determined
least-squares fit (+ optional 1-outlier reject); `n_ticks=2` uses only the extreme
pair (the brittle baseline the over-determined fit is compared against).
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from unrender.schema.chart_schema import ChartData, Point, Series


def _fit_axis(ticks, quant: Optional[int], n_ticks, robust: bool):
    """Return an affine fn frac->value from tick [[frac, value], ...], or None."""
    pts = [(round(f, quant) if quant is not None else f, v) for f, v in ticks]
    # collapse ticks that quantized to the same fraction (keep mean value)
    by_f: Dict[float, list] = {}
    for f, v in pts:
        by_f.setdefault(f, []).append(v)
    fs = sorted(by_f)
    if len(fs) < 2:
        return None
    if n_ticks == 2:
        fs = [fs[0], fs[-1]]
    F = np.array(fs, dtype=float)
    V = np.array([float(np.mean(by_f[f])) for f in fs], dtype=float)
    a, b = np.polyfit(F, V, 1)
    if robust and len(fs) >= 4:
        resid = np.abs((a * F + b) - V)
        mad = np.median(np.abs(resid - np.median(resid))) or 1e-12
        keep = resid <= np.median(resid) + 3.0 * mad
        if keep.sum() >= 2 and keep.sum() < len(fs):
            a, b = np.polyfit(F[keep], V[keep], 1)
    return lambda f: a * f + b


def decode_geometry(geom: Dict, quant: Optional[int] = None, n_ticks="all",
                    robust: bool = True) -> Optional[ChartData]:
    """Decode a geometry program to ChartData. Label-free pie -> proportions
    (y in [0,1]); the scorer's pie path normalizes both sides, so that is the
    correct proxy target. Returns None if the value axis cannot be fit."""
    ct = geom["chart_type"]

    if ct == "pie":
        s = geom["series"][0]
        pts = [Point(x=m["x"], y=float(m["prop"])) for m in s["marks"]]
        return ChartData(chart_type="pie", series=[Series(name=s.get("name"), points=pts)])

    fit = _fit_axis(geom["ticks"], quant, n_ticks, robust)
    if fit is None:
        return None

    def q(f):
        return round(f, quant) if quant is not None else f

    series = []
    for s in geom["series"]:
        pts = []
        for m in s["marks"]:
            if m["kind"] == "stack_seg":
                y = float(fit(q(m["f_top"])) - fit(q(m["f_bot"])))
            else:
                y = float(fit(q(m["f"])))
            pts.append(Point(x=m["x"], y=y))
        series.append(Series(name=s.get("name"), points=pts))
    return ChartData(chart_type=ct, series=series)
