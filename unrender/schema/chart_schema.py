"""The data contract: what a chart's underlying data looks like as JSON.

This single schema is the model's output target, the ground-truth label format,
and the unit the scorer compares on. Keep it small and strict.
"""

from __future__ import annotations

import json
from typing import List, Optional, Union

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

    label: Optional[str] = None
    unit: Optional[str] = None


class Point(BaseModel):
    """One (x, y) pair. x is a category string or a numeric position."""

    x: Union[str, float]
    y: float


class Series(BaseModel):
    """One data series — a single bar/line set, or one pie's slices."""

    name: Optional[str] = None
    points: List[Point] = Field(default_factory=list)


class ChartData(BaseModel):
    """The full structured contents of one chart."""

    chart_type: ChartType
    title: Optional[str] = None
    x_axis: Axis = Field(default_factory=Axis)
    y_axis: Axis = Field(default_factory=Axis)
    series: List[Series] = Field(default_factory=list)


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
