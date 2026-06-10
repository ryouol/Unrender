"""Combine report.json files into the headline markdown comparison.

The aggregate number is nearly useless on its own — the SLICE is the deliverable.
This emits two tables:
  1. Cell accuracy split labeled vs label-free, with the gap (labeled - free).
     A large gap is the wedge: the skill frontier models lack.
  2. Label-free cell accuracy per chart type — where the wedge is widest.

    python -m unrender.eval.report --reports outputs/eval_reports --out outputs/eval_reports/COMPARISON.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List


def _find_reports(paths: List[str]) -> List[Path]:
    found, seen = [], set()
    for pth in paths:
        p = Path(pth)
        candidates = sorted(p.rglob("report.json")) if p.is_dir() else [p]
        for c in candidates:
            rc = c.resolve()
            if rc not in seen:  # dedup overlapping args
                seen.add(rc)
                found.append(c)
    return found


def _pct(x) -> str:
    return f"{x * 100:.1f}%" if x is not None else "—"


def _load(report_paths: List[str]) -> List[dict]:
    reports = []
    for rp in _find_reports(report_paths):
        try:
            data = json.loads(rp.read_text())
        except Exception:
            continue
        if data.get("metrics", {}).get("n"):
            data["_name"] = f"{data.get('provider') or '?'}:{data.get('model') or rp.parent.name}"
            reports.append(data)
    return reports


def _headline_table(reports: List[dict]) -> str:
    cols = ["Model", "Cell acc (all)", "Cell acc (labeled)", "Cell acc (label-free)",
            "Gap (lab−free)", "Exact chart", "Schema ok", "N"]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for d in reports:
        m, sl = d["metrics"], d.get("slices", {})
        lab = sl.get("labeled", {}).get("cell_accuracy")
        free = sl.get("label_free", {}).get("cell_accuracy")
        gap = f"{(lab - free) * 100:+.1f} pts" if lab is not None and free is not None else "—"
        lines.append("| " + " | ".join([
            d["_name"], _pct(m.get("cell_accuracy")), _pct(lab), _pct(free), gap,
            _pct(m.get("chart_exact_rate")), _pct(m.get("schema_valid_rate")), str(m.get("n", 0)),
        ]) + " |")
    return "\n".join(lines)


def _by_type_table(reports: List[dict]) -> str:
    types = sorted({ct for d in reports for ct in d.get("slices", {}).get("by_chart_type", {})})
    if not types:
        return ""
    header = ["Model (label-free cell acc)"] + types
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for d in reports:
        by_ct = d.get("slices", {}).get("by_chart_type", {})
        cells = [d["_name"]]
        for ct in types:
            lf = by_ct.get(ct, {}).get("label_free", {})
            cells.append(_pct(lf["cell_accuracy"]) + f" (n={lf['n']})" if lf.get("n") else "—")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build(report_paths: List[str], out: str) -> str:
    reports = _load(report_paths)
    # Best label-free cell accuracy first — that's the metric the project targets.
    reports.sort(key=lambda d: d.get("slices", {}).get("label_free", {}).get("cell_accuracy", -1), reverse=True)

    if not reports:
        table = "# Unrender — chart-to-data extraction\n\n_No scored reports found._\n"
    else:
        tol = reports[0].get("tol")
        table = (
            "# Unrender — chart-to-data extraction\n\n"
            f"Cell = data point recovered within {tol:.0%} relative error. "
            "The **label-free** column is the one that matters: when values aren't printed, "
            "the model must read geometry against the axis scale.\n\n"
            "## Cell accuracy: labeled vs label-free\n\n" + _headline_table(reports) + "\n\n"
            "## Label-free cell accuracy by chart type\n\n" + _by_type_table(reports) + "\n"
        )

    if out:
        Path(out).write_text(table)
        print(f"Wrote {out}")
    print("\n" + table)
    return table


def main():
    p = argparse.ArgumentParser(description="Aggregate report.json files into a sliced markdown table.")
    p.add_argument("--reports", nargs="+", default=["outputs/eval_reports"],
                   help="report.json files or dirs to search")
    p.add_argument("--out", default="outputs/eval_reports/COMPARISON.md", help="output markdown path")
    args = p.parse_args()
    build(args.reports, args.out)


if __name__ == "__main__":
    main()
