"""Build the versioned scoreboard from saved artifacts, without GPU/API calls.

Missing artifacts are errors. Incomplete frontier runs expose coverage only,
never a success-selected accuracy comparison. Historical RESULTS.md is immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from unrender.eval.metrics import METRIC_VERSION
from unrender.eval.paired_bootstrap import compare, verdict
from unrender.eval.score import score_rows, validate_rows
from unrender.io_utils import read_jsonl
from unrender.schema.validate import PARSER_VERSION

ROOT = Path(__file__).resolve().parents[1]
TOL = 0.05
COMMON300 = json.loads((ROOT / "unrender/eval/subsets/common300.json").read_text())["ids"]
COMMON = {
    "base 4B (pinned)": "eval_v1__Qwen3-VL-4B-Instruct__common300",
    "table-LoRA (fair)": "eval_v1__qwen3vl4b-table-fair__common300",
    "table-LoRA + numeric-loss": "eval_v1__qwen3vl4b-table-numloss__common300",
}
FRONTIER = {
    "claude-fable-5": "anthropic__claude-fable-5",
    "gpt-5.5": "openai__gpt-5.5",
    "gemini-3.1-pro": "gemini__gemini-3.1-pro-preview",
}
REAL = {
    "earlier table-LoRA": "eval_real_v0__qwen3vl4b-lora",
    "base 4B": "eval_real_v0__Qwen3-VL-4B-Instruct",
    "gemini-3.1-pro": "eval_real_v0__gemini",
}


def build(model_root: Path | None = None, frontier_root: Path | None = None):
    model_root = model_root or ROOT / "outputs/modal"
    frontier_root = frontier_root or ROOT / "outputs/eval_v1"
    sources = {}

    def load(root, directory):
        path = root / directory / "predictions.jsonl"
        if not path.is_file():
            raise ValueError(f"missing evidence: {path}; no scoreboard was written")
        rows = validate_rows(read_jsonl(path))
        if not rows:
            raise ValueError(f"empty evidence: {path}")
        sources[directory] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(rows),
        }
        return rows

    common = {name: load(model_root, directory) for name, directory in COMMON.items()}
    ladder = {name: score_rows(rows, TOL, only_ids=COMMON300) for name, rows in common.items()}
    base = common["base 4B (pinned)"]
    fair = common["table-LoRA (fair)"]
    numeric = common["table-LoRA + numeric-loss"]
    improvement = compare(fair, base, COMMON300, tol=TOL)
    passed, reasons = verdict(improvement)
    frontier = {}
    for name, directory in FRONTIER.items():
        rows = load(frontier_root, directory)
        missing = sorted(set(COMMON300) - {str(row["id"]) for row in rows})
        entry = {
            "n_expected": len(COMMON300),
            "n_recorded": len(COMMON300) - len(missing),
            "missing_ids": missing,
            "complete": not missing,
        }
        if not missing:
            entry["scores"] = score_rows(rows, TOL, only_ids=COMMON300)
            entry["paired_fair_minus_frontier"] = compare(fair, rows, COMMON300, tol=TOL)
        frontier[name] = entry
    return {
        "metric_version": METRIC_VERSION,
        "parser_version": PARSER_VERSION,
        "metric": "cell_f1",
        "tol": TOL,
        "common300_n": len(COMMON300),
        "ladder": ladder,
        "fair_vs_base": {**improvement, "passed": passed, "reasons": reasons},
        "numeric_vs_fair": compare(numeric, fair, COMMON300, tol=TOL),
        "frontier": frontier,
        "real_v0_review": {
            "status": "withheld_pending_visual_metadata_audit",
            "reason": (
                "The fetcher constructs titles, axes and series names; these need "
                "image-level verification before semantic quality claims."
            ),
        },
        "real_v0": {
            name: score_rows(load(model_root, directory), TOL) for name, directory in REAL.items()
        },
        "sources": sources,
    }


def render(result: dict) -> str:
    lines = [
        "# Versioned model evaluation",
        "",
        f"Scorer `{result['metric_version']}`; semantic cell F1 at {result['tol']:.0%} tolerance.",
        "All recorded failures remain in the denominator. Historical scores are not comparable.",
        "Common300 is a reused synthetic regression set, not a fresh real-world holdout.",
        "Exact-chart percentages exclude unlabeled pies; denominators are in the JSON report.",
        "",
    ]
    for title, section in (("Common300", "ladder"),):
        lines += [
            f"## {title}",
            "",
            "| Model | N | Precision | Recall | F1 | Raw semantic validity | Exact charts |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, report in result[section].items():
            metrics = report["metrics"]
            values = [metrics[k] for k in ("cell_precision", "cell_recall", "cell_f1")]
            values += [report["raw_validity"]["raw_semantic_valid"], metrics["chart_exact_rate"]]
            lines.append(
                f"| {name} | {metrics['n']} | " + " | ".join(f"{v:.2%}" for v in values) + " |"
            )
        lines += [""]
    for label, key in (
        ("Fair minus base", "fair_vs_base"),
        ("Numeric loss minus fair", "numeric_vs_fair"),
    ):
        value = result[key]
        lines += [
            f"{label}: **{value['gap_pp']:+.2f} points**; paired 95% interval "
            f"[{value['ci95_pp'][0]:+.2f}, {value['ci95_pp'][1]:+.2f}].",
            "",
        ]
    lines += [
        "## Frontier coverage",
        "",
        "| Model | Recorded / expected | Comparison |",
        "|---|---:|---|",
    ]
    for name, entry in result["frontier"].items():
        comparison = (
            "Complete; paired scores in JSON"
            if entry["complete"]
            else "INCOMPLETE — no paired quality claim"
        )
        lines.append(f"| {name} | {entry['n_recorded']} / {entry['n_expected']} | {comparison} |")
    lines += [
        "",
        "Real_v0 semantic quality claims are WITHHELD pending a visual metadata audit.",
        "Its fetcher synthesizes titles, axis labels and series names; source CSV values alone",
        "do not verify those fields against the image. Strict diagnostic scores remain in JSON.",
        "The set contains only eight public line charts and evaluates the earlier LoRA.",
        "It cannot establish generalization or frontier parity. Contamination is a hypothesis,",
        "not a demonstrated cause. Raw/repaired validity, all outcomes, family slices,",
        "conditional metrics, bootstrap settings and artifact hashes are in scoreboard.json.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=ROOT / "outputs/modal")
    parser.add_argument("--frontier-root", type=Path, default=ROOT / "outputs/eval_v1")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/evaluation-v2")
    args = parser.parse_args()
    result = build(args.model_root, args.frontier_root)
    text = render(result)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scoreboard.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "RESULTS.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
