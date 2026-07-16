"""Generate random-but-realistic chart specifications.

A ChartSpec carries BOTH the ground-truth data (chart_type, title, axes,
categories, exact values) AND the rendering style (palette, dpi, whether value
labels are printed, ...). render.py draws it; to_chart_data() extracts the
label. Because both read the same spec, the image and the label can never drift.

The single most important knob is `value_labels_shown`. When False, the model
must measure bar/point geometry against the axis scale to recover values — the
exact skill frontier models lack. We keep ~half the dataset label-free.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

from unrender.schema.chart_schema import (
    CHART_TYPES,
    MULTI_SERIES_TYPES,
    Axis,
    ChartData,
    Point,
    Series,
)

# Sampling weights, keyed by the canonical chart types. The assert keeps this in
# sync with the schema's taxonomy — add a type there and this fails loudly.
CHART_TYPE_WEIGHTS = {
    "bar": 0.20,
    "horizontal_bar": 0.12,
    "grouped_bar": 0.15,
    "stacked_bar": 0.13,
    "line": 0.15,
    "multi_line": 0.15,
    "pie": 0.10,
}
if set(CHART_TYPE_WEIGHTS) != set(CHART_TYPES):  # plain raise, not assert (survives python -O)
    raise RuntimeError("CHART_TYPE_WEIGHTS out of sync with CHART_TYPES")
_CT_NAMES, _CT_WEIGHTS = zip(*CHART_TYPE_WEIGHTS.items())  # precomputed once for sampling

# --- Word banks (business/finance/science flavored, on-distribution) ---------
_METRICS = [
    "Revenue", "Sales", "Profit", "Net Income", "Expenses", "Users",
    "Active Users", "Downloads", "Visitors", "Market Share", "Population",
    "Temperature", "Rainfall", "GDP", "Production", "Headcount", "Latency",
    "Throughput", "Conversion Rate", "Growth", "Cost", "Budget", "Energy Use",
]
_UNITS = ["USD", "EUR", "%", "K", "M", "units", "ms", "°C", "mm", "people", "GB", "kWh"]
_PALETTES = [
    ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"],  # seaborn deep
    ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"],  # mpl default
    ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51"],  # earthy
    ["#003f5c", "#58508d", "#bc5090", "#ff6361", "#ffa600"],  # sunset
    ["#0b6e4f", "#08a045", "#6bbf59", "#ddd92a", "#eabe7c"],  # greens
    ["#22223b", "#4a4e69", "#9a8c98", "#c9ada7", "#f2e9e4"],  # muted
]
_FONTS = ["sans-serif", "serif", "monospace", "DejaVu Sans", "DejaVu Serif"]
_LEGEND_LOCS = ["best", "upper right", "upper left", "lower right", "lower left"]

# Near-monochrome ramps for hard mode: 4-6 series in similar shades are hard to
# tell apart (forces the model to track position, not just color).
_MONO_PALETTES = [
    ["#08306b", "#2171b5", "#4292c6", "#6baed6", "#9ecae1", "#c6dbef"],  # blues
    ["#00441b", "#238b45", "#41ab5d", "#74c476", "#a1d99b", "#c7e9c0"],  # greens
    ["#7f2704", "#d94801", "#f16913", "#fd8d3c", "#fdae6b", "#fdd0a2"],  # oranges
    ["#3f007d", "#6a51a3", "#807dba", "#9e9ac8", "#bcbddc", "#dadaeb"],  # purples
    ["#252525", "#525252", "#737373", "#969696", "#bdbdbd", "#d9d9d9"],  # greys
]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
_COUNTRIES = ["USA", "China", "India", "Germany", "Japan", "Brazil", "UK", "France", "Canada", "Italy", "Spain", "Mexico"]
_REGIONS = ["North", "South", "East", "West", "Central", "APAC", "EMEA", "LATAM"]
_PRODUCTS = ["Product A", "Product B", "Product C", "Product D", "Product E", "Product F"]


@dataclass
class ChartSpec:
    # --- ground truth --- (the x axis never carries a unit, only a label)
    chart_type: str
    title: Optional[str]
    x_label: Optional[str]
    y_label: Optional[str]
    y_unit: Optional[str]
    categories: List[str]
    series_names: List[Optional[str]]
    values: List[List[float]]  # [n_series][n_cat], exactly what gets drawn
    # --- style (rendering only) ---
    value_labels_shown: bool = False
    palette: List[str] = field(default_factory=lambda: _PALETTES[0])
    grid: bool = True
    legend_loc: str = "best"
    font_family: str = "sans-serif"
    dpi: int = 100
    figsize: tuple = (7.0, 5.0)
    rotate_xticks: int = 0
    decimals: int = 0
    thousands_sep: bool = False
    # --- hard-mode style knobs (eval-v1); all default to the easy v0 behavior ---
    y_baseline: Optional[float] = None   # truncated/non-zero value-axis floor
    y_top: Optional[float] = None        # unrounded value-axis maximum
    tick_suffix: Optional[str] = None    # "K" / "M" / "B" value-axis tick suffix
    minor_ticks: bool = False
    # --- v2 knobs (synthetic_v2); all default to the frozen v0/v1 behavior ---
    tick_format: Optional[str] = None    # "comma" (1,200,000) / "plain" (full raw digits)
    x_numeric: bool = False              # line charts: continuous numeric x-axis, sparse auto ticks
    theme: Optional[str] = None          # "owid" / "dark" / "news" rendering style

    def to_chart_data(self) -> ChartData:
        """Build the exact ground-truth label from this spec."""
        series = [
            Series(
                name=self.series_names[i],
                points=[Point(x=self.categories[j], y=self.values[i][j]) for j in range(len(self.categories))],
            )
            for i in range(len(self.values))
        ]
        return ChartData(
            chart_type=self.chart_type,
            title=self.title,
            x_axis=Axis(label=self.x_label, unit=None),
            y_axis=Axis(label=self.y_label, unit=self.y_unit),
            series=series,
        )


def _weighted_chart_type(rng: random.Random) -> str:
    return rng.choices(_CT_NAMES, weights=_CT_WEIGHTS, k=1)[0]


def _pooled(rng: random.Random, pool: List[str], n: int, noun: str, fmt) -> tuple:
    """Sample up to len(pool) unique labels; pad any overflow via fmt(index)."""
    picks = rng.sample(pool, min(n, len(pool)))
    picks += [fmt(len(pool) + i) for i in range(max(0, n - len(pool)))]
    return picks, noun


def _categories(rng: random.Random, n: int) -> tuple:
    """Exactly n unique category labels (+ dimension name). Pads if the chosen
    pool can't supply n (e.g. >12 months in hard mode) — a no-op for n<=12."""
    labels, dim = _categories_raw(rng, n)
    labels = labels[:n]
    if len(labels) < n:
        labels += [f"{dim} {len(labels) + i + 1}" for i in range(n - len(labels))]
    return labels, dim


