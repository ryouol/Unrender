"""Split a generated manifest into train/val/test JSONL in chat format.

Output rows match the multimodal SFT format used by ms-swift / LLaMA-Factory /
Unsloth:

    {"images": ["images/0000001.png"],
     "messages": [
        {"role": "user", "content": "<EXTRACTION_PROMPT>"},
        {"role": "assistant", "content": "<exact ground-truth JSON>"}
     ]}

The user turn uses the EXACT canonical prompt — the same string the eval harness
and inference send to every model. Test split is held out and never trained on.
"""

from __future__ import annotations

import argparse
import os
import random
from pathlib import Path

from unrender.data_gen.provenance import (
    SPLIT_CONTRACT,
    artifact_path,
    digest,
    json_bytes,
    verify_dataset,
)
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


def split(
    out: str, val_size: int, test_size: int, seed: int = 7, prompt: str = EXTRACTION_PROMPT
) -> None:
    out_dir = Path(out)
    if val_size < 0 or test_size < 0:
        raise ValueError("split sizes must be nonnegative")
    generation, entries = verify_dataset(out_dir)
    # Membership depends only on IDs and seed, never on worker completion order.
    entries.sort(key=lambda e: e["id"])
    random.Random(seed).shuffle(entries)

    if val_size + test_size >= len(entries):
        raise ValueError(f"val+test ({val_size + test_size}) >= dataset size ({len(entries)})")

    test = entries[:test_size]
    val = entries[test_size : test_size + val_size]
    train = entries[test_size + val_size :]

    payloads = {}
    for name, split_entries in (("train", train), ("val", val), ("test", test)):
        rows = []
        for e in split_entries:
            label_bytes = artifact_path(out_dir, e["label"]).read_bytes()
            if digest(label_bytes) != e["label_sha256"]:
                raise ValueError("target changed while splitting")
            meta = {
                k: e[k]
                for k in (
                    "labels_shown",
                    "chart_type",
                    "augmented",
                    "visual_review",
                    "layout_status",
                    "final_font_pixels_estimate",
                )
            }
            meta["generation"] = {
                key: e[key]
                for key in ("target_contract", "recipe_sha256", "image_sha256", "label_sha256")
            }
            rows.append(_row(e["image"], label_bytes.decode(), meta, prompt=prompt))
        payloads[f"{name}.jsonl"] = b"".join(json_bytes(row) for row in rows)

    receipt = {
        "contract": SPLIT_CONTRACT,
        "status": "splitting",
        "seed": seed,
        "recipe_sha256": generation["recipe_sha256"],
        "manifest_sha256": generation["manifest_sha256"],
        "prompt_sha256": digest(prompt.encode()),
        "splitter_sha256": digest(Path(__file__).read_bytes()),
        "files": {
            name: {"sha256": digest(raw), "rows": len(raw.splitlines())}
            for name, raw in payloads.items()
        },
    }
    if any((out_dir / name).exists() for name in (*payloads, "split.json")):
        raise ValueError("split files already exist; cannot overwrite a frozen or partial split")
    # Exclusive claim prevents concurrent splitters from publishing mixed memberships.
    with (out_dir / "split.json").open("xb") as stream:
        stream.write(json_bytes(receipt))
    for name, raw in payloads.items():
        with (out_dir / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    verify_dataset(out_dir)  # a concurrent input mutation cannot earn a complete receipt
    receipt["status"] = "complete"
    pending = out_dir / ".split.complete.json"
    with pending.open("xb") as stream:
        stream.write(json_bytes(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(out_dir / "split.json")
    for name, item in receipt["files"].items():
        print(f"{name}: {item['rows']:>6} -> {out_dir / name}")


def main():
    p = argparse.ArgumentParser(description="Split manifest into train/val/test JSONL.")
    p.add_argument("--out", type=str, default="data/synthetic", help="dataset directory")
    p.add_argument("--val-size", type=int, default=500, help="validation examples")
    p.add_argument("--test-size", type=int, default=1000, help="held-out test examples")
    p.add_argument("--seed", type=int, default=7, help="shuffle seed")
    p.add_argument(
        "--prompt-v2",
        action="store_true",
        help="bake EXTRACTION_PROMPT_V2 into the rows (synthetic_v2 sets; "
        "never mix prompt versions within one comparison)",
    )
    args = p.parse_args()
    split(
        args.out,
        args.val_size,
        args.test_size,
        args.seed,
        prompt=EXTRACTION_PROMPT_V2 if args.prompt_v2 else EXTRACTION_PROMPT,
    )


if __name__ == "__main__":
    main()
