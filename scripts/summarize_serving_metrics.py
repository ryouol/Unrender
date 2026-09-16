"""Reduce saved Prometheus samples and GPU readings; never substitutes capacity for occupancy."""

import argparse
import json
import re
from pathlib import Path

GAUGES = ("num_requests_running", "num_requests_waiting", "kv_cache_usage_perc")
COUNTERS = (
    "num_preemptions_total",
    "request_queue_time_seconds_sum",
    "request_queue_time_seconds_count",
)


def values(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r"vllm:([a-z_]+)(?:\{[^}]*\})? ([0-9.eE+\-]+)$", line)
        if match:
            key, value = match.groups()
            result[key] = result.get(key, 0) + float(value)
    return result


def summarize(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    samples = [values(row.get("prometheus", "")) for row in rows]
    out = {"samples": len(rows), "scrape_errors": sum("error" in row for row in rows)}
    for key in GAUGES:
        vals = [sample[key] for sample in samples if key in sample]
        out[key + "_max"] = max(vals) if vals else None
    for key in COUNTERS:
        vals = [sample[key] for sample in samples if key in sample]
        out[key + "_observed_delta"] = vals[-1] - vals[0] if vals else None
    gpu = [
        list(map(float, row["gpu_csv"].splitlines()[0].split(",")))
        for row in rows
        if row.get("gpu_csv")
    ]
    if gpu:
        out.update(
            gpu_used_mib_max=max(row[0] for row in gpu),
            gpu_free_mib_min=min(row[1] for row in gpu),
            gpu_utilization_pct_mean=sum(row[2] for row in gpu) / len(gpu),
        )
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    root = parser.parse_args().directory
    result = {p.parent.name: summarize(p) for p in sorted(root.glob("*/metrics.jsonl"))}
    (root / "metrics-summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