def _categories_raw(rng: random.Random, n: int) -> tuple:
    """Return (n UNIQUE category labels of one coherent kind, dimension name).

    The dimension name describes the categories (e.g. quarters -> "Quarter") so
    the x-axis label and title stay consistent with what's actually plotted.
    """
    kind = rng.choice(["months", "quarters", "years", "countries", "regions", "products", "generic"])
    if kind == "months":
        start = rng.randint(0, max(0, 12 - n))
        return _MONTHS[start : start + n], "Month"
    if kind == "quarters":
        # Sequential quarters across years -> always unique. Force the year
        # suffix once we wrap past Q4, otherwise Q1..Q4 would repeat.
        with_year = (rng.random() < 0.6) or n > 4
        year = rng.randint(2015, 2023)
        qi = rng.randint(0, 3)
        out = []
        for _ in range(n):
            out.append(f"{_QUARTERS[qi]} {year}" if with_year else _QUARTERS[qi])
            qi += 1
            if qi == 4:
                qi, year = 0, year + 1
        return out, "Quarter"
    if kind == "years":
        start = rng.randint(1995, 2020)
        return [str(start + i) for i in range(n)], "Year"
    if kind == "countries":
        return _pooled(rng, _COUNTRIES, n, "Country", lambda k: f"Country {k + 1}")
    if kind == "regions":
        return _pooled(rng, _REGIONS, n, "Region", lambda k: f"Region {k + 1}")
    if kind == "products":
        return _pooled(rng, _PRODUCTS, n, "Product", lambda k: f"Product {chr(65 + k)}")
    return [f"Cat {i+1}" for i in range(n)], "Category"


