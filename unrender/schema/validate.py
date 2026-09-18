"""Parse chart output without guessing, converting units, or dropping data.

Only complete JSON objects are recoverable. A formatting repair may remove an
outer prose/Markdown envelope or trailing commas outside strings. It may not
complete truncated tokens, rename keys, coerce printed quantities, unwrap another
schema, or select one of multiple objects. Diagnostics are fixed codes; they never
include model output, labels, or values.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from unrender.schema.chart_schema import CHART_TYPES, ChartData

PARSER_VERSION = "chart-json-v2"


class InvalidJSON(ValueError):
    """A JSON-level ambiguity which must not be repaired."""


def strict_json(raw: str) -> Any:
    """Reject duplicate keys and JavaScript nonfinite constants at every depth."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidJSON("duplicate_json_key")
            result[key] = value
        return result

    def constant(_value):
        raise InvalidJSON("nonfinite_json_constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _complete_object(text: str) -> str:
    """Extract one balanced object, respecting strings and escaped quotes.

    Return the unchanged input on an ambiguous envelope or incomplete structure;
    the JSON decoder then rejects it. No suffix of an unfinished table is lost.
    """
    start = text.find("{")
    if (
        start < 0
        or any(ch in text[:start] for ch in '{}[]"')
        or re.search(r"\d|\b(?:true|false|null|NaN|Infinity)\b", text[:start])
    ):
        return text
    stack: list[str] = []
    in_string = escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or stack.pop() != ("{" if char == "}" else "["):
                return text
            if not stack:
                # Multiple objects/arrays and unfinished sibling fields are not
                # prose. Do not choose the first apparently complete answer.
                suffix = text[index + 1 :]
                if (
                    any(ch in suffix for ch in '{}[]":,')
                    or re.search(r"\d", suffix)
                    or re.search(r"\b(?:true|false|null|NaN|Infinity)\b", suffix)
                ):
                    return text
                return text[start : index + 1]
    return text


def repair_json(raw: str) -> str:
    """Remove formatting only; leave incomplete or ambiguous data unparseable."""
    text = _complete_object(raw.strip())
    output: list[str] = []
    in_string = escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            output.append(char)
        elif char == ",":
            following = index + 1
            while following < len(text) and text[following].isspace():
                following += 1
            if following == len(text) or text[following] not in "}]":
                output.append(char)
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _canonical_fields(obj: Any) -> bool:
    """The schema's optional defaults are allowed; unknown fields are not."""

    def keys(value, allowed):
        return isinstance(value, dict) and not (value.keys() - allowed)

    if not keys(obj, {"chart_type", "title", "x_axis", "y_axis", "series"}):
        return False
    for axis in ("x_axis", "y_axis"):
        if axis in obj and not keys(obj[axis], {"label", "unit"}):
            return False
    if not isinstance(obj.get("series"), list) or not obj["series"]:
        return False
    for series in obj["series"]:
        if not keys(series, {"name", "points"}):
            return False
        if not isinstance(series.get("points"), list) or not series["points"]:
            return False
        for point in series["points"]:
            if not keys(point, {"x", "y"}) or point.keys() != {"x", "y"}:
                return False
    return obj.get("chart_type") in CHART_TYPES


def parse_chart_json(raw: str) -> tuple[ChartData | None, list[str]]:
    """Return the whole table or no table, plus privacy-safe diagnostic codes.

    Empty diagnostics means the raw response satisfies the parser contract.
    ``syntax_repaired`` identifies a complete table recovered without changing
    its labels, values, units, keys, or point count. Rejection never returns a
    partial chart disguised as a complete one.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, ["empty_output"]
    errors: list[str] = []
    try:
        obj = strict_json(raw)
    except InvalidJSON as exc:
        return None, [str(exc)]
    except (ValueError, RecursionError):
        candidate = repair_json(raw)
        if candidate == raw.strip():
            return None, ["invalid_json"]
        try:
            obj = strict_json(candidate)
        except InvalidJSON as exc:
            return None, [str(exc)]
        except (ValueError, RecursionError):
            return None, ["invalid_json"]
        errors.append("syntax_repaired")
    if not _canonical_fields(obj):
        return None, [*errors, "invalid_chart_structure"]
    try:
        return ChartData.model_validate(obj, strict=True), errors
    except (ValidationError, RecursionError):
        return None, [*errors, "invalid_chart_values"]
