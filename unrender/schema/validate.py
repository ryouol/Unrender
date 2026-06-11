"""Parse + deterministically repair model output into a valid ChartData.

IMPORTANT: repair here is pure string surgery (strip fences, extract the JSON
object, fix trailing commas). It must NEVER call another model — if a frontier
model "helped" repair the output, you could no longer claim your model did the
extraction. Keep this honest.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from pydantic import ValidationError

from unrender.schema.chart_schema import ChartData

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_POINTS_SYNONYMS = ("data", "values")           # series-level -> "points"
_POINT_X_SYNONYMS = ("category", "label", "name")  # point-level -> "x"
_POINT_Y_SYNONYMS = ("value", "amount")            # point-level -> "y"


def _normalize_keys(obj):
    """Map common key synonyms onto the schema's names before validation (A2).

    Pure, model-neutral leniency applied identically to every provider:
      series : data/values        -> points
      point  : category/label/name -> x ;  value/amount -> y
    'name' maps to x only INSIDE a point — a series' own 'name' is preserved.
    Each rename is guarded so it never clobbers a canonical key already present.
    """
    if not isinstance(obj, dict):
        return obj
    series = obj.get("series")
    if isinstance(series, list):
        for s in series:
            if not isinstance(s, dict):
                continue
            for syn in _POINTS_SYNONYMS:
                if syn in s and "points" not in s:
                    s["points"] = s.pop(syn)
            pts = s.get("points")
            if isinstance(pts, list):
                for p in pts:
                    if not isinstance(p, dict):
                        continue
                    for syn in _POINT_X_SYNONYMS:
                        if syn in p and "x" not in p:
                            p["x"] = p.pop(syn)
                    for syn in _POINT_Y_SYNONYMS:
                        if syn in p and "y" not in p:
                            p["y"] = p.pop(syn)
    return obj


def repair_json(raw: str) -> str:
    """Best-effort cleanup of common LLM JSON formatting slips.

    Handles markdown fences, leading/trailing prose around the object, and
    trailing commas. Returns a candidate JSON string (not guaranteed to parse).
    """
    text = raw.strip()

    # Strip a leading/trailing ```json ... ``` fence if present.
    text = _FENCE_RE.sub("", text).strip()

    # Grab the outermost {...} span — drops any prose before/after the object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    # Remove trailing commas before } or ].
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def parse_chart_json(raw: str) -> Tuple[Optional[ChartData], List[str]]:
    """Parse raw model output into a ChartData.

    Tries the raw string first, then one deterministic repair pass. Returns
    (ChartData or None, list of error strings). An empty error list means the
    first parse succeeded with no repair needed.
    """
    errors: List[str] = []

    for attempt, candidate in enumerate((raw, repair_json(raw))):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as e:
            errors.append(f"json_decode[{attempt}]: {e}")
            continue
        obj = _normalize_keys(obj)  # A2: map key synonyms, same leniency for all providers
        try:
            return ChartData.model_validate(obj), ([] if attempt == 0 else errors)
        except ValidationError as e:
            errors.append(f"schema[{attempt}]: {e.error_count()} error(s)")

    return None, errors
