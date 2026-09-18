"""Inspect actual pinned Qwen image-processor rasters on CPU, without model weights.

Run in a separate environment with the candidate torch/torchvision/transformers/
Pillow versions. The processor configuration is a local recovered release artifact.
This measures resizing, not model accuracy, GPU parity, or human recoverability.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import platform
from pathlib import Path


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()


def _file(root: Path, name: str) -> bytes:
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact escaped its dataset")
    return path.read_bytes()


def _inputs(root: Path):
    generation = json.loads((root / "generation.json").read_bytes())
    if (
        generation.get("status") != "complete"
        or generation["recipe"]["contract"] != "synthetic-generation-v2"
    ):
        raise ValueError("a completed layout-aware generation bundle is required")
    if sha(canonical(generation["recipe"])) != generation["recipe_sha256"]:
        raise ValueError("generation recipe changed")
    raw = (root / "manifest.jsonl").read_bytes()
    if sha(raw) != generation["manifest_sha256"]:
        raise ValueError("manifest changed")
    rows = [json.loads(line) for line in raw.splitlines()]
    parameters = generation["recipe"]["parameters"]
    expected = {
        f"{i:07d}"
        for i in range(parameters["start_index"], parameters["start_index"] + parameters["n"])
    }
    if len(rows) != len(expected) or {r["id"] for r in rows} != expected:
        raise ValueError("generation coverage changed")
    for row in rows:
        if row["recipe_sha256"] != generation["recipe_sha256"]:
            raise ValueError("mixed generation recipes")
        for kind in ("image", "label"):
            if sha(_file(root, row[kind])) != row[f"{kind}_sha256"]:
                raise ValueError(f"{kind} changed")
    return generation, rows


def reconstruct_first_frame(encoded, grid, processor):
    """Invert the pinned processor's patch permutation and normalization.

    Comparing this to the captured resize tensor verifies that the saved raster
    actually corresponds to pixel_values, rather than a guessed resize preview.
    """
    import torch

    t, h, w = (int(value) for value in grid)
    m, p, temporal = processor.merge_size, processor.patch_size, processor.temporal_patch_size
    patches = encoded.reshape(t, h // m, w // m, m, m, 3, temporal, p, p)
    pixels = patches.permute(0, 6, 5, 1, 3, 7, 2, 4, 8).reshape(t * temporal, 3, h * p, w * p)[0]
    mean = torch.tensor(processor.image_mean).reshape(3, 1, 1)
    std = torch.tensor(processor.image_std).reshape(3, 1, 1)
    return ((pixels * std + mean) / processor.rescale_factor).round().clamp(0, 255).to(torch.uint8)


def audit(datasets: list[Path], processor_dir: Path, out: Path) -> dict:
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor

    from unrender.data_gen.review import PROCESSOR_RUNTIME

    required = PROCESSOR_RUNTIME
    for name, version in required.items():
        if importlib.metadata.version(name).split("+")[0] != version:
            raise ValueError(f"requires candidate {name}=={version}")
    if len({path.name for path in datasets}) != len(datasets):
        raise ValueError("dataset names must be unique")
    if out.exists() and any(out.iterdir()):
        raise ValueError("output must be a fresh directory")
    prepared = [(path, *_inputs(path)) for path in datasets]
    processor = AutoImageProcessor.from_pretrained(
        processor_dir, local_files_only=True, backend="torchvision"
    )
    if type(processor).__name__ != "Qwen2VLImageProcessor":
        raise ValueError("unexpected candidate image processor")
    torch.set_num_threads(4)
    out.mkdir(parents=True, exist_ok=True)
    capture = []
    original_resize = processor.resize

    def captured_resize(*args, **kwargs):
        result = original_resize(*args, **kwargs)
        capture.append(result.detach().cpu().clone())
        return result

    processor.resize = captured_resize
    report = {
        "contract": "qwen-image-budget-audit-v2",
        "device": "cpu",
        "inference_calls": 0,
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": dict(
            sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())
        ),
        "processor_class": type(processor).__name__,
        "processor_config_sha256": sha((processor_dir / "preprocessor_config.json").read_bytes()),
        "processor_source_sha256": sha(Path(inspect.getfile(type(processor))).read_bytes()),
        "auditor_sha256": sha(Path(__file__).read_bytes()),
        "datasets": {},
        "rows": [],
        "limits": (
            "CPU raster inspection only; Python/platform differ from production. "
            "Font estimates exclude blur and glyph contrast; "
            "no model accuracy or eligibility claim."
        ),
    }
    for root, generation, rows in prepared:
        report["datasets"][root.name] = generation
        for row in rows:
            with Image.open(root / row["image"]) as opened:
                image = opened.convert("RGB")
            result = {
                "dataset": root.name,
                "id": row["id"],
                "image_sha256": row["image_sha256"],
                "layout_status": row["layout_status"],
                "chart_type": row["chart_type"],
                "source_size": list(image.size),
                "budgets": {},
            }
            for name, maximum in (("full", processor.size.longest_edge), ("512", 512 * 32 * 32)):
                capture.clear()
                encoded = processor(
                    images=[image],
                    size={"shortest_edge": processor.size.shortest_edge, "longest_edge": maximum},
                    return_tensors="pt",
                    device="cpu",
                )
                if len(capture) != 1 or capture[0].shape[0] != 1:
                    raise ValueError("unexpected processor resize path")
                grid = encoded["image_grid_thw"][0].tolist()
                recovered = reconstruct_first_frame(encoded["pixel_values"], grid, processor)
                if not torch.equal(recovered, capture[0][0]):
                    raise ValueError("saved raster would not match encoded model input")
                pixels = recovered.permute(1, 2, 0).contiguous().numpy()
                raster = Image.fromarray(pixels)
                relative = f"{root.name}/{row['id']}-{name}.png"
                destination = out / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                raster.save(destination)
                tokens = grid[0] * grid[1] * grid[2] // processor.merge_size**2
                if name == "512" and tokens > 512:
                    raise ValueError("deployed image budget exceeded")
                result["budgets"][name] = {
                    "size": list(raster.size),
                    "grid_thw": grid,
                    "image_tokens": tokens,
                    "raster": relative,
                    "raster_sha256": sha(destination.read_bytes()),
                    "pixel_values_sha256": sha(encoded["pixel_values"].numpy().tobytes()),
                    "minimum_font_pixels_estimate": round(
                        row["final_font_pixels_estimate"]
                        * min(raster.width / image.width, raster.height / image.height),
                        3,
                    ),
                    "reconstructed_pixels_equal_captured_resize": True,
                }
            report["rows"].append(result)
        print(f"{root.name}: inspected {len(rows)} images at both budgets", flush=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, action="append", required=True)
    parser.add_argument("--processor", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    audit(args.dataset, args.processor, args.out)


if __name__ == "__main__":
    main()
