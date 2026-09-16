"""Serving summaries with explicit failure denominators and unchanged numeric scorer."""

from __future__ import annotations

import json
import math
from collections import Counter

from unrender.eval.metrics import aggregate, score_sample
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import parse_chart_json


def percentile(values: list[float], p: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def reject_nonfinite(value: str):
    raise ValueError(f"Non-JSON constant: {value}")


def schema_valid(raw: str) -> bool:
    try:
        ChartData.model_validate_json(raw, strict=True)
        return True
    except ValueError:
        return False


def summarize(rows: list[dict], elapsed: float) -> dict:
    successful = [row for row in rows if row["status"] == "ok"]
    scored = []
    parsed = 0
    for row in rows:
        try:
            json.loads(row["raw"], parse_constant=reject_nonfinite)
            parsed += 1
        except (ValueError, TypeError):
            pass
        # Every failed request is a miss here, even if a partial response can be repaired.
        # The historical standalone scorer remains unchanged (and excludes infra errors).
        chart, _ = parse_chart_json(row["raw"]) if row["status"] == "ok" else (None, [])
        scored.append(
            score_sample(
                chart,
                ChartData.model_validate_json(row["gt"]),
                tol=0.05,
                labels_shown=row.get("meta", {}).get("labels_shown"),
            )
        )
    tokens = [row["usage"].get("completion_tokens") for row in successful]
    complete_tokens = all(isinstance(n, int) and n >= 0 for n in tokens)
    summary = {
        "requests": len(rows),
        "valid": len(successful),
        "elapsed_s": elapsed,
        "failures": len(rows) - len(successful),
        "errors_by_code": dict(
            Counter(row.get("error") or row["status"] for row in rows if row["status"] != "ok")
        ),
        "valid_requests_per_s": len(successful) / elapsed if elapsed else None,
        "output_tokens_per_s": sum(tokens) / elapsed
        if tokens and complete_tokens and elapsed
        else None,
        "output_token_usage_coverage": sum(n is not None for n in tokens),
        "json_parse_success": parsed,
        "strict_schema_success": sum(schema_valid(row["raw"]) for row in rows),
        "numeric_accuracy_failures_as_misses": aggregate(scored),
        "p95_interpretation": "pilot_only" if len(successful) < 200 else "repeat_runs_required",
    }
    for name, values in {
        "ttft_s": [row["ttft_s"] for row in successful if row["ttft_s"] is not None],
        "response_s": [row["response_s"] for row in successful],
        "all_attempt_response_s": [row["response_s"] for row in rows],
        "queue_s": [
            row["server_timings"]["queue_s"] for row in rows if "queue_s" in row["server_timings"]
        ],
        "output_tokens": [n for n in tokens if n is not None],
    }.items():
        summary[f"n_{name}"] = len(values)
        summary[f"p50_{name}"] = percentile(values, 0.5)
        summary[f"p95_{name}"] = percentile(values, 0.95)
    return summary
