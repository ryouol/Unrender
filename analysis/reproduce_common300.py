"""Verify and rescore the committed historical evidence, without network or GPU."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from unrender.eval.metrics import METRIC_VERSION, semantic_errors
from unrender.eval.paired_bootstrap import compare
from unrender.eval.score import score_rows, validate_rows
from unrender.io_utils import fingerprint_ids
from unrender.schema.chart_schema import ChartData, data_table_signature, x_key
from unrender.schema.validate import PARSER_VERSION, strict_json

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "release/common300-evidence"
ARMS = ("base", "fair", "numeric")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_bytes(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if sha256(raw) != expected:
        raise ValueError(f"evidence hash mismatch: {path.name}")
    return raw


def table(raw: str) -> ChartData:
    result = ChartData.model_validate(strict_json(raw), strict=True)
    if semantic_errors(result):
        raise ValueError("invalid evidence ground truth")
    return result


def numerical_table_signature(data: ChartData) -> str:
    """Full SHA-256, ignoring chart family, series names/order and point order.

    Keep x identities, series grouping, multiplicity and exact parsed y values.
    This is an additional conservative overlap check, not a scorer identity rule.
    """
    series = sorted(
        sorted((x_key(p.x), str(Decimal(str(p.y)).normalize())) for p in s.points)
        for s in data.series
    )
    return sha256(json.dumps(series, ensure_ascii=False, separators=(",", ":")).encode())


def load_evidence(bundle: Path = BUNDLE, root: Path = ROOT) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest["format"] != "common300-evidence-v1":
        raise ValueError("unsupported evidence format")
    if set(manifest["artifacts"]) != {*ARMS, "train_v0", "train_v1", "test_v1"}:
        raise ValueError("incomplete evidence manifest")
    rows = {}
    for key, item in manifest["artifacts"].items():
        path = bundle / item["file"]
        compressed = checked_bytes(path, item["compressed_sha256"])
        raw = gzip.decompress(compressed)
        if sha256(raw) != item["sha256"] or len(raw) != item["bytes"]:
            raise ValueError(f"uncompressed evidence mismatch: {key}")
        rows[key] = [strict_json(line) for line in raw.decode().splitlines()]
        if len(rows[key]) != item["rows"]:
            raise ValueError(f"evidence row count mismatch: {key}")
    metadata = {
        key: json.loads(checked_bytes(bundle / item["file"], item["sha256"]))
        for key, item in manifest["models"].items()
    }
    fixed = {
        key: json.loads(checked_bytes(root / manifest[key]["file"], manifest[key]["sha256"]))
        for key in ("subset", "modal_split")
    }
    return {"manifest": manifest, "rows": rows, "metadata": metadata, **fixed}


def audit_evidence(evidence: dict) -> dict:
    rows = evidence["rows"]
    ids = evidence["subset"]["ids"]
    if len(ids) != 300 or len(set(ids)) != 300:
        raise ValueError("common300 must contain exactly 300 unique IDs")
    splits = {}
    for name in ("train_v0", "train_v1", "test_v1"):
        split = {}
        for row in rows[name]:
            rid = Path(row["images"][0]).stem
            if rid in split:
                raise ValueError(f"duplicate split ID: {name}/{rid}")
            split[rid] = (table(row["messages"][1]["content"]), row["meta"])
        splits[name] = split
    frozen = evidence["modal_split"]
    for key, split_name in (("train_ids", "train_v1"), ("test_ids", "test_v1")):
        if set(frozen[key]) != set(splits[split_name]):
            raise ValueError(f"frozen Modal split mismatch: {split_name}")
    if set(ids) - splits["test_v1"].keys():
        raise ValueError("missing common300 truth")
    if set(splits["train_v1"]) & set(splits["test_v1"]):
        raise ValueError("Modal train/test ID overlap")
    for arm in ARMS:
        predictions = validate_rows(rows[arm], ids)
        if len(rows[arm]) != len(ids):
            raise ValueError(f"unexpected predictions outside common300: {arm}")
        meta = evidence["metadata"][arm]
        if (
            meta["subset_fp"] != fingerprint_ids(ids)
            or meta["dataset_fp"] != fingerprint_ids(splits["test_v1"])
            or meta["n_subset"] != len(ids)
        ):
            raise ValueError(f"historical metadata coverage mismatch: {arm}")
        for row in predictions:
            truth, truth_meta = splits["test_v1"][row["id"]]
            if table(row["gt"]) != truth or row["meta"] != truth_meta:
                raise ValueError(f"prediction truth mismatch: {arm}/{row['id']}")
    overlap = {}
    for name in ("train_v0", "train_v1"):
        entry = {"rows": len(splits[name]), "id_overlap": len(set(ids) & splits[name].keys())}
        for label, signature in (
            ("historical_table_signature", data_table_signature),
            ("numerical_table_sha256", numerical_table_signature),
        ):
            train = {signature(value[0]) for value in splits[name].values()}
            entry[label] = sorted(
                rid for rid in ids if signature(splits["test_v1"][rid][0]) in train
            )
        overlap[name] = entry
    return {"n": len(ids), "truth_verified_arms": list(ARMS), "training_overlap": overlap}


def reproduce(bundle: Path = BUNDLE, root: Path = ROOT) -> dict:
    evidence = load_evidence(bundle, root)
    audit = audit_evidence(evidence)
    if any(
        item[key]
        for item in audit["training_overlap"].values()
        for key in ("historical_table_signature", "numerical_table_sha256")
    ):
        raise ValueError("common300 training-table overlap; investigate before comparison")
    rows, ids = evidence["rows"], evidence["subset"]["ids"]
    return {
        "metric_version": METRIC_VERSION,
        "parser_version": PARSER_VERSION,
        "audit": audit,
        "ladder": {arm: score_rows(rows[arm], 0.05, only_ids=ids) for arm in ARMS},
        "fair_vs_base": compare(rows["fair"], rows["base"], ids),
        "numeric_vs_fair": compare(rows["numeric"], rows["fair"], ids),
        "manifest_sha256": sha256((bundle / "manifest.json").read_bytes()),
        "source_hashes": {
            name: sha256((root / name).read_bytes())
            for name in (
                "analysis/reproduce_common300.py",
                "unrender/eval/metrics.py",
                "unrender/eval/dataset.py",
                "unrender/eval/ledger.py",
                "unrender/io_utils.py",
                "unrender/eval/score.py",
                "unrender/eval/paired_bootstrap.py",
                "unrender/schema/chart_schema.py",
                "unrender/schema/validate.py",
            )
        },
        "attempt_coverage": "historical_saved_rows_only; no dispatch ledger or finish reasons",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/common300-reproduced.json")
    args = parser.parse_args()
    result = reproduce()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Verified all 900 saved predictions, test truth and both training splits.")
    for arm, report in result["ladder"].items():
        print(f"{arm}: semantic cell F1 = {report['metrics']['cell_f1']:.2%}")
    for label in ("fair_vs_base", "numeric_vs_fair"):
        comparison = result[label]
        lo, hi = comparison["ci95_pp"]
        print(f"{label}: {comparison['gap_pp']:+.2f} pp; paired 95% CI [{lo:+.2f}, {hi:+.2f}]")
    print(f"Full report: {args.out}")


if __name__ == "__main__":
    main()
