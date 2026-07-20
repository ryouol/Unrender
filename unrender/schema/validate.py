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
_PY_LITERAL_RE = re.compile(r"\b(None|True|False)\b")
_PY_LITERALS = {"None": "null", "True": "true", "False": "false"}

_POINTS_SYNONYMS = ("data", "values")           # series-level -> "points"
_POINT_X_SYNONYMS = ("category", "label", "name")  # point-level -> "x"
_POINT_Y_SYNONYMS = ("value", "amount")            # point-level -> "y"

# Numeric-string coercion (P0 free win): a single y like "1,200" / "1.2B" / "12%"
# used to fail float validation and zero the ENTIRE chart. These are printed-number
# formats, so translate them — same leniency for every provider, never GT-aware.
_SUFFIX_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
_GROUPED_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_SUFFIX_NUM_RE = re.compile(r"([-+]?[\d.,]*\.?\d+)\s*([kKmMbBtT])")
_CURRENCY_RE = re.compile(r"^[\s$€£¥]+")


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


def _scan_json(text: str):
    """One pass over `text` tracking JSON string state and the open {/[ stack.
    Returns (stack, in_string, index_of_unterminated_string_open_quote)."""
    stack, in_str, esc, str_start = [], False, False, -1
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str, str_start = True, i
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    return stack, in_str, str_start


def _balance_json(text: str) -> str:
    """Close a TRUNCATED JSON object (max-token cutoff): drop an unterminated
    trailing string / partial literal / dangling ',' or ':', then append the
    missing closers. A no-op on already-balanced text."""
    stack, in_str, str_start = _scan_json(text)
    if in_str:  # cut the unterminated string off entirely
        text = text[:str_start]
        stack, _, _ = _scan_json(text)
    if not stack:
        return text
    t = text.rstrip()
    frag = re.search(r"[A-Za-z]+$", t)
    if frag and any(w.startswith(frag.group(0)) for w in ("true", "false", "null")) \
            and frag.group(0) not in ("true", "false", "null"):
        t = t[: frag.start()].rstrip()  # partial literal like "fal"
    t = re.sub(r"(\d)[.eE+-]+$", r"\1", t)  # partial number like "12." or "1e"
    if t.endswith(":"):
        t += " null"
    elif t.endswith(","):
        t = t[:-1]
    stack, _, _ = _scan_json(t)
    return t + "".join("}" if c == "{" else "]" for c in reversed(stack))


def repair_json(raw: str) -> str:
    """Best-effort cleanup of common LLM JSON formatting slips.

    Handles markdown fences, leading/trailing prose around the object, trailing
    commas, Python literals (None/True/False), fully-single-quoted JSON, and
    truncated output (unbalanced braces from a max-token cutoff). Returns a
    candidate JSON string (not guaranteed to parse).
    """
    text = raw.strip()

    # Strip a leading/trailing ```json ... ``` fence if present.
    text = _FENCE_RE.sub("", text).strip()

    # Grab the outermost {...} span — drops any prose before/after the object.
    # Truncated output may have no closing brace at all: fall back to "from the
    # first { to the end" and let _balance_json close it.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        # A truncated tail AFTER the last } (e.g. an unfinished sibling key)
        # still balances; prefer the span only when it is itself balanced.
        stack, in_str, _ = _scan_json(candidate)
        text = candidate if (not stack and not in_str) else text[start:]
    elif start != -1:
        text = text[start:]

    # Python-repr literals -> JSON (outside of strings this is what models mean;
    # inside a label string "True" is rare and unaffected by scoring anyway).
    text = _PY_LITERAL_RE.sub(lambda m: _PY_LITERALS[m.group(0)], text)

    # A fully single-quoted object (no double quotes at all) -> double quotes.
    if '"' not in text and "'" in text:
        text = text.replace("'", '"')

    # Close truncation, then remove trailing commas before } or ].
    text = _balance_json(text)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def _coerce_num(v):
    """A printed-number string -> float ("1,200", "1.2B", "12%", "$3,400").
    Returns None when the value is unusable as a number. Ints/floats pass
    through; everything else (None, dicts, prose) -> None."""
    if isinstance(v, bool):  # bool is an int subclass; a bool y is not a number
        return None
    if isinstance(v, (int, float)):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip().replace("−", "-").replace("–", "-")  # unicode minus/dash
    s = _CURRENCY_RE.sub("", s)
    if s.endswith("%"):
        s = s[:-1].strip()
    mult = 1.0
    m = _SUFFIX_NUM_RE.fullmatch(s)
    if m:
        s, mult = m.group(1), _SUFFIX_MULT[m.group(2).lower()]
    if _GROUPED_NUM_RE.fullmatch(s):
        s = s.replace(",", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


def _coerce_points(obj) -> int:
    """Normalize point y-values in place; DROP unusable points (y is null /
    prose / non-scalar, or the point is malformed / missing x or y — e.g. the
    half-point left behind by a truncation cut) so one bad point no longer
    zeroes the whole chart. The scorer already counts a dropped point as a
    miss: its GT point simply has no match. Returns how many were dropped."""
    dropped = 0
    if not isinstance(obj, dict) or not isinstance(obj.get("series"), list):
        return 0
    for s in obj["series"]:
        pts = s.get("points") if isinstance(s, dict) else None
        if not isinstance(pts, list):
            continue
        kept = []
        for p in pts:
            if not isinstance(p, dict) or "x" not in p or "y" not in p:
                dropped += 1
                continue
            y = _coerce_num(p["y"])
            if y is None:
                dropped += 1
                continue
            p["y"] = y
            kept.append(p)
        s["points"] = kept
    return dropped


def _unwrap(obj):
    """{"chart": {...actual ChartData...}} -> the inner object. Only fires when
    the top level clearly isn't ChartData and exactly one child clearly is."""
    if isinstance(obj, dict) and "chart_type" not in obj and "series" not in obj:
        inner = [v for v in obj.values()
                 if isinstance(v, dict) and ("chart_type" in v or "series" in v)]
        if len(inner) == 1:
            return inner[0]
    return obj


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
        obj = _unwrap(obj)          # {"chart": {...}} wrappers
        obj = _normalize_keys(obj)  # A2: map key synonyms, same leniency for all providers
        dropped = _coerce_points(obj)  # "1,200"/"1.2B"/"12%" -> numbers; unusable y -> point dropped
        if dropped:
            errors.append(f"coerce[{attempt}]: dropped {dropped} point(s) with unusable y")
        try:
            return ChartData.model_validate(obj), ([] if attempt == 0 and not dropped else errors)
        except ValidationError as e:
            errors.append(f"schema[{attempt}]: {e.error_count()} error(s)")

    return None, errors
