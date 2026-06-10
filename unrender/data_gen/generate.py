"""Generate a synthetic chart dataset: images + exact JSON labels.

Each sample is fully determined by its index and the base seed, so the whole
dataset is reproducible and you can grow it deterministically (indices
0..N are stable as you raise --n). Runs across CPU cores.

Usage:
    python -m unrender.data_gen.generate --n 1000 --out data/synthetic
    python -m unrender.data_gen.generate --n 20 --no-augment   # quick smoke test
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Optional

from PIL import Image
from tqdm import tqdm

from unrender.data_gen.augment import augment_image
from unrender.data_gen.chart_specs import random_spec
from unrender.data_gen.render import render_chart
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
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _make_one(args_tuple):
    index, base_seed, images_dir, labels_dir, augment, max_side = args_tuple
    rng = random.Random(base_seed + index)

    spec = random_spec(rng)
    img = render_chart(spec)
    did_augment = augment and rng.random() < _AUGMENT_FRACTION
    if did_augment:
        img = augment_image(img, rng)
    img = _cap_long_side(img, max_side)

    stem = f"{index:07d}"
    img_path = os.path.join(images_dir, f"{stem}.png")
    label_path = os.path.join(labels_dir, f"{stem}.json")
    img.save(img_path)
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(canonical_json(spec.to_chart_data()))

    # `labels_shown` and `chart_type` are the slice keys the eval table needs;
    # they live only in the spec, so capture them here or they're lost.
    return {
        "id": stem, "image": img_path, "label": label_path,
        "chart_type": spec.chart_type,
        "labels_shown": spec.value_labels_shown,
        "augmented": did_augment,
    }


def generate(
    n: int,
    out: str,
    base_seed: int = 1234,
    augment: bool = True,
    workers: Optional[int] = None,
    max_side: int = 1280,
    start_index: int = 0,
) -> Path:
    out_dir = Path(out)
    images_dir = out_dir / "images"
    labels_dir = out_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    tasks = [
        (i, base_seed, str(images_dir), str(labels_dir), augment, max_side)
        for i in range(start_index, start_index + n)
    ]

    manifest_path = out_dir / "manifest.jsonl"
    mode = "a" if start_index > 0 and manifest_path.exists() else "w"

    print(f"Generating {n} charts -> {out_dir}  (workers={workers}, augment={augment})")
    with open(manifest_path, mode, encoding="utf-8") as mf:
        if workers == 1:
            for t in tqdm(tasks, total=len(tasks)):
                mf.write(json.dumps(_make_one(t)) + "\n")
        else:
            import multiprocessing as mp

            with mp.Pool(workers) as pool:
                for entry in tqdm(pool.imap_unordered(_make_one, tasks, chunksize=8), total=len(tasks)):
                    mf.write(json.dumps(entry) + "\n")

    print(f"Done. Manifest: {manifest_path}")
    return manifest_path


def main():
    p = argparse.ArgumentParser(description="Generate synthetic chart->JSON data.")
    p.add_argument("--n", type=int, default=20, help="number of charts to generate")
    p.add_argument("--out", type=str, default="data/synthetic", help="output directory")
    p.add_argument("--seed", type=int, default=1234, help="base random seed")
    p.add_argument("--workers", type=int, default=None, help="processes (default: cpus-2)")
    p.add_argument("--max-side", type=int, default=1280, help="cap longest image side (px)")
    p.add_argument("--start-index", type=int, default=0, help="first sample index (for appending)")
    p.add_argument("--no-augment", action="store_true", help="disable image degradations")
    args = p.parse_args()

    generate(
        n=args.n,
        out=args.out,
        base_seed=args.seed,
        augment=not args.no_augment,
        workers=args.workers,
        max_side=args.max_side,
        start_index=args.start_index,
    )


if __name__ == "__main__":
    main()
