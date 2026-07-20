"""Compact GEOMETRY-program target string — what the geometry-LoRA learns to emit.

`to_target(geom)` serializes the captured geometry (data_gen/geometry.py) into a
compact JSON the model is trained to produce; `from_target(text)` parses it back
into the dict `eval/geometry_decode.decode_geometry` consumes. Fractions are
emitted at 3 decimals — R000 showed that precision recovers ~98% of matched-bucket
values within 5%, and it keeps the target short (long targets are what triggered
the dropped-mark / repetition failures in the table-only LoRA).

Short keys keep the sequence compact: ct=chart_type, ax=value axis, box=plot bbox,
t=ticks [[frac,value]], s=series [{n:name, m:marks}]. A mark is [x, frac] (bar/
point), [x, f_bot, f_top] (stacked segment), or [x, prop] (pie). The TABLE (x
labels + series names) is carried inside the marks, so one object holds both the
geometry and the table.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

FRAC_DECIMALS = 3


def _r(v: float) -> float:
    return round(float(v), FRAC_DECIMALS)


def to_target(geom: Dict) -> str:
    ct = geom["chart_type"]
    if ct == "pie":
        s = geom["series"][0]
        obj = {"ct": "pie", "s": [{"n": s.get("name"),
                                   "m": [[m["x"], round(float(m["prop"]), 4)] for m in s["marks"]]}]}
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    series = []
    for s in geom["series"]:
        marks = []
        for m in s["marks"]:
            if m["kind"] == "stack_seg":
                marks.append([m["x"], _r(m["f_bot"]), _r(m["f_top"])])
            else:
                marks.append([m["x"], _r(m["f"])])
        series.append({"n": s.get("name"), "m": marks})
    obj = {
        "ct": ct,
        "ax": geom["value_axis"],
        "box": [_r(v) for v in geom["plot_bbox"]],
        "t": [[_r(f), v] for f, v in geom["ticks"]],
        "s": series,
    }
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def from_target(text: str) -> Optional[Dict]:
    """Parse a (possibly model-emitted) target string back to a decode-ready geom
    dict. Tolerant of leading/trailing prose/fences like the JSON repair. Returns
    None if unparseable."""
    s = text.strip()
    if "```" in s:  # strip code fences
        parts = s.split("```")
        s = max(parts, key=len)
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
    lo, hi = s.find("{"), s.rfind("}")
    if lo == -1 or hi == -1:
        return None
    try:
        obj = json.loads(s[lo:hi + 1])
    except Exception:
        return None

    # Everything past the JSON load is tolerant: a model may emit a non-numeric
    # fraction, a placeholder, or a ragged mark — drop the bad element rather than
    # crash the whole scorer (a malformed row must count as one miss, not abort).
    def _f(x):
        return float(x)  # raises on junk; callers below skip the offending item

    try:
        ct = obj.get("ct")
        if ct == "pie":
            s0 = (obj.get("s") or [{}])[0]
            marks = []
            for m in s0.get("m", []):
                try:
                    if len(m) >= 2:
                        marks.append({"x": m[0], "prop": _f(m[1]), "kind": "pie"})
                except (TypeError, ValueError):
                    continue
            return {"chart_type": "pie", "value_axis": None, "ticks": [],
                    "series": [{"name": s0.get("n"), "marks": marks}]}

        series = []
        for s0 in obj.get("s", []):
            marks = []
            for m in s0.get("m", []):
                try:
                    if len(m) == 3:
                        marks.append({"x": m[0], "kind": "stack_seg", "f_bot": _f(m[1]), "f_top": _f(m[2])})
                    elif len(m) == 2:
                        marks.append({"x": m[0], "kind": "mark", "f": _f(m[1])})
                except (TypeError, ValueError):
                    continue
            series.append({"name": s0.get("n"), "marks": marks})
        ticks = []
        for t in obj.get("t", []):
            try:
                if len(t) == 2 and t[1] is not None:
                    ticks.append([_f(t[0]), _f(t[1])])
            except (TypeError, ValueError):
                continue
        if not isinstance(ct, str):
            return None
        return {"chart_type": ct, "value_axis": obj.get("ax"),
                "plot_bbox": obj.get("box"), "ticks": ticks, "series": series}
    except Exception:
        return None
