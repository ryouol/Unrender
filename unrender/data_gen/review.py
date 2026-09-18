"""Source-review packets bound to generated targets and observed processor inputs.

Receipts record a person's attestation; hashes cannot prove reviewer independence
or correctness. This gate does not validate the training collator's preprocessing.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from unrender.data_gen.provenance import (
    artifact_path,
    digest,
    json_bytes,
    read_split,
    verify_dataset,
)

CONTRACT = "synthetic-source-review-v1"
VALUE_TOLERANCE = {"relative": 0.05, "absolute_floor": 1e-6}
CHECKS = (
    "metadata_visible",
    "target_values_correct",
    "scale_units_correct",
    "native_readable",
    "full_input_readable",
    "capped_input_readable",
    "target_precision_supported",
)
PROTOCOL = """# Source and numeric-recoverability review

Inspect the source image, exact target and both actual processor rasters for every
chart. Mark eligible only when all target metadata is visible, source values and
units are correct, category/series associations are unambiguous, and the numeric
precision required by the target is supported at both budgets. Check blur, glyph
contrast, clipping, line/leader association, logarithmic scales, multipliers and
rounding. This protocol uses the current cell scorer's tolerance:
absolute error <= max(0.05 * abs(target), 0.000001). It does not require exact
transcription of unprinted trailing digits. For unlabeled charts, quantify the
plausible reading interval in notes; its uncertainty must fit inside that
tolerance for every value. Do not approve unsupported subpixel precision. A pie
without printed values does not identify an absolute total.

No font-size cutoff or native bounding-box result is automatic approval. Record
uncertain examples as pending; use stress or unreadable for unsuitable examples
and explain why. Do not remove them from the packet. No bulk approval is provided.
Record the reviewer's identity and timezone-aware time for each eligible row.

