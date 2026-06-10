"""The canonical extraction prompt.

CRITICAL: this exact string is used in three places — training targets, the
frontier-model eval harness, and production inference. If it drifts between
them, your benchmark numbers stop being comparable. Import it; never retype it.
"""

from unrender.schema.chart_schema import CHART_TYPES

EXTRACTION_PROMPT = """You are given a chart image. Extract the EXACT underlying data from the chart.

Return strict JSON only, matching this schema:
{
  "chart_type": "{TYPES}",
  "title": string or null,
  "x_axis": {"label": string or null, "unit": string or null},
  "y_axis": {"label": string or null, "unit": string or null},
  "series": [
    {
      "name": string or null,
      "points": [{"x": string or number, "y": number}]
    }
  ]
}

Rules:
- If exact values are printed on the chart, use them. Otherwise estimate each value from the axis scale.
- One object in "series" per data series (one for a single-series chart, one per legend entry otherwise).
- For pie charts, use a single series whose points are {category, value}.
- Do not describe the chart. Do not include markdown fences or any explanation.
- Return JSON only.""".replace("{TYPES}", " | ".join(CHART_TYPES))
