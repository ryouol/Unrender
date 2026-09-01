"""The data contract: what a chart's underlying data looks like as JSON.

This single schema is the model's output target, the ground-truth label format,
and the unit the scorer compares on. Keep it small and strict.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

# The chart families v1 covers. Pie is included but generated/weighted lightly.
# This is the single source of truth for the taxonomy — the generator, the
# prompt, and the tests all derive from these (never re-list the names).
ChartType = str
CHART_TYPES = (
    "bar",
    "horizontal_bar",
    "grouped_bar",
    "stacked_bar",
    "line",
    "multi_line",
    "pie",
)

# Chart types that carry more than one data series (and thus a legend).
MULTI_SERIES_TYPES = frozenset({"grouped_bar", "stacked_bar", "multi_line"})


class Axis(BaseModel):
    """An axis label split from its unit (e.g. label="Revenue", unit="USD")."""

    label: str | None = None
    unit: str | None = None


class Point(BaseModel):
    """One (x, y) pair. x is a category string or a numeric position."""

    x: str | float
    y: float


class Series(BaseModel):
    """One data series — a single bar/line set, or one pie's slices."""

    name: str | None = None
    points: list[Point] = Field(default_factory=list)


class ChartData(BaseModel):
    """The full structured contents of one chart."""

    chart_type: ChartType
    title: str | None = None
    x_axis: Axis = Field(default_factory=Axis)
    y_axis: Axis = Field(default_factory=Axis)
    series: list[Series] = Field(default_factory=list)


def canonical_json(data: ChartData) -> str:
    """Compact, stable JSON string used as the training target.

    Stable key order and no superfluous whitespace so identical data always
    serializes to an identical target string.
    """
    return json.dumps(data.model_dump(), ensure_ascii=False, separators=(",", ":"))


def x_key(x) -> str:
    """Canonical string form of a Point's x value.

    Collapses integral floats (2020.0 -> "2020") so the CSV exporter and the
    scorer agree on point identity. This is the one place that rule lives — both
    must route through here, or they silently disagree on what "the same point"
    means.
    """
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x)


def data_table_signature(data: ChartData) -> str:
    """Hash of the underlying DATA TABLE only — chart_type plus each series' name
    and its (x, y) points — ignoring title / axis labels / styling.

    Two charts with the same numbers but different cosmetics collide, which is
    exactly the leak that matters: a held-out chart whose answer table equals a
    TRAIN chart's is memorizable and would inflate apparent skill. Use to dedup
    across train/val/test (audit finding G — the generator splits on image id, so
    this is the table-level guard that catches a re-rendered duplicate).
    """
    payload: list[object] = [data.chart_type]
    for s in data.series:
        pts = sorted((x_key(p.x), round(float(p.y), 6)) for p in s.points)
        payload.append([s.name or "", pts])
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]