This is source review, not a benchmark eligibility rate, proof of independent
review, GPU parity or approval of the training collator. Final evaluation needs
independent annotation/recoverability review, frozen scope and a separate holdout.
"""


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[0-9]{7}$")
    decision: Literal["pending", "eligible", "stress", "unreadable"]
    reviewer: str
    reviewed_at: str
    notes: str
    checks: dict[str, bool]


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract: Literal["synthetic-source-review-v1"]
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: list[Decision]


def _audit_rows(audit: dict, generation: dict, manifest: list[dict], name: str) -> dict:
    if (
        audit.get("contract") != "qwen-image-budget-audit-v1"
        or audit.get("processor_class") != "Qwen2VLImageProcessorFast"
        or audit.get("device") != "cpu"
        or audit.get("datasets", {}).get(name) != generation
    ):
        raise ValueError("processor audit does not match the generated bundle")
    rows = [row for row in audit["rows"] if row["dataset"] == name]
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {row["id"] for row in manifest}:
        raise ValueError("processor audit coverage differs from the generated bundle")
    for entry in manifest:
        row = by_id[entry["id"]]
        if row["image_sha256"] != entry["image_sha256"]:
            raise ValueError("processor audit used a different image")
        if set(row["budgets"]) != {"full", "512"}:
            raise ValueError("both full and capped processor inputs are required")
        for budget, details in row["budgets"].items():
            if details.get("reconstructed_pixels_equal_captured_resize") is not True:
                raise ValueError("processor raster reconstruction was not verified")
            if budget == "512" and not 0 < details["image_tokens"] <= 512:
                raise ValueError("invalid capped image budget")
    return by_id


def _packet(root: Path) -> tuple[dict, dict, list[dict]]:
    generation, manifest = verify_dataset(root)
    packet_path = root / "review/packet.json"
    packet = json.loads(packet_path.read_bytes())
    if (
        packet.get("contract") != CONTRACT
        or packet.get("value_tolerance") != VALUE_TOLERANCE
        or packet.get("generation") != generation
        or packet.get("split_sha256") != digest((root / "split.json").read_bytes())
        or packet.get("protocol_sha256") != digest((root / "review/protocol.md").read_bytes())
    ):
        raise ValueError("source-review packet changed or belongs to a different bundle")
    raw = (root / "review/processor-audit.json").read_bytes()
    if digest(raw) != packet["processor_audit_sha256"]:
        raise ValueError("processor audit changed since packet creation")
    audit = json.loads(raw)
    if (
        digest((root / "review/preprocessor_config.json").read_bytes())
        != audit["processor_config_sha256"]
    ):
        raise ValueError("reviewed processor configuration changed")
    by_id = _audit_rows(audit, generation, manifest, packet["dataset_name"])
    for row in by_id.values():
        for details in row["budgets"].values():
            path = artifact_path(root / "review/processor", details["raster"])
            if digest(path.read_bytes()) != details["raster_sha256"]:
                raise ValueError("reviewed processor raster changed")
    return packet, generation, manifest


def require_source_review(split_path: str | Path) -> dict:
    """Reject the whole requested split if any source row is not explicitly eligible.

    Low-level read_split/load_records remain diagnostic readers. Actual training
    and its CPU preflight call this gate before consuming any training/val row.
    """
    path = Path(split_path)
    rows = read_split(path)
    if not rows:
        raise ValueError("training source split is empty")
    if any("generation" not in (row.get("meta") or {}) for row in rows):
        raise ValueError("training requires a reviewed current generated bundle")
    try:
        packet, _, manifest = _packet(path.parent)
        raw = (path.parent / "review/review.json").read_bytes()
        review = Review.model_validate_json(raw, strict=True)
        if review.packet_sha256 != digest(json_bytes(packet)):
            raise ValueError("review decisions belong to a different packet")
        decisions = {row.id: row for row in review.rows}
        if len(decisions) != len(review.rows) or set(decisions) != {r["id"] for r in manifest}:
            raise ValueError("review decisions must retain every generated ID exactly once")
        for decision in review.rows:
            if set(decision.checks) != set(CHECKS):
                raise ValueError("review checklist differs from the required protocol")
            if decision.decision == "eligible":
                time = datetime.fromisoformat(decision.reviewed_at.replace("Z", "+00:00"))
                if (
                    time.tzinfo is None
                    or not decision.reviewer.strip()
                    or not decision.notes.strip()
                    or not all(decision.checks.values())
                ):
                    raise ValueError("eligible rows require identified, dated, complete review")
        failed = [
            Path(r["images"][0]).stem
            for r in rows
            if decisions[Path(r["images"][0]).stem].decision != "eligible"
        ]
        if failed:
            raise ValueError(
                f"{len(failed)} noneligible source rows; no rows filtered: {failed[:8]}"
            )
        return {
            "split_sha256": digest(path.read_bytes()),
            "packet_sha256": review.packet_sha256,
            "review_sha256": digest(raw),
            "source_rows": len(rows),
            "processor_config_sha256": json.loads(
                (path.parent / "review/processor-audit.json").read_bytes()
            )["processor_config_sha256"],
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"training source review failed for {path.name}: {exc}") from exc


def prepare(root: Path, audit_dir: Path, processor_dir: Path) -> Path:
    """Create a complete pending packet; never approve, filter or overwrite sources."""
    generation, manifest = verify_dataset(root)
    read_split(root / "train.jsonl")  # verify complete split membership as well
    raw = (audit_dir / "report.json").read_bytes()
    audit = json.loads(raw)
    by_id = _audit_rows(audit, generation, manifest, root.name)
    config = (processor_dir / "preprocessor_config.json").read_bytes()
    if digest(config) != audit["processor_config_sha256"]:
        raise ValueError("processor configuration differs from the audit")
    # Validate all raster bytes before reserving the output directory.
    rasters = {}
    for row in by_id.values():
        for details in row["budgets"].values():
            source = artifact_path(audit_dir, details["raster"])
            content = source.read_bytes()
            if digest(content) != details["raster_sha256"]:
                raise ValueError("processor raster changed since the audit")
            rasters[details["raster"]] = content
    target = root / "review"
    target.mkdir()  # exclusive; partial packet is never treated as complete
    for name, content in rasters.items():
        path = artifact_path(target / "processor", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (target / "processor-audit.json").write_bytes(raw)
    (target / "preprocessor_config.json").write_bytes(config)
    (target / "protocol.md").write_text(PROTOCOL)
    packet = {
        "contract": CONTRACT,
        "value_tolerance": VALUE_TOLERANCE,
        "dataset_name": root.name,
        "generation": generation,
        "split_sha256": digest((root / "split.json").read_bytes()),
        "processor_audit_sha256": digest(raw),
        "protocol_sha256": digest(PROTOCOL.encode()),
    }
    decisions = {
        "contract": CONTRACT,
        "packet_sha256": digest(json_bytes(packet)),
        "rows": [
            {
                "id": row["id"],
                "decision": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
                "checks": dict.fromkeys(CHECKS, False),
            }
            for row in manifest
        ],
    }
    (target / "review.json").write_bytes(json_bytes(decisions))
    cards = []
    for row in manifest:
        images = [("Generated source", "../" + row["image"])] + [
            ("Processor: " + name, "processor/" + details["raster"])
            for name, details in by_id[row["id"]]["budgets"].items()
        ]
        figures = "".join(
            f"<figure><figcaption>{escape(label)} · click for original size</figcaption>"
            f'<a href="{escape(name, quote=True)}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="{escape(name, quote=True)}" '
            f'alt="{escape(label)}"></a></figure>'
            for label, name in images
        )
        raw_truth = (root / row["label"]).read_text()
        target_data = json.loads(raw_truth)
        series = target_data["series"]
        headers = "".join(f"<th>{escape(s['name'] or 'Value')}</th>" for s in series)
        cells = "".join(
            f"<tr><th>{escape(point['x'])}</th>"
            + "".join(f"<td>{s['points'][i]['y']}</td>" for s in series)
            + "</tr>"
            for i, point in enumerate(series[0]["points"])
        )
        table = (
            f'<div class="table"><table><tr><th>Category</th>{headers}</tr>{cells}</table></div>'
        )
        truth = escape(raw_truth)
        cards.append(
            f"<article><h2>{row['id']} · {escape(row['chart_type'])}</h2>"
            f'<div class="images">{figures}</div><details><summary>Exact target</summary>'
            f"{table}<details><summary>Full target JSON, including metadata</summary>"
            f"<pre>{truth}</pre></details></details></article>"
        )
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Chart source review</title><style>"
        "body{font:16px system-ui;max-width:1600px;margin:auto;padding:24px;color:#18232c}"
        "article{border-top:1px solid #ccc;padding:24px 0}.images{display:flex;flex-wrap:wrap}"
        "figure{margin:12px;flex:1 1 300px;min-width:0}img{max-width:100%;height:auto}"
        "figcaption{font-weight:600;margin-bottom:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        ".table{overflow:auto;margin:16px 0}table{border-collapse:collapse}"
        "th,td{border:1px solid #ddd;padding:8px 16px;text-align:left}"
        "</style><h1>Chart source review</h1>"
        "<p>All decisions start pending. This static page does not reflect later edits "
        "to review.json. Inspect images at original size when necessary. "
        'Read <a href="protocol.md">the review protocol</a>, then record each decision in '
        '<a href="review.json">review.json</a>. Keep all IDs. This page is a static review '
        "packet; it does not save or approve decisions.</p>" + "".join(cards) + "</html>"
    )
    (target / "index.html").write_text(html)
    (target / "packet.json").write_bytes(json_bytes(packet))  # completion marker written last
    return target


def require_training_sources(train_paths: list[str], val_paths: list[str], data_root: str) -> dict:
    if not train_paths:
        raise ValueError("explicit reviewed training splits are required")
    receipts = {}
    for kind, paths in (("train", train_paths), ("val", val_paths)):
        for name in paths:
            path = (Path(data_root) / name).resolve()
            if path.name != f"{kind}.jsonl" or str(path) in receipts:
                raise ValueError("training source roles must be distinct train/val splits")
            receipts[str(path)] = require_source_review(path)
    return receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--processor", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.dataset, args.audit, args.processor))


if __name__ == "__main__":
    main()
