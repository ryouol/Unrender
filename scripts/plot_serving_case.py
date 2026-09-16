"""Plot saved serving summaries (requires matplotlib; performs no inference)."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    runs = json.loads(args.summary.read_text())["runs"]
    concurrency = [1, 2, 4, 8, 16]
    pilot = [runs[f"saturation-c{c}"] for c in concurrency]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
    for ax, field, title, unit in zip(
        axes[:2],
        ["valid_requests_per_s", "p95_response_s"],
        ["Throughput plateaus", "Queueing raises latency"],
        ["Successful requests/s", "p95 completion (seconds)"],
        strict=True,
    ):
        ax.plot(concurrency, [r[field] for r in pilot], marker="o", color="#226b93")
        ax.set(xlabel="Client concurrency", ylabel=unit, title=title, xticks=concurrency)
        ax.grid(alpha=0.2)
    axes[0].set_ylim(0, 0.8)
    axes[1].set_ylim(bottom=0)
    names = ["intervention-before"] + [f"intervention-after-{i}" for i in (1, 2, 3)]
    axes[2].bar(
        ["Before", "After 1", "After 2", "After 3"],
        [runs[n]["valid_requests_per_s"] for n in names],
        color=["#718096"] + ["#226b93"] * 3,
    )
    axes[2].set(ylabel="Successful requests/s", title="Only sequence limit changed: 1 → 16")
    fig.suptitle("Unrender / H100 / BF16 — serialized control and batching ablation", fontsize=14)
    fig.supxlabel(
        "Left: 16-request pilots, sequence limit 1. "
        "Right: 210 requests/run, client concurrency 16. Repeated 23-chart tuning set.",
        fontsize=9,
    )
    fig.savefig(args.output, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