def _series_names(rng: random.Random, n: int) -> List[str]:
    """n series names drawn from ONE coherent pool (all products, all regions,
    or generic), so a chart's legend doesn't mix products with regions."""
    kind = rng.choice(["products", "regions", "generic"])
    if kind == "generic":
        return [f"Series {i + 1}" for i in range(n)]
    pool = _PRODUCTS if kind == "products" else _REGIONS
    return rng.sample(pool, n)  # n <= 4 <= len(pool)


def _title(rng: random.Random, metric: str, dim: str) -> Optional[str]:
    if rng.random() < 0.12:
        return None  # ~12% of real charts have no title
    template = rng.choice([
        "{metric} by {dim}", "{metric} per {dim}", "{dim} {metric}",
        "{metric} Overview", "Annual {metric}", "{metric} Breakdown",
        "{metric} ({dim})", "Total {metric} by {dim}",
    ])
    return template.format(metric=metric, dim=dim)


# v0/v1 magnitude ceiling: max value < 1e6. The 2026-07-01 sweep showed real
# charts live at 1e8-1e9 (population, total CO2) and the model scored 0% there —
# it had never emitted an 8-10 digit number. v2 extends the range to 1e9.
_SCALES = [1, 10, 100, 1000, 10_000, 100_000, 1_000_000]
_V2_SCALES = _SCALES + [10_000_000, 100_000_000, 1_000_000_000]


def _values(rng: random.Random, n_series: int, n_cat: int, allow_negative: bool, decimals: int,
            scales: List[int] = _SCALES):
    # NOTE: the draw ORDER here (choice, then random per cell) is frozen — v0/v1
    # regenerate byte-identically because `scales` defaults to the original list.
    scale = rng.choice(scales)
    out: List[List[float]] = []
    for _ in range(n_series):
        row = []
        for _ in range(n_cat):
            v = rng.random() * scale
            if allow_negative and rng.random() < 0.3:
                v -= scale * 0.5
            v = round(v, decimals)
            row.append(int(v) if decimals == 0 else v)
        out.append(row)
    return out


