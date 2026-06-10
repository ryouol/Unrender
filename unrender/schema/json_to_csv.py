"""Convert validated ChartData into a CSV string.

Single-series  -> two columns: <x_label>, <y_label>
Multi-series   -> wide format: <x_label>, <series1>, <series2>, ...
Pie            -> two columns: category, value

Multi-series alignment is by x label/position across series, preserving the
order x values first appear.
"""

from __future__ import annotations

import csv
import io
from typing import List

from unrender.schema.chart_schema import ChartData, x_key


def chart_to_csv(data: ChartData) -> str:
    """Render ChartData to a CSV string (with header row)."""
    buf = io.StringIO()
    writer = csv.writer(buf)

    x_label = (data.x_axis.label if data.x_axis else None) or "x"
    y_label = (data.y_axis.label if data.y_axis else None) or "value"

    if data.chart_type == "pie":
        writer.writerow(["category", "value"])
        for s in data.series:
            for p in s.points:
                writer.writerow([x_key(p.x), p.y])
        return buf.getvalue()

    if len(data.series) <= 1:
        writer.writerow([x_label, y_label])
        if data.series:
            for p in data.series[0].points:
                writer.writerow([x_key(p.x), p.y])
        return buf.getvalue()

    # Multi-series wide format. Collect x order from first appearance.
    x_order: List[str] = []
    seen = set()
    per_series = []
    for s in data.series:
        mapping = {}
        for p in s.points:
            k = x_key(p.x)
            mapping[k] = p.y
            if k not in seen:
                seen.add(k)
                x_order.append(k)
        per_series.append(mapping)

    headers = [x_label] + [s.name or f"series_{i+1}" for i, s in enumerate(data.series)]
    writer.writerow(headers)
    for k in x_order:
        writer.writerow([k] + [per_series[i].get(k, "") for i in range(len(data.series))])
    return buf.getvalue()
