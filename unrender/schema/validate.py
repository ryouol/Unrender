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
        try:
            return ChartData.model_validate(obj), ([] if attempt == 0 else errors)
        except ValidationError as e:
            errors.append(f"schema[{attempt}]: {e.error_count()} error(s)")

    return None, errors
