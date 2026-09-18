"""Serving summaries using the current semantic scorer and one acceptance contract."""

from __future__ import annotations

import math
from collections import Counter

from unrender.eval.metrics import aggregate, score_sample
from unrender.schema.chart_schema import ChartData
from unrender.serving.validity import CONTRACT, assess


def percentile(values: list[float], p: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def summarize(rows: list[dict], elapsed: float) -> dict:
    assessments = [
        assess(row.get("raw") or "", row.get("finish_reason"), row.get("stream_complete", False))
        for row in rows
    ]
    successful = [
        row
        for row, (state, _) in zip(rows, assessments, strict=True)
        if row["status"] == "ok" and not row.get("error") and state["accepted"]
    ]
    scored = []
    for row, (_, chart) in zip(rows, assessments, strict=True):
        if row["status"] != "ok" or row.get("error"):
            chart = None
        scored.append(
            score_sample(
                chart,
                ChartData.model_validate_json(row["gt"]),
                tol=0.05,
                labels_shown=row.get("meta", {}).get("labels_shown"),
            )
        )
    correct = sum(sample["table_within_tolerance"] for sample in scored)
    tokens = [row["usage"].get("completion_tokens") for row in successful]
    complete_tokens = all(isinstance(n, int) and n >= 0 for n in tokens)
    summary = {
        "acceptance_contract": CONTRACT,
        "requests": len(rows),
        "valid": len(successful),
        "elapsed_s": elapsed,
        "failures": len(rows) - len(successful),
        "errors_by_code": dict(
            Counter(
                row.get("error")
                or (row["status"] if row["status"] != "ok" else "model_output_invalid")
                for row in rows
                if row not in successful
            )
        ),
        "valid_requests_per_s": len(successful) / elapsed if elapsed else None,
        "output_tokens_per_s": sum(tokens) / elapsed
        if tokens and complete_tokens and elapsed
        else None,
        "output_token_usage_coverage": sum(n is not None for n in tokens),
        "json_parse_success": sum(state["raw_json"] for state, _ in assessments),
        "strict_schema_success": sum(state["strict_schema"] for state, _ in assessments),
        "raw_semantic_success": sum(state["semantic"] for state, _ in assessments),
        "completed_streams": sum(state["completed"] for state, _ in assessments),
        "correct_tables": correct,
        "correct_tables_per_s": correct / elapsed if elapsed else None,
        "quality_failures_as_misses": aggregate(scored),
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