def random_spec(rng: random.Random, hard: bool = False, v2: bool = False) -> ChartSpec:
    """Produce one fully-specified random chart.

    hard=True enables the eval-v1 escalations (denser data, truncated/unrounded
    value axes, K/M/B ticks, similar palettes, smaller figures). v2=True is the
    2026-07 real-transfer escalation (magnitudes to 1e9, real-world axis formats,
    continuous year x-axes, themes). Each mode is a separate function so the
    frozen paths' RNG sequences stay byte-identical — regenerating v0/v1 from
    their recipes still reproduces them exactly.
    """
    if v2:
        return _v2_spec(rng)
    if hard:
        return _hard_spec(rng)
    chart_type = _weighted_chart_type(rng)
    is_multi = chart_type in MULTI_SERIES_TYPES
    is_pie = chart_type == "pie"

    n_series = rng.randint(2, 4) if is_multi else 1
    n_cat = rng.randint(3, 7) if is_pie else rng.randint(3, 12)

    metric = rng.choice(_METRICS)
    categories, dim = _categories(rng, n_cat)

    decimals = rng.choice([0, 0, 0, 1, 2])
    allow_negative = (not is_pie) and chart_type in ("bar", "horizontal_bar", "line", "multi_line") and rng.random() < 0.15
    values = _values(rng, n_series, n_cat, allow_negative, decimals)
    if is_pie:
        # Pie slices must be strictly POSITIVE: an all-zero pie (reachable at
        # scale=1, decimals=0) has a zero total, which makes matplotlib's ax.pie
        # divide by zero -> NaN -> crash, and is degenerate ground truth anyway.
        values = [[max(abs(v), 1) for v in values[0]]]

    # Series names only when there is a legend (multi-series).
    if is_multi:
        series_names = _series_names(rng, n_series)
    else:
        series_names = [metric if rng.random() < 0.5 else None]

    has_unit = rng.random() < 0.45
    unit = rng.choice(_UNITS) if has_unit else None

    long_labels = any(len(c) > 6 for c in categories)
    rotate = rng.choice([0, 0, 30, 45, 90]) if (long_labels or n_cat > 8) else rng.choice([0, 0, 0, 45])

    return ChartSpec(
        chart_type=chart_type,
        title=_title(rng, metric, dim),
        x_label=None if is_pie else (dim if rng.random() < 0.85 else None),
        y_label=None if is_pie else (metric if rng.random() < 0.85 else None),
        y_unit=None if is_pie else unit,
        categories=categories,
        series_names=series_names,
        values=values,
        value_labels_shown=rng.random() < 0.48,  # ~half label-free (the hard, valuable case)
        palette=rng.choice(_PALETTES),
        grid=rng.random() < 0.55,
        legend_loc=rng.choice(_LEGEND_LOCS),
        font_family=rng.choice(_FONTS),
        dpi=rng.choice([72, 96, 100, 150, 200]),
        figsize=(round(rng.uniform(4.5, 9.5), 1), round(rng.uniform(3.2, 6.5), 1)),
        rotate_xticks=rotate,
        decimals=decimals,
        thousands_sep=rng.random() < 0.4,
    )


def _hard_spec(rng: random.Random) -> ChartSpec:
    """eval-v1 hard charts (see CHANGELOG): 15-60 points, 4-6 similar-shade
    series, truncated/unrounded value axes, K/M/B ticks, smaller figures, more
    label-free. Separate RNG path so it can't perturb the v0 (easy) sequence."""
    chart_type = _weighted_chart_type(rng)
    is_multi = chart_type in MULTI_SERIES_TYPES
    is_pie = chart_type == "pie"

    if is_pie:
        n_series, n_cat = 1, rng.randint(4, 8)                    # pies stay readable
    elif is_multi:
        n_series, n_cat = rng.randint(4, 6), rng.randint(4, 10)   # 16-60 points
    else:
        n_series, n_cat = 1, rng.randint(15, 40)                  # dense single series

    metric = rng.choice(_METRICS)
    categories, dim = _categories(rng, n_cat)

    decimals = rng.choice([0, 0, 0, 1, 2])
    allow_negative = (not is_pie) and chart_type in ("bar", "horizontal_bar", "line", "multi_line") and rng.random() < 0.2
    values = _values(rng, n_series, n_cat, allow_negative, decimals)
    if is_pie:
        values = [[max(abs(v), 1) for v in values[0]]]

    series_names = _series_names(rng, n_series) if is_multi else [metric if rng.random() < 0.5 else None]

    has_unit = rng.random() < 0.45
    unit = rng.choice(_UNITS) if has_unit else None
    rotate = rng.choice([0, 30, 45, 90]) if n_cat > 6 else rng.choice([0, 0, 45])

    # Value-axis hardening (truncated baseline, unrounded max, K/M/B ticks).
    y_baseline = y_top = tick_suffix = None
    flat = [v for row in values for v in row] or [0.0, 1.0]
    vmin, vmax = min(flat), max(flat)
    if not is_pie:
        if vmin > 0 and rng.random() < 0.6:
            y_baseline = round(vmin * rng.uniform(0.5, 0.9), 4)
        if rng.random() < 0.7:
            y_top = round(vmax * rng.uniform(1.02, 1.12), 4)
        if vmax >= 1e4 and rng.random() < 0.6:
            tick_suffix = "B" if vmax >= 1e9 else "M" if vmax >= 1e6 else "K"

    return ChartSpec(
        chart_type=chart_type,
        title=_title(rng, metric, dim),
        x_label=None if is_pie else (dim if rng.random() < 0.85 else None),
        y_label=None if is_pie else (metric if rng.random() < 0.85 else None),
        y_unit=None if is_pie else unit,
        categories=categories,
        series_names=series_names,
        values=values,
        value_labels_shown=rng.random() < 0.35,   # ~65% label-free (the hard case)
        palette=rng.choice(_MONO_PALETTES) if is_multi else rng.choice(_PALETTES),
        grid=rng.random() < 0.35,
        legend_loc=rng.choice(_LEGEND_LOCS),
        font_family=rng.choice(_FONTS),
        dpi=rng.choice([72, 96, 100, 150]),
        figsize=(round(rng.uniform(3.2, 5.5), 1), round(rng.uniform(2.6, 4.2), 1)),
        rotate_xticks=rotate,
        decimals=decimals,
        thousands_sep=rng.random() < 0.3,
        y_baseline=y_baseline, y_top=y_top, tick_suffix=tick_suffix,
    )


