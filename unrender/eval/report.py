"""Cross-provider comparison from saved predictions — the headline artifact.

Reads each provider's predictions.jsonl directly (so it always reflects the
current scorer). The headline cell-accuracy tables are computed on the
INTERSECTION of charts where EVERY provider produced an ok prediction (A6), so N
is identical across rows — an apples-to-apples accuracy comparison. Reliability
(schema-valid, model_invalid, infra-excluded) is reported separately on each
provider's full set. Both 5% and 2% tolerance tracks are shown (A5).

    python -m unrender.eval.report --reports outputs/eval_reports --out outputs/eval_reports/COMPARISON.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from unrender.eval.score import TRACKS, row_status, score_rows
from unrender.io_utils import read_jsonl


def _load_providers(report_paths: List[str]) -> List[dict]:
    """Each provider: {name, rows, ids_ok}. Found by predictions.jsonl files."""
    pred_files, seen = [], set()
    for pth in report_paths:
        p = Path(pth)
        files = sorted(p.rglob("predictions.jsonl")) if p.is_dir() else [p.parent / "predictions.jsonl"]
        for f in files:
            if f.exists() and f.resolve() not in seen:
                seen.add(f.resolve())
                pred_files.append(f)
    providers = []
    for f in pred_files:
        rows = read_jsonl(f)
        if not rows:
            continue
        mp = f.parent / "meta.json"
        meta = json.loads(mp.read_text()) if mp.exists() else {}
        name = f"{meta.get('provider') or '?'}:{meta.get('model') or f.parent.name}"
        providers.append({
            "name": name, "rows": rows,
            "ids_ok": {r["id"] for r in rows if row_status(r) == "ok"},
        })
    return providers


def _pct(x) -> str:
    return f"{x*100:.1f}%" if x is not None else "—"


def _cell_table(providers: List[dict], tol: float, ids: set) -> str:
    cols = ["Model", "Cell (all)", "Labeled", "Label-free", "Gap (lab−free)", "Exact-chart"]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    rows = []
    for p in providers:
        r = score_rows(p["rows"], tol, only_ids=ids)
        m, sl = r["metrics"], r["slices"]
        lab = sl["labeled"].get("cell_accuracy")
        free = sl["label_free"].get("cell_accuracy")
        gap = f"{(lab-free)*100:+.1f} pts" if lab is not None and free is not None else "—"
        rows.append((free if free is not None else -1, [
            p["name"], _pct(m.get("cell_accuracy")), _pct(lab), _pct(free), gap,
            _pct(m.get("chart_exact_rate")),
        ]))
    for _, cells in sorted(rows, key=lambda t: t[0], reverse=True):
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _reliability_table(providers: List[dict]) -> str:
    cols = ["Model", "Schema-valid", "model_invalid", "infra-excluded", "N (full attempts)"]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for p in providers:
        full = score_rows(p["rows"], 0.05)
        m = full["metrics"]
        n_full = m["n"] + full["n_infra_error"]
        lines.append("| " + " | ".join([
            p["name"], _pct(m.get("schema_valid_rate")),
            str(full["n_model_invalid"]), str(full["n_infra_error"]), str(n_full),
        ]) + " |")
    return "\n".join(lines)


def _by_type_table(providers: List[dict], ids: set) -> str:
    scored = {p["name"]: score_rows(p["rows"], 0.05, only_ids=ids)["slices"]["by_chart_type"] for p in providers}
    types = sorted({ct for s in scored.values() for ct in s})
    if not types:
        return ""
    header = ["Model (label-free cell, 5%)"] + types
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for p in providers:
        by_ct = scored[p["name"]]
        cells = [p["name"]]
        for ct in types:
            lf = by_ct.get(ct, {}).get("label_free", {})
            cells.append(f"{_pct(lf['cell_accuracy'])} (n={lf['n']})" if lf.get("n") else "—")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build(report_paths: List[str], out: str, title: str = "Unrender — chart-to-data extraction") -> str:
    providers = _load_providers(report_paths)
    if not providers:
        text = f"# {title}\n\n_No predictions found._\n"
    else:
        ids = set.intersection(*[p["ids_ok"] for p in providers])  # charts ok for EVERY provider
        text = (
            f"# {title}\n\n"
            f"Headline cell-accuracy tables are on the **intersection of charts where all "
            f"{len(providers)} providers produced an ok prediction: N = {len(ids)}** (identical across rows). "
            "Cell = data point within tolerance; label-free pies scored on proportions. "
            "Reliability (schema-valid / invalid / rate-limit-excluded) is on each provider's full set.\n\n"
        )
        for t in TRACKS:
            kind = "headline" if t == TRACKS[0] else "strict"
            text += f"## Cell accuracy @ {t:.0%} tolerance ({kind}, N={len(ids)})\n\n" + _cell_table(providers, t, ids) + "\n\n"
        text += "## Reliability (full attempt set)\n\n" + _reliability_table(providers) + "\n\n"
        text += "## Label-free cell accuracy by chart type (5%, intersection)\n\n" + _by_type_table(providers, ids) + "\n"

    if out:
        Path(out).write_text(text)
        print(f"Wrote {out}")
    print("\n" + text)
    return text


def main():
    p = argparse.ArgumentParser(description="Build the cross-provider comparison markdown.")
    p.add_argument("--reports", nargs="+", default=["outputs/eval_reports"])
    p.add_argument("--out", default="outputs/eval_reports/COMPARISON.md")
    p.add_argument("--title", default="Unrender — chart-to-data extraction")
    args = p.parse_args()
    build(args.reports, args.out, args.title)


if __name__ == "__main__":
    main()
