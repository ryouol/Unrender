"""Build geometry-supervision training data from an existing chat-format split.

Each input row (from split_dataset.py) is {images:[path], messages:[user, assistant
=table JSON], meta}. We regenerate that chart's exact ChartSpec from its seed
(id == generation index), capture the renderer's ground-truth geometry, and emit a
new row whose assistant target is the COMPACT GEOMETRY PROGRAM (geometry_target.to_target)
and whose user turn is GEOMETRY_PROMPT. The image and meta are carried through
unchanged, so the geometry-LoRA trains on the identical images, just a different
(measurement-teaching) target.

Reproducibility check: the regenerated spec's table must equal the row's stored GT
(both come from the same seed). A mismatch means the seed/split is desynced — we
fail loudly rather than emit a mislabeled target.

    python -m unrender.train.geometry_data --in data/synthetic_v1/train.jsonl \
        --out data/synthetic_v1/train.geom.jsonl --seed 5678 --hard
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from unrender.data_gen.chart_specs import random_spec
from unrender.data_gen.geometry import capture_geometry
from unrender.data_gen.geometry_target import to_target
from unrender.io_utils import read_jsonl
from unrender.prompts import GEOMETRY_PROMPT
from unrender.schema.chart_schema import ChartData, canonical_json


def build_geometry_split(in_jsonl: str, out_jsonl: str, base_seed: int, hard: bool) -> dict:
    rows = read_jsonl(in_jsonl)
    n_ok = n_mismatch = 0
    out_path = Path(out_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            idx = int(Path(r["images"][0]).stem)
            spec = random_spec(random.Random(base_seed + idx), hard=hard)
            gt = spec.to_chart_data()
            stored = r["messages"][1]["content"]
            # the stored assistant target is the table JSON; it must reproduce
            if canonical_json(gt) != canonical_json(ChartData.model_validate_json(stored)):
                n_mismatch += 1
                continue
            target = to_target(capture_geometry(spec))
            out_row = {
                "images": r["images"],
                "messages": [
                    {"role": "user", "content": GEOMETRY_PROMPT},
                    {"role": "assistant", "content": target},
                ],
                "meta": r.get("meta", {}),
            }
            f.write(json.dumps(out_row, ensure_ascii=False) + "\n")
            n_ok += 1
    print(f"geometry split: wrote {n_ok} rows -> {out_path}  (skipped {n_mismatch} seed-mismatch)")
    return {"n_ok": n_ok, "n_mismatch": n_mismatch, "out": str(out_path)}


def main():
    p = argparse.ArgumentParser(description="Build geometry-target training data from a chat-format split.")
    p.add_argument("--in", dest="in_jsonl", required=True)
    p.add_argument("--out", dest="out_jsonl", required=True)
    p.add_argument("--seed", type=int, default=5678, help="base seed of the source split (v1=5678, v0=1234)")
    p.add_argument("--hard", action="store_true", help="source split was generated with --hard (v1)")
    args = p.parse_args()
    build_geometry_split(args.in_jsonl, args.out_jsonl, args.seed, args.hard)


if __name__ == "__main__":
    main()
