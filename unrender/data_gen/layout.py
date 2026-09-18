"""Measured native-raster layout, with explicit residual failures.

Text rectangles are conservative (especially for rotated glyphs). Absence of
rectangle collisions is not a certificate of OCR or numerical recoverability.
"""

from __future__ import annotations

import warnings

import numpy as np
from matplotlib import colors, patheffects
from matplotlib.text import Annotation, Text
from matplotlib.transforms import Bbox

LAYOUT_CONTRACT = "chart-layout-v1"


def text_box(text, renderer):
    if isinstance(text, Annotation):
        text.update_positions(renderer)
    # Annotation.get_window_extent also includes its leader; measure glyphs only.
    return Text.get_window_extent(text, renderer).frozen()


def visible_texts(ax):
    texts = []
    for axis_name, axis, limits in (("x", ax.xaxis, ax.get_xlim()), ("y", ax.yaxis, ax.get_ylim())):
        lo, hi = sorted(limits)
        for index, tick in enumerate(axis.get_major_ticks()):
            if lo - 1e-9 <= tick.get_loc() <= hi + 1e-9:
                texts.append((f"{axis_name}_tick:{index}", tick.label1))
        texts.append((f"{axis_name}_label", axis.label))
        texts.append((f"{axis_name}_offset", axis.get_offset_text()))
    texts.extend((text.get_gid() or f"annotation:{i}", text) for i, text in enumerate(ax.texts))
    # Title can be centered or left/right aligned by a theme.
    texts.extend(
        (f"title:{i}", text)
        for i, text in enumerate(
            child
            for child in ax.get_children()
            if isinstance(child, Text) and child not in ax.texts
        )
    )
    legend = ax.get_legend()
    if legend is not None:
        texts.extend((f"legend:{i}", text) for i, text in enumerate(legend.get_texts()))
    return [(name, text) for name, text in texts if text.get_visible() and text.get_text().strip()]


def _overlap(a, b, tolerance=0.5):
    return (
        min(a.x1, b.x1) - max(a.x0, b.x0) > tolerance
        and min(a.y1, b.y1) - max(a.y0, b.y0) > tolerance
    )


def _inside(box, outer, pad=0.0):
    return (
        box.x0 >= outer.x0 + pad
        and box.y0 >= outer.y0 + pad
        and box.x1 <= outer.x1 - pad
        and box.y1 <= outer.y1 - pad
    )


def inspect_layout(fig, ax):
    """Inspect the final native canvas; retain every collision and clipped text."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = [(name, text, text_box(text, renderer)) for name, text in visible_texts(ax)]
    overlaps = []
    for i, (name, _, box) in enumerate(items):
        for other, _, other_box in items[i + 1 :]:
            if _overlap(box, other_box):
                overlaps.append([name, other])
    clipped = [name for name, _, box in items if not _inside(box, fig.bbox, -0.5)]
    legend = ax.get_legend()
    legend_covers_plot = bool(
        legend is not None
        and _overlap(legend.get_window_extent(renderer), ax.get_window_extent(renderer))
    )
    return {
        "contract": LAYOUT_CONTRACT,
        "native_size": [int(fig.bbox.width), int(fig.bbox.height)],
        "text_overlaps": overlaps,
        "clipped_text": clipped,
        "legend_covers_plot": legend_covers_plot,
        "status": "issues" if overlaps or clipped or legend_covers_plot else "clear",
        "text": [
            {
                "id": name,
                "text": text.get_text(),
                "bbox": [round(v, 3) for v in box.extents],
                "font_pixels": round(text.get_fontsize() * fig.dpi / 72, 3),
            }
            for name, text, box in items
        ],
    }


def _place_values(fig, ax):
    renderer = fig.canvas.get_renderer()
    annotations = [text for text in ax.texts if (text.get_gid() or "").startswith("value:")]
    occupied = []
    area = ax.get_window_extent(renderer)
    for text in annotations:
        original = text._unrender_offset
        text.set_position(original)
        text.set_color(text._unrender_color)
        if text.arrow_patch is not None:
            text.arrow_patch.set_visible(False)
        box = text_box(text, renderer)
        step = max(4.0, text.get_fontsize() * 1.3)  # offsets are points, not pixels
        candidates = [(0, 0)]
        for ring in range(1, 13):
            candidates.extend(
                (dx * ring * step, dy * ring * step)
                for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, 1), (1, -1), (-1, -1))
            )
        chosen = None
        for dx, dy in candidates:
            candidate = Bbox.from_extents(
                box.x0 + dx * fig.dpi / 72,
                box.y0 + dy * fig.dpi / 72,
                box.x1 + dx * fig.dpi / 72,
                box.y1 + dy * fig.dpi / 72,
            )
            if _inside(candidate, area, 2) and not any(
                _overlap(candidate.padded(1), previous) for previous in occupied
            ):
                chosen = (dx, dy, candidate)
                break
        if chosen is not None:
            dx, dy, box = chosen
            text.set_position((original[0] + dx, original[1] + dy))
            if dx or dy:
                text.set_color(ax.xaxis.label.get_color())
            if text.arrow_patch is not None:
                text.arrow_patch.set_visible(bool(dx or dy))
        r, g, b, _ = colors.to_rgba(text.get_color())
        edge = "black" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 else "white"
        text.set_path_effects([patheffects.withStroke(linewidth=1.0, foreground=edge)])
        occupied.append(box)


def fit_layout(fig, ax, spec):
    """Keep all text; rotate crowded categories and expand within a finite budget.

    Remaining collisions are reported, never silently removed from a dataset.
    Figure size changes are style-only and recorded by the generation receipt.
    """
    for text in ax.texts:
        if (text.get_gid() or "").startswith("value:"):
            text._unrender_offset = text.get_position()
            text._unrender_color = text.get_color()
    width, height = fig.get_size_inches()
    if spec.chart_type == "horizontal_bar":
        height = max(height, len(spec.categories) * 0.22 + 1.5)
    else:
        width = max(width, len(spec.categories) * 0.20 + 1.5)
    if max(width, height) > 30 or width * height * fig.dpi**2 > 24_000_000:
        raise ValueError("chart exceeds the bounded native layout canvas")
    fig.set_size_inches(width, height)
    report = None
    for attempt in range(5):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Tight layout not applied.*")
            fig.tight_layout(pad=1.5)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        if spec.chart_type not in ("horizontal_bar", "pie") and not spec.x_numeric:
            labels = ax.get_xticklabels()
            boxes = [text_box(text, renderer) for text in labels]
            if any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :]):
                for text in labels:
                    text.set_rotation(90)
                    text.set_horizontalalignment("center")
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Tight layout not applied.*")
                    fig.tight_layout(pad=1.5)
                fig.canvas.draw()
        _place_values(fig, ax)
        report = inspect_layout(fig, ax)
        if report["status"] == "clear":
            break
        new_size = fig.get_size_inches() * 1.22
        # Bound native memory even on custom DPI/size specs; report unresolved work.
        if attempt == 4 or max(new_size) > 30 or np.prod(new_size * fig.dpi) > 24_000_000:
            break
        fig.set_size_inches(new_size)
    report["layout_passes"] = attempt + 1
    return report
