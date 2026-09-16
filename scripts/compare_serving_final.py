"""Assess complete common300 coverage before permitting a scheduler quality claim."""

import argparse
import json
from pathlib import Path

from unrender.serving.benchmark import check_split
from unrender.serving.report import summarize


def evidence(root, phase):
    folder = root / phase
    rows = [json.loads(line) for line in (folder / "predictions.jsonl").read_text().splitlines()]
    expected = set(
        json.loads(
            (
                Path(__file__).resolve().parents[1] / "unrender/eval/subsets/common300.json"
            ).read_text()
        )["ids"]
    )
    ids = [row["id"] for row in rows]
    complete = set(ids) == expected and len(ids) == 300
    if complete:
        check_split(ids, final=True)
    run = json.loads((folder / "run.json").read_text())
    summary = summarize(rows, max(row["finished_s"] for row in rows))
    return {
        "run_status": json.loads((root / "progress.json").read_text()),
        "expected_inputs": 300,
        "recorded_responses": len(rows),
        "uncompleted_ids": sorted(expected - set(ids)),
        "complete_coverage": complete,
        "summary": summary,
        "score_scope": "full common300"
        if complete
        else "partial only; not a final quality baseline",
        "workload_sha256": run["workload_sha256"],
        "manifest": run["manifest"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    before, after = evidence(args.before, "final-before"), evidence(args.after, "final-after")
    differences = {
        k: [before["manifest"].get(k), after["manifest"].get(k)]
        for k in set(before["manifest"]) | set(after["manifest"])
        if before["manifest"].get(k) != after["manifest"].get(k)
    }
    comparable = (
        differences == {"max_num_seqs": [1, 16]}
        and before["workload_sha256"] == after["workload_sha256"]
    )
    complete = before["complete_coverage"] and after["complete_coverage"]
    delta = (
        after["summary"]["numeric_accuracy_failures_as_misses"]["cell_accuracy_exact"]
        - before["summary"]["numeric_accuracy_failures_as_misses"]["cell_accuracy_exact"]
        if complete and comparable
        else None
    )
    approved = bool(
        delta is not None
        and delta >= -0.01
        and before["summary"]["failures"] == after["summary"]["failures"] == 0
        and after["summary"]["strict_schema_success"] >= before["summary"]["strict_schema_success"]
    )
    result = {
        "before": before,
        "after": after,
        "manifest_differences": differences,
        "same_model_precision_workload": comparable,
        "physical_gpu_note": (
            "Separate H100 devices; primary performance comparison uses one physical H100."
        ),
        "cell_accuracy_exact_delta": delta,
        "promotion_approved": approved,
        "decision": "Eligible scheduler candidate"
        if approved
        else "Retain existing production provider; quality gate not established",
        "uncompleted_note": (
            "Missing inputs are not silently dropped. An interrupted run cannot "
            "establish the final quality baseline; its in-flight attempt count "
            "may be unavailable in older runner output."
        ),
    }
    args.output.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "same_model_precision_workload",
                    "cell_accuracy_exact_delta",
                    "promotion_approved",
                    "decision",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
