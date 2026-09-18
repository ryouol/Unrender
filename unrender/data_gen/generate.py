"""Generate a synthetic chart dataset: images + exact JSON labels.

Each sample is determined by its index, seed, recorded source and rendering
environment. Each invocation creates one immutable dataset in an empty directory;
there is no in-place regeneration or append. Runs across CPU cores.

Usage:
    python -m unrender.data_gen.generate --n 1000 --out data/synthetic
    python -m unrender.data_gen.generate --n 20 --no-augment   # quick smoke test
"""

from __future__ import annotations

import argparse
import io
import os
import random
from dataclasses import asdict
from pathlib import Path

from PIL import Image
from tqdm import tqdm

from unrender.data_gen.augment import augment_image
from unrender.data_gen.chart_specs import TARGET_CONTRACT, random_spec
from unrender.data_gen.provenance import digest, json_bytes, recipe
from unrender.data_gen.render import render_with_diagnostics
from unrender.schema.chart_schema import canonical_json

# Fraction of samples that get degraded when augmentation is enabled. The rest
# stay pristine so the model also sees clean, high-DPI renders.
_AUGMENT_FRACTION = 0.85


def _cap_long_side(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        return img
    scale = max_side / longest
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _make_one(args_tuple):
    index, base_seed, images_dir, labels_dir, augment, max_side, hard, aug_frac, v2, recipe_hash = (
        args_tuple
    )
    rng = random.Random(base_seed + index)

    spec = random_spec(rng, hard=hard, v2=v2)
    img, layout = render_with_diagnostics(spec)
    native_size = list(img.size)
    did_augment = augment and rng.random() < aug_frac
    if did_augment:
        img = augment_image(img, rng)
    augmented_size = list(img.size)
    img = _cap_long_side(img, max_side)

    stem = f"{index:07d}"
    img_path = os.path.join(images_dir, f"{stem}.png")
    label_path = os.path.join(labels_dir, f"{stem}.json")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    label_bytes = canonical_json(spec.to_chart_data()).encode()
    with open(img_path, "xb") as stream:
        stream.write(image_bytes)
    with open(label_path, "xb") as stream:
        stream.write(label_bytes)
    return {
        "id": stem,
        "image": f"images/{stem}.png",
        "label": f"labels/{stem}.json",
        "chart_type": spec.chart_type,
        "labels_shown": spec.value_labels_shown,
        "augmented": did_augment,
        "target_contract": TARGET_CONTRACT,
        "recipe_sha256": recipe_hash,
        "image_sha256": digest(image_bytes),
        "label_sha256": digest(label_bytes),
        "spec": asdict(spec),
        "native_size": native_size,
        "image_size": list(img.size),
        "visual_review": "not_reviewed",
        "layout": layout,
        "layout_status": layout["status"],
        "augmented_size": augmented_size,
        "final_font_pixels_estimate": round(
            min((item["font_pixels"] for item in layout["text"]), default=0)
            * min(img.width / augmented_size[0], img.height / augmented_size[1]),
            3,
        ),
    }


def generate(
    n: int,
    out: str,
    base_seed: int = 1234,
    augment: bool = True,
    workers: int | None = None,
    max_side: int = 1280,
    start_index: int = 0,
    hard: bool = False,
    v2: bool = False,
) -> Path:
    if n <= 0 or start_index < 0 or max_side < 1 or (workers is not None and workers < 1):
        raise ValueError(
            "n, max_side and workers must be positive; start_index must be nonnegative"
        )
    if hard and v2:
        raise ValueError("choose one sampling profile: hard or v2")
    out_dir = Path(out)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(
            "output directory is not empty; frozen or partial datasets "
            "cannot be overwritten or appended"
        )
    workers = workers if workers is not None else max(1, (os.cpu_count() or 4) - 2)
    aug_frac = 0.95 if (hard or v2) else _AUGMENT_FRACTION
    parameters = dict(
        n=n,
        base_seed=base_seed,
        augment=augment,
        max_side=max_side,
        start_index=start_index,
        hard=hard,
        v2=v2,
        augmentation_fraction=aug_frac,
    )
    identity = recipe(**parameters)
    recipe_hash = digest(json_bytes(identity))
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = out_dir / "generation.json"
    receipt = {"status": "generating", "recipe": identity, "recipe_sha256": recipe_hash}
    # Exclusive create is the ownership claim if two processes choose an empty directory.
    with receipt_path.open("xb") as stream:
        stream.write(json_bytes(receipt))
    images_dir, labels_dir = out_dir / "images", out_dir / "labels"
    images_dir.mkdir()
    labels_dir.mkdir()
    tasks = [
        (
            i,
            base_seed,
            str(images_dir),
            str(labels_dir),
            augment,
            max_side,
            hard,
            aug_frac,
            v2,
            recipe_hash,
        )
        for i in range(start_index, start_index + n)
    ]
    pending = out_dir / ".manifest.inprogress.jsonl"
    manifest_path = out_dir / "manifest.jsonl"
    print(f"Generating {n} charts -> {out_dir} (contract={TARGET_CONTRACT}, workers={workers})")
    with pending.open("xb") as stream:
        if workers == 1:
            for task in tqdm(tasks):
                stream.write(json_bytes(_make_one(task)))
        else:
            import multiprocessing as mp

            with mp.Pool(workers) as pool:
                for entry in tqdm(pool.imap(_make_one, tasks, chunksize=8), total=len(tasks)):
                    stream.write(json_bytes(entry))
        stream.flush()
        os.fsync(stream.fileno())
    if recipe(**parameters) != identity:
        raise ValueError("generation source/environment changed; output remains incomplete")
    pending.rename(manifest_path)
    receipt.update(status="complete", manifest_sha256=digest(manifest_path.read_bytes()))
    completed = out_dir / ".generation.complete.json"
    with completed.open("xb") as stream:
        stream.write(json_bytes(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    completed.replace(receipt_path)
    print(f"Done. Manifest: {manifest_path}; images still require visual/recoverability review.")
    return manifest_path


def main():
    p = argparse.ArgumentParser(description="Generate synthetic chart->JSON data.")
    p.add_argument("--n", type=int, default=20, help="number of charts to generate")
    p.add_argument("--out", type=str, default="data/synthetic", help="output directory")
    p.add_argument("--seed", type=int, default=1234, help="base random seed")
    p.add_argument("--workers", type=int, default=None, help="processes (default: cpus-2)")
    p.add_argument("--max-side", type=int, default=1280, help="cap longest image side (px)")
    p.add_argument(
        "--start-index", type=int, default=0, help="first sample index in a NEW dataset directory"
    )
    p.add_argument("--no-augment", action="store_true", help="disable image degradations")
    p.add_argument(
        "--hard", action="store_true", help="eval-v1 hard mode (denser, truncated axes, K/M/B, ...)"
    )
    p.add_argument(
        "--v2",
        action="store_true",
        help="synthetic_v2 mode (magnitudes to 1e9, real-world axis formats, year axes, themes)",
    )
    args = p.parse_args()

    generate(
        n=args.n,
        out=args.out,
        base_seed=args.seed,
        augment=not args.no_augment,
        workers=args.workers,
        max_side=args.max_side,
        start_index=args.start_index,
        hard=args.hard,
        v2=args.v2,
    )


if __name__ == "__main__":
    main()
