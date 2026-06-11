"""Render a ChartSpec to a PIL image with matplotlib.

All value labels are formatted from the spec's exact values, so any number
printed on the chart equals the ground-truth number byte-for-byte. The variety
(palette, dpi, fonts, rotation, gridlines, value-labels-on/off) is what forces
the model to generalize instead of memorizing one chart look.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")  # headless; must be set before pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from unrender.data_gen.chart_specs import ChartSpec  # noqa: E402


def _fmt(v: float, decimals: int, thousands_sep: bool) -> str:
    if decimals == 0:
        return f"{int(round(v)):,}" if thousands_sep else f"{int(round(v))}"
    return f"{v:,.{decimals}f}" if thousands_sep else f"{v:.{decimals}f}"


def _axis_text(label, unit=None):
    if label and unit:
        return f"{label} ({unit})"
    return label or ""


def _apply_value_axis(ax, spec, horizontal):
    """eval-v1 hardening of the value axis: truncated baseline, unrounded max,
    and K/M/B tick suffixes. No-op unless the spec sets those knobs."""
    if spec.y_baseline is None and spec.y_top is None and not spec.tick_suffix:
        return
    get_lim, set_lim = (ax.get_xlim, ax.set_xlim) if horizontal else (ax.get_ylim, ax.set_ylim)
    axis = ax.xaxis if horizontal else ax.yaxis
    if spec.y_baseline is not None or spec.y_top is not None:
        lo, hi = get_lim()
        set_lim(spec.y_baseline if spec.y_baseline is not None else lo,
                spec.y_top if spec.y_top is not None else hi)
    if spec.tick_suffix:
        from matplotlib.ticker import FuncFormatter
        div = {"K": 1e3, "M": 1e6, "B": 1e9}[spec.tick_suffix]
        suffix = spec.tick_suffix
        axis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v / div:g}{suffix}"))


def render_chart(spec: ChartSpec) -> Image.Image:
    """Draw the chart described by `spec` and return it as a PIL RGB image."""
    # Scope the font choice so it can't leak into the next render in this worker.
    with plt.rc_context({"font.family": spec.font_family}):
        return _draw_chart(spec)


def _draw_chart(spec: ChartSpec) -> Image.Image:
    fig, ax = plt.subplots(figsize=spec.figsize)

    n_cat = len(spec.categories)
    x = np.arange(n_cat)
    colors = spec.palette
    fmt = lambda v: _fmt(v, spec.decimals, spec.thousands_sep)  # noqa: E731

    ct = spec.chart_type

    if ct in ("bar", "horizontal_bar"):
        row = spec.values[0]
        if ct == "bar":
            bars = ax.bar(x, row, color=colors[0])
            ax.set_xticks(x)
            ax.set_xticklabels(spec.categories, rotation=spec.rotate_xticks,
                               ha="right" if spec.rotate_xticks else "center")
        else:
            bars = ax.barh(x, row, color=colors[0])
            ax.set_yticks(x)
            ax.set_yticklabels(spec.categories)
        if spec.value_labels_shown:
            ax.bar_label(bars, labels=[fmt(v) for v in row], padding=2, fontsize=8)

    elif ct in ("grouped_bar", "stacked_bar"):
        n_series = len(spec.values)
        if ct == "grouped_bar":
            width = 0.8 / n_series
            for i, row in enumerate(spec.values):
                offset = (i - (n_series - 1) / 2) * width
                bars = ax.bar(x + offset, row, width, label=spec.series_names[i], color=colors[i % len(colors)])
                if spec.value_labels_shown:
                    ax.bar_label(bars, labels=[fmt(v) for v in row], padding=2, fontsize=7, rotation=90)
        else:  # stacked
            bottom = np.zeros(n_cat)
            for i, row in enumerate(spec.values):
                bars = ax.bar(x, row, bottom=bottom, label=spec.series_names[i], color=colors[i % len(colors)])
                if spec.value_labels_shown:
                    ax.bar_label(bars, labels=[fmt(v) for v in row], label_type="center", fontsize=7)
                bottom += np.array(row)
        ax.set_xticks(x)
        ax.set_xticklabels(spec.categories, rotation=spec.rotate_xticks,
                           ha="right" if spec.rotate_xticks else "center")
        ax.legend(loc=spec.legend_loc, fontsize=8)

    elif ct in ("line", "multi_line"):
        for i, row in enumerate(spec.values):
            ax.plot(x, row, marker="o", label=spec.series_names[i], color=colors[i % len(colors)])
            if spec.value_labels_shown:
                for xi, v in zip(x, row):
                    ax.annotate(fmt(v), (xi, v), textcoords="offset points", xytext=(0, 6),
                                ha="center", fontsize=7)
        ax.set_xticks(x)
        ax.set_xticklabels(spec.categories, rotation=spec.rotate_xticks,
                           ha="right" if spec.rotate_xticks else "center")
        if len(spec.values) > 1:
            ax.legend(loc=spec.legend_loc, fontsize=8)

    elif ct == "pie":
        row = spec.values[0]
        wedges, _ = ax.pie(row, labels=spec.categories, colors=colors[: len(row)] * (len(row) // len(colors) + 1))
        if spec.value_labels_shown:
            for w, v in zip(wedges, row):
                ang = np.deg2rad((w.theta1 + w.theta2) / 2)
                ax.text(0.6 * np.cos(ang), 0.6 * np.sin(ang), fmt(v), ha="center", va="center", fontsize=8)
        ax.set_aspect("equal")

    else:
        # Never silently emit a blank image with a valid label — that would
        # poison the dataset undetectably. Fail loudly on an unhandled type.
        plt.close(fig)
        raise ValueError(f"render: unhandled chart_type {ct!r}")

    # Titles, axis labels, grid (skip axis chrome for pie).
    if spec.title:
        ax.set_title(spec.title, fontsize=12, fontweight="bold")
    if ct != "pie":
        if ct == "horizontal_bar":
            ax.set_xlabel(_axis_text(spec.y_label, spec.y_unit))
            ax.set_ylabel(_axis_text(spec.x_label))
        else:
            ax.set_xlabel(_axis_text(spec.x_label))
            ax.set_ylabel(_axis_text(spec.y_label, spec.y_unit))
        if spec.grid:
            ax.grid(axis="x" if ct == "horizontal_bar" else "y", linestyle="--", alpha=0.5)
        _apply_value_axis(ax, spec, horizontal=(ct == "horizontal_bar"))

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=spec.dpi)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")
