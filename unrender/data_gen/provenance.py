"""Immutable generation receipts and byte verification for current synthetic data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

from matplotlib import font_manager, ft2font

from unrender.data_gen.chart_specs import _FONTS, TARGET_CONTRACT, ChartSpec
from unrender.io_utils import read_jsonl
from unrender.schema.chart_schema import canonical_json

GENERATION_CONTRACT = "synthetic-generation-v1"
SPLIT_CONTRACT = "synthetic-split-v1"
ROOT = Path(__file__).resolve().parents[2]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()


def recipe(**parameters) -> dict:
    fonts = {}
    for family in _FONTS:
        for weight in ("normal", "bold"):
            path = Path(
                font_manager.findfont(font_manager.FontProperties(family=family, weight=weight))
            )
            fonts[f"{family}:{weight}"] = {
                "filename": path.name,
                "sha256": digest(path.read_bytes()),
            }
    return {
        "contract": GENERATION_CONTRACT,
        "target_contract": TARGET_CONTRACT,
        "parameters": parameters,
        "sources": {
            name: digest((ROOT / name).read_bytes())
            for name in (
                "unrender/data_gen/chart_specs.py",
                "unrender/data_gen/render.py",
                "unrender/data_gen/augment.py",
                "unrender/data_gen/generate.py",
                "unrender/data_gen/provenance.py",
                "unrender/schema/chart_schema.py",
            )
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
            "libraries": {
                name: importlib.metadata.version(name) for name in ("matplotlib", "numpy", "Pillow")
            },
            "freetype": ft2font.__freetype_version__,
            "fonts": fonts,
            "matplotlib_style": "library defaults plus per-spec font and theme",
        },
    }


def artifact_path(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("generated artifact path must stay inside its dataset")
    return path


def verify_dataset(root: Path) -> tuple[dict, list[dict]]:
    receipt = json.loads((root / "generation.json").read_text())
    if receipt.get("status") != "complete":
        raise ValueError("generation is incomplete; create a fresh dataset directory")
    recipe_value = receipt["recipe"]
    recipe_hash = digest(json_bytes(recipe_value))
    if (
        recipe_value.get("contract") != GENERATION_CONTRACT
        or recipe_value.get("target_contract") != TARGET_CONTRACT
        or receipt["recipe_sha256"] != recipe_hash
    ):
        raise ValueError("generation recipe/contract mismatch")
    manifest_bytes = (root / "manifest.jsonl").read_bytes()
    if digest(manifest_bytes) != receipt["manifest_sha256"]:
        raise ValueError("generation manifest changed")
    rows = [json.loads(line) for line in manifest_bytes.splitlines() if line.strip()]
    parameters = recipe_value["parameters"]
    expected = [
        f"{i:07d}"
        for i in range(parameters["start_index"], parameters["start_index"] + parameters["n"])
    ]
    if len(rows) != len(expected) or sorted(row["id"] for row in rows) != sorted(expected):
        raise ValueError("generation coverage mismatch")
    for row in rows:
        if row["target_contract"] != TARGET_CONTRACT or row["recipe_sha256"] != recipe_hash:
            raise ValueError("mixed generation contracts or recipes")
        for kind in ("image", "label"):
            suffix = "png" if kind == "image" else "json"
            if row[kind] != f"{kind}s/{row['id']}.{suffix}":
                raise ValueError("artifact does not match its generated ID")
            path = artifact_path(root, row[kind])
            if digest(path.read_bytes()) != row[f"{kind}_sha256"]:
                raise ValueError(f"generated {kind} changed: {row['id']}")
        spec = ChartSpec(**row["spec"])
        if digest(canonical_json(spec.to_chart_data()).encode()) != row["label_sha256"]:
            raise ValueError("recorded specification does not match target")
        if row["chart_type"] != spec.chart_type or row["labels_shown"] != spec.value_labels_shown:
            raise ValueError("recorded specification does not match slice metadata")
    return receipt, rows


def read_split(path: str | Path) -> list[dict]:
    """Read a chat split, verifying current synthetic receipts before use.

    External/manual chat datasets have their own review requirements. Current
    synthetic splits require the entire dataset bundle; copying only JSONL drops
    evidence and is rejected. This is integrity checking, not annotation review.
    """
    path = Path(path)
    rows = read_jsonl(path)
    root = path.parent
    generated = any("generation" in (row.get("meta") or {}) for row in rows)
    if (
        not generated
        and not (root / "generation.json").exists()
        and not (root / "split.json").exists()
    ):
        return rows
    generation, manifest = verify_dataset(root)
    receipt = json.loads((root / "split.json").read_bytes())
    if (
        receipt.get("status") != "complete"
        or receipt.get("contract") != SPLIT_CONTRACT
        or receipt.get("recipe_sha256") != generation["recipe_sha256"]
        or receipt.get("manifest_sha256") != generation["manifest_sha256"]
        or set(receipt.get("files", {})) != {"train.jsonl", "val.jsonl", "test.jsonl"}
        or path.name not in receipt["files"]
    ):
        raise ValueError("split receipt is incomplete or does not match generation")
    by_id = {entry["id"]: entry for entry in manifest}
    seen = set()
    verified_rows = {}
    for name, record in receipt["files"].items():
        raw = (root / name).read_bytes()
        if digest(raw) != record["sha256"]:
            raise ValueError(f"split changed: {name}")
        members = [json.loads(line) for line in raw.splitlines() if line.strip()]
        verified_rows[name] = members
        if len(members) != record["rows"]:
            raise ValueError("split row count mismatch")
        for row in members:
            image_path = row["images"][0]
            entry = by_id.get(Path(image_path).stem)
            if entry is None or entry["id"] in seen or row["images"] != [entry["image"]]:
                raise ValueError("split coverage or image identity mismatch")
            seen.add(entry["id"])
            expected_meta = {
                key: entry[key]
                for key in ("labels_shown", "chart_type", "augmented", "visual_review")
            }
            expected_meta["generation"] = {
                key: entry[key]
                for key in ("target_contract", "recipe_sha256", "image_sha256", "label_sha256")
            }
            messages = row["messages"]
            if (
                row.get("meta") != expected_meta
                or len(messages) != 2
                or messages[0]["role"] != "user"
                or messages[1]["role"] != "assistant"
                or digest(messages[0]["content"].encode()) != receipt["prompt_sha256"]
                or digest(messages[1]["content"].encode()) != entry["label_sha256"]
            ):
                raise ValueError("split target, prompt or provenance mismatch")
    if seen != set(by_id):
        raise ValueError("split coverage is incomplete")
    return verified_rows[path.name]
