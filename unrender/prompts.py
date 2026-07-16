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


# v2 prompt (FRONTIER_PLAN P1): the same schema with two extra rules targeting
# the measured failure modes — suffix/comma-formatted numbers (which used to
# invalidate whole charts) and paraphrased x labels (killed by fuzzy matching).
# COMPARABILITY RULE: numbers are only comparable within one prompt version.
# Use this for synthetic_v2 training and any re-baselined comparison set; never
# mix v1-prompt and v2-prompt results in the same table.
EXTRACTION_PROMPT_V2 = EXTRACTION_PROMPT.replace(
    "- Do not describe the chart.",
    """- Write every value as a plain number: no thousands separators, no % or currency signs, and expand K/M/B/T suffixes (an axis reading 1.2B means 1200000000).
- Copy each x/category label EXACTLY as printed on the chart.
- Emit exactly one point per category shown; never add or drop categories.
- Do not describe the chart.""")
if "1200000000" not in EXTRACTION_PROMPT_V2:  # the .replace anchor must never drift silently
    raise RuntimeError("EXTRACTION_PROMPT_V2 composition failed")


# Geometry-supervision prompt (the "measure, don't guess" arm). The model emits a
# compact GEOMETRY PROGRAM — the plotting box, every value-axis tick paired with
# its printed value, and each mark's position — from which a deterministic
# pixel->value transform (eval/geometry_decode.py) computes the table. Same string
# used for the geometry-LoRA's training targets, eval, and inference (the
# train=eval=inference invariant, now for the geometry arm). The exact JSON shape
# must match data_gen/geometry_target.to_target().
GEOMETRY_PROMPT = """You are given a chart image. Do NOT guess the values. Instead, report the chart's GEOMETRY so the values can be computed exactly from the axis scale.

Return strict JSON only, with these fields:
{
  "ct": "{TYPES}",
  "ax": "y" | "x",                 // which axis carries the values (y for most; x for horizontal_bar)
  "box": [x0, y0, x1, y1],         // the plotting-area rectangle, as fractions of the image (0=left/bottom, 1=right/top)
  "t": [[f, v], ...],              // EVERY value-axis tick: f = its position along the value axis as a fraction (0=bottom or left, 1=top or right); v = its printed number
  "s": [                           // one entry per data series, in legend order
    {"n": string or null,          // series name
     "m": [["x-label", f], ...]}   // one mark per category (left to right): f = the mark's position along the value axis as a fraction
  ]
}

Rules:
- For each bar: f is the fraction at the bar's END (its top, or right end for horizontal bars).
- For each line/scatter point: f is the fraction at the point.
- For STACKED bars, each mark is ["x-label", f_bottom, f_top] (the segment's two ends).
- For PIE charts, omit "ax"/"box"/"t"; each mark is ["x-label", proportion] where proportion is the slice's share of the whole (0-1).
- Report ticks and marks in the SAME fraction convention so the values are recoverable by linear interpolation between ticks.
- Do not include markdown fences or any explanation. Return JSON only.""".replace("{TYPES}", " | ".join(CHART_TYPES))
