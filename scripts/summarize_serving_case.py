"""Summarize saved GPU evidence without invoking a model or changing the scorer."""

import argparse
import hashlib
import json
from pathlib import Path

from unrender.serving.report import percentile, summarize


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    runs = {}
    for path in sorted(root.glob("*/summary.json")):
        saved = json.loads(path.read_text())
        predictions = path.parent / "predictions.jsonl"
        runs[path.parent.name] = (
            summarize(read_rows(predictions), saved["elapsed_s"]) if predictions.exists() else saved
        )
    comparison = {"runs": runs, "status": json.loads((root / "progress.json").read_text())}
    original = root / "existing-path.jsonl"
    reference = root / "tf-baseline/predictions.jsonl"
    if original.exists() and reference.exists():
        original_rows = read_rows(original)
        reference_rows = {row["id"]: row for row in read_rows(reference)}
        comparison["existing_path_vs_reference"] = {
            "requests": len(original_rows),
            "raw_exact_matches": sum(
                row["raw"] == reference_rows.get(row["id"], {}).get("raw") for row in original_rows
            ),
            "cold_first_request_s": original_rows[0]["elapsed_s"],
            "warm_p50_s": percentile([row["elapsed_s"] for row in original_rows[1:]], 0.5),
            "warm_p95_s": percentile([row["elapsed_s"] for row in original_rows[1:]], 0.95),
        }
    baseline = root / "vllm-baseline/predictions.jsonl"
    if baseline.exists() and reference.exists():
        reference_rows = {row["id"]: row for row in read_rows(reference)}
        vllm_rows = read_rows(baseline)
        comparison["runtime_comparability"] = {
            "matched_samples": sum(row["id"] in reference_rows for row in vllm_rows),
            "prompt_token_count_matches": sum(
                row["usage"].get("prompt_tokens") is not None
                and row["usage"].get("prompt_tokens")
                == reference_rows.get(row["id"], {}).get("usage", {}).get("prompt_tokens")
                for row in vllm_rows
            ),
            "raw_exact_matches": sum(
                row["raw"] == reference_rows.get(row["id"], {}).get("raw") for row in vllm_rows
            ),
            "limits": (
                "Token-count agreement is necessary evidence, not proof of identical pixel tensors."
            ),
        }
    before, after = runs.get("final-before"), runs.get("final-after")
    comparison["promotion"] = {"approved": False, "reason": "Complete final comparison unavailable"}
    if before and after:
        delta = (
            after["numeric_accuracy_failures_as_misses"]["cell_accuracy_exact"]
            - before["numeric_accuracy_failures_as_misses"]["cell_accuracy_exact"]
        )
        passed = (
            before["requests"] == after["requests"] == 300
            and before["failures"] == after["failures"] == 0
            and delta >= -0.01
            and after["strict_schema_success"] >= before["strict_schema_success"]
        )
        comparison["promotion"] = {
            "approved": passed,
            "cell_accuracy_exact_delta": delta,
            "reason": "Preregistered final quality gate",
            "scope": "scheduler only",
        }
    comparison["evidence_sha256"] = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.json"))
        if path.name != "case-summary.json"
    }
    (root / "case-summary.json").write_text(json.dumps(comparison, indent=2))
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