_V2_THEMES = [None, None, None, "owid", "dark", "news"]  # 50% themed

# Dark-theme-safe palettes (visual audit 2026-07-06): the standard palettes'
# darkest entries (#22223b, #252525, #08306b, ...) are near-invisible on the
# dark theme's #1c1e26 background — a bar the model literally cannot see is
# garbage supervision. Bright sets + the LIGHT ends of the mono ramps (which
# keep the "similar shades" difficulty without vanishing).
_DARK_THEME_PALETTES = [
    ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8"],  # bright material
    ["#8ab4f8", "#f28b82", "#fdd663", "#81c995", "#ff8bcb"],  # dark-mode classics
] + [list(reversed(p))[:5] for p in _MONO_PALETTES]           # light-first ramps


def _v2_spec(rng: random.Random) -> ChartSpec:
    """synthetic_v2 (2026-07, see FRONTIER_PLAN.md): everything the sweep showed
    real charts have and v0/v1 lack — values up to 1e9 rendered with real-world
    axis formats (K/M/B suffixes incl. the previously-unreachable B, comma
    grouping, full raw digits, mpl offset), continuous numeric year x-axes with
    sparse auto ticks, and OWID/dark/news themes. Density mixes easy and hard.
    Separate RNG path so it can't perturb the frozen v0/v1 sequences."""
    chart_type = _weighted_chart_type(rng)
    is_multi = chart_type in MULTI_SERIES_TYPES
    is_pie = chart_type == "pie"

    dense = rng.random() < 0.55
    if is_pie:
        n_series, n_cat = 1, rng.randint(3, 8)
    elif is_multi:
        n_series, n_cat = (rng.randint(4, 6), rng.randint(4, 10)) if dense else (rng.randint(2, 4), rng.randint(3, 8))
    else:
        n_series, n_cat = 1, (rng.randint(15, 40) if dense else rng.randint(3, 12))

    metric = rng.choice(_METRICS)
    categories, dim = _categories(rng, n_cat)

    decimals = rng.choice([0, 0, 0, 1, 2])
    allow_negative = (not is_pie) and chart_type in ("bar", "horizontal_bar", "line", "multi_line") and rng.random() < 0.15
    values = _values(rng, n_series, n_cat, allow_negative, decimals, scales=_V2_SCALES)
    flat = [v for row in values for v in row] or [0.0, 1.0]
    if max(abs(v) for v in flat) >= 1000:
        # big-magnitude charts are integer-valued in the real world
        values = [[int(round(v)) for v in row] for row in values]
        decimals = 0
        flat = [v for row in values for v in row]
    if is_pie:
        values = [[max(abs(v), 1) for v in values[0]]]
        flat = values[0]

    series_names = _series_names(rng, n_series) if is_multi else [metric if rng.random() < 0.5 else None]
    has_unit = rng.random() < 0.45
    unit = rng.choice(_UNITS) if has_unit else None
    rotate = rng.choice([0, 30, 45, 90]) if n_cat > 6 else rng.choice([0, 0, 45])

    # Value-axis rendering: spread big numbers across the REAL formats a model
    # must read — suffix ticks (K/M/B), comma grouping, full raw digits, or the
    # matplotlib default (which shows offset "1e8"-style notation when large).
    vmin, vmax = min(flat), max(flat)
    y_baseline = y_top = tick_suffix = tick_format = None
    if not is_pie:
        if vmin > 0 and rng.random() < 0.5:
            y_baseline = round(vmin * rng.uniform(0.5, 0.9), 4)
        if rng.random() < 0.6:
            y_top = round(vmax * rng.uniform(1.02, 1.12), 4)
        if vmax >= 1e4:
            r = rng.random()
            if r < 0.40:
                # Fractional thresholds, NOT >= 1e9: values are rng.random()*scale
                # so vmax is always strictly below the scale — a >= 1e9 gate would
                # make "B" unreachable (the exact dead-branch bug v1 had). A chart
                # topping out at 0.6e9 legitimately reads "0.2B .. 0.6B" on its axis.
                tick_suffix = "B" if vmax >= 2.5e8 else "M" if vmax >= 2.5e5 else "K"
            elif r < 0.65:
                tick_format = "comma"
            elif r < 0.85:
                tick_format = "plain"
            # else: matplotlib default (offset notation at large magnitudes)

    # Continuous year x-axis (the OWID/FRED look): numeric years on a real axis
    # with sparse auto ticks, instead of every category printed as a label.
    x_numeric = chart_type in ("line", "multi_line") and dim == "Year" and rng.random() < 0.6

    theme = rng.choice(_V2_THEMES)
    palette = rng.choice(_MONO_PALETTES) if (is_multi and dense) else rng.choice(_PALETTES)
    if theme == "dark":
        palette = rng.choice(_DARK_THEME_PALETTES)  # visual audit: no invisible marks

    value_labels_shown = rng.random() < 0.45  # ~55% label-free
    if value_labels_shown and vmax >= 1e7 and (n_cat > 12 or n_series * n_cat > 24):
        # Visual audit: 8-10-digit printed labels at this density collide into
        # unreadable ink — supervision noise, not signal. Flip to label-free;
        # sparse big-magnitude charts keep their printed labels.
        value_labels_shown = False

    return ChartSpec(
        chart_type=chart_type,
        title=_title(rng, metric, dim),
        x_label=None if is_pie else (dim if rng.random() < 0.85 else None),
        y_label=None if is_pie else (metric if rng.random() < 0.85 else None),
        y_unit=None if is_pie else unit,
        categories=categories,
        series_names=series_names,
        values=values,
        value_labels_shown=value_labels_shown,
        palette=palette,
        grid=rng.random() < 0.55,
        legend_loc=rng.choice(_LEGEND_LOCS),
        font_family=rng.choice(_FONTS),
        dpi=rng.choice([72, 96, 100, 150, 200]),
        figsize=(round(rng.uniform(3.6, 9.5), 1), round(rng.uniform(2.8, 6.5), 1)),
        rotate_xticks=rotate,
        decimals=decimals,
        thousands_sep=(rng.random() < 0.7) if vmax >= 1e4 else (rng.random() < 0.4),
        y_baseline=y_baseline, y_top=y_top, tick_suffix=tick_suffix,
        minor_ticks=rng.random() < 0.3,
        tick_format=tick_format,
        x_numeric=x_numeric,
        theme=theme,
    )
