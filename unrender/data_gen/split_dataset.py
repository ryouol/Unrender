"""Split a generated manifest into train/val/test JSONL in chat format.

Output rows match the multimodal SFT format used by ms-swift / LLaMA-Factory /
Unsloth:

    {"images": ["data/synthetic/images/0000001.png"],
     "messages": [
        {"role": "user", "content": "<EXTRACTION_PROMPT>"},
        {"role": "assistant", "content": "<exact ground-truth JSON>"}
     ]}

The user turn uses the EXACT canonical prompt — the same string the eval harness
and inference send to every model. Test split is held out and never trained on.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from unrender.io_utils import read_jsonl
from unrender.prompts import EXTRACTION_PROMPT, EXTRACTION_PROMPT_V2


def _row(image_path: str, label_json: str, meta: dict, prompt: str = EXTRACTION_PROMPT) -> dict:
    # "images"/"messages" are the SFT fields trainers read; "meta" is ignored by
    # training and carries the slice keys the eval scorer needs.
    return {
        "images": [image_path],
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": label_json},
        ],
        "meta": meta,
    }


def split(out: str, val_size: int, test_size: int, seed: int = 7,
          prompt: str = EXTRACTION_PROMPT) -> None:
    out_dir = Path(out)
    manifest_path = out_dir / "manifest.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest at {manifest_path}. Run generate first.")

    entries = read_jsonl(manifest_path)
    # Sort by stable id BEFORE the seeded shuffle so split membership depends only on
    # (id set, seed) — never on manifest write-order. Generation now writes in index
    # order too, but this makes the split reproducible even from an older unordered
    # manifest. (Splits frozen before this fix are pinned by explicit id-list, e.g.
    # unrender/eval/subsets/modal_v1_split.json — regenerating will NOT reproduce them.)
    entries.sort(key=lambda e: e["id"])
    random.Random(seed).shuffle(entries)

    if val_size + test_size >= len(entries):
        raise ValueError(f"val+test ({val_size+test_size}) >= dataset size ({len(entries)})")

    test = entries[:test_size]
    val = entries[test_size : test_size + val_size]
    train = entries[test_size + val_size :]

    for name, split_entries in (("train", train), ("val", val), ("test", test)):
        path = out_dir / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for e in split_entries:
                label_json = Path(e["label"]).read_text(encoding="utf-8").strip()
                meta = {k: e.get(k) for k in ("labels_shown", "chart_type", "augmented")}
                f.write(json.dumps(_row(e["image"], label_json, meta, prompt=prompt)) + "\n")
        print(f"{name}: {len(split_entries):>6} -> {path}")


def main():
    p = argparse.ArgumentParser(description="Split manifest into train/val/test JSONL.")
    p.add_argument("--out", type=str, default="data/synthetic", help="dataset directory")
    p.add_argument("--val-size", type=int, default=500, help="validation examples")
    p.add_argument("--test-size", type=int, default=1000, help="held-out test examples")
    p.add_argument("--seed", type=int, default=7, help="shuffle seed")
    p.add_argument("--prompt-v2", action="store_true",
                   help="bake EXTRACTION_PROMPT_V2 into the rows (synthetic_v2 sets; "
                        "never mix prompt versions within one comparison)")
    args = p.parse_args()
    split(args.out, args.val_size, args.test_size, args.seed,
          prompt=EXTRACTION_PROMPT_V2 if args.prompt_v2 else EXTRACTION_PROMPT)


if __name__ == "__main__":
    main()
