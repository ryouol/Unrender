"""CPU-only acceptance audit of saved outputs under the current parser.

Historical acceptance counts are recorded receipts, not another parser mode.
No inference calls, repaired-output primary credit, or success-only subsets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from analysis.scoreboard import COMMON, COMMON300
from unrender.eval.score import row_status, score_rows, validate_rows
from unrender.io_utils import read_jsonl
from unrender.schema.validate import PARSER_VERSION, parse_chart_json


def audit(root: Path) -> dict:
    results = {}
    for model, directory in COMMON.items():
        source = root / directory / "predictions.jsonl"
        rows = validate_rows(read_jsonl(str(source)), COMMON300)
        diagnostics = Counter()
        accepted = repaired = 0
        for row in rows:
            if row_status(row) == "infra_error":
                diagnostics["infrastructure_failure"] += 1
                continue
            parsed, errors = parse_chart_json(row.get("raw") or "")
            accepted += parsed is not None
            repaired += parsed is not None and bool(errors)
            diagnostics.update(errors)
        scoring = score_rows(rows, 0.05)
        results[model] = {
            "prediction_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "n": len(rows),
            "accepted": accepted,
            "syntax_repaired": repaired,
            "rejected": len(rows) - accepted,
            "diagnostics": dict(sorted(diagnostics.items())),
            "primary_cell_f1": scoring["metrics"]["cell_f1"],
            "raw_semantic_valid_rate": scoring["raw_validity"]["raw_semantic_valid"],
        }
    return {
        "parser_version": PARSER_VERSION,
        "scope": "common300 saved synthetic outputs; no new generation or stop-reason evidence",
        "source_sha256": hashlib.sha256(
            Path("unrender/schema/validate.py").read_bytes()
        ).hexdigest(),
        "models": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.model_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
