"""LoRA fine-tune Qwen3-VL on the synthetic chart->JSON data (Unsloth + TRL).

This is Phase 3. It runs on the rented CUDA GPU box, NOT your Mac — the heavy
imports (unsloth/torch/trl) are deferred into functions so the module still
imports on Apple Silicon for reading and lint.

WHY there's almost nothing to configure about the task: the training signal is
already baked into the split files. split_dataset.py wrote each row as
{images, messages:[user=EXTRACTION_PROMPT, assistant=canonical_json]} — the
SAME prompt the eval harness and inference send, and the SAME canonical JSON the
scorer compares on. So train/eval consistency is structural: this script must
NOT re-specify the prompt or reformat the target, only feed those rows to the
trainer. (prompts.py spells out why drift here silently invalidates the
benchmark.)

Runbook (on the GPU box, from the repo root):
    pip install -e ".[train]"
    # images aren't committed — regenerate them byte-for-byte first:
    python -m unrender.data_gen.generate      --n 5000 --out data/synthetic_v1 --seed 5678 --hard
    python -m unrender.data_gen.split_dataset --out data/synthetic_v1   # rewrites train/val/test.jsonl
    # train (v0+v1 mixed, label-free oversampled 1.5x):
    python -m unrender.train.sft_lora \
        --train data/synthetic_v1/train.jsonl data/synthetic_v0/train.jsonl \
        --labelfree-weight 1.5 --epochs 2 --out runs/qwen3vl4b-lora
    # eval the merged model through the SAME scorer as the frontier baselines:
    python -m unrender.eval.run_baselines --provider hf --model runs/qwen3vl4b-lora/merged \
        --data data/synthetic_v1/test.jsonl --out outputs/eval_v1/unrender-lora
    python -m unrender.eval.score --predictions outputs/eval_v1/unrender-lora/predictions.jsonl

On Modal, all of the above is wrapped by modal_train.py (gen/smoke/train/evaluate).

The exact Unsloth vision API (FastVisionModel / UnslothVisionDataCollator) moves
fast — if a call signature here is stale, check current Unsloth docs; the shape
below follows the established vision-SFT notebook.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import List

from unrender.io_utils import read_jsonl

# Iteration base; --base swaps to Qwen3-VL-8B for the launch run. The unsloth/
# mirror downloads faster but the canonical HF id (what providers.py evals)
# loads identically through FastVisionModel.
DEFAULT_BASE = "Qwen/Qwen3-VL-4B-Instruct"


def _resolve_image(path: str, data_root: str) -> str:
    """Image paths in the jsonl are repo-root-relative (data/synthetic_*/...).
    Honor them as-is, else fall back to --data-root, else fail loudly — a missing
    image must not silently drop a training sample."""
    if Path(path).exists():
        return path
    alt = Path(data_root) / path
    if alt.exists():
        return str(alt)
    raise FileNotFoundError(f"image not found: {path} (also tried {alt})")


def load_records(train_paths: List[str], data_root: str, labelfree_weight: float, seed: int) -> List[dict]:
    """Read the chat-format split rows into lightweight records, oversampling the
    label-free slice.

    Label-free charts are the skill that matters (the model must read geometry,
    not OCR printed numbers — see chart_specs.py), so we let them appear
    `labelfree_weight`x as often. Images stay on disk here; the dataset transform
    loads them lazily per batch so we never hold thousands of decoded PNGs in RAM.
    """
    rng = random.Random(seed)
    records: List[dict] = []
    n_labelfree_src = 0
    for tp in train_paths:
        for r in read_jsonl(tp):
            rec = {
                "image": _resolve_image(r["images"][0], data_root),
                "user": r["messages"][0]["content"],
                "assistant": r["messages"][1]["content"],
            }
            labels_shown = (r.get("meta") or {}).get("labels_shown", True)
            copies = 1
            if not labels_shown:
                n_labelfree_src += 1
                # integer copies + a fractional extra so 1.5 means "half of them twice"
                copies = int(labelfree_weight) + (1 if rng.random() < (labelfree_weight % 1) else 0)
            records.extend(rec for _ in range(max(1, copies)))

    rng.shuffle(records)
    print(
        f"Loaded {len(records)} training records from {len(train_paths)} file(s) "
        f"(label-free source rows: {n_labelfree_src}, oversample x{labelfree_weight})"
    )
    return records


def build_dataset(records: List[dict]):
    """Wrap records in a HF Dataset whose transform yields Unsloth vision messages
    on access — content becomes a list of {type:image|text} parts, image decoded
    lazily. The collator reads each example's `messages`."""
    from datasets import Dataset
    from PIL import Image

    ds = Dataset.from_list(records)

    def to_messages(batch):
        out = []
        for img_path, user, assistant in zip(batch["image"], batch["user"], batch["assistant"]):
            out.append([
                {"role": "user", "content": [
                    {"type": "image", "image": Image.open(img_path).convert("RGB")},
                    {"type": "text", "text": user},
                ]},
                {"role": "assistant", "content": [{"type": "text", "text": assistant}]},
            ])
        return {"messages": out}

    return ds.with_transform(to_messages)


def _patch_transformers_4572_bug(model_dir: Path) -> None:
    """transformers 4.57.2 crashes loading any LOCAL model dir whose config.json
    records transformers_version <= 4.57.2 and whose tokenizer is big + fast
    (Qwen's is): tokenization_utils_base.py json-loads config.json into a dict,
    then reads `.model_type` off it -> AttributeError, inside a Mistral-only
    regex fix that would have early-returned for Qwen anyway. Recording a
    version above the gate makes every loader skip that branch. No-op once the
    installed transformers (and thus the recorded version) moves past 4.57.2.
    """
    from packaging import version as _v

    cfg_path = Path(model_dir) / "config.json"
    if not cfg_path.exists():
        return
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    v = cfg.get("transformers_version")
    if v and _v.parse(v) <= _v.parse("4.57.2"):
        cfg["transformers_version"] = "4.57.3"
        cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Patched {cfg_path}: transformers_version {v} -> 4.57.3 (4.57.2 local-load bug)")


def train(
    train_paths: List[str],
    out: str,
    base: str = DEFAULT_BASE,
    data_root: str = ".",
    labelfree_weight: float = 1.5,
    epochs: float = 1.0,
    max_steps: int = 0,
    lr: float = 2e-4,
    batch_size: int = 2,
    grad_accum: int = 4,
    lora_r: int = 16,
    lora_alpha: int = 16,
    max_seq_length: int = 4096,
    load_in_4bit: bool = True,
    merge: bool = True,
    seed: int = 3407,
) -> None:
    # Heavy, CUDA-only imports stay inside the function (see module docstring).
    from unsloth import FastVisionModel, is_bf16_supported
    from unsloth.trainer import UnslothVisionDataCollator
    from trl import SFTConfig, SFTTrainer

    records = load_records(train_paths, data_root, labelfree_weight, seed)
    dataset = build_dataset(records)

    model, processor = FastVisionModel.from_pretrained(
        base,
        load_in_4bit=load_in_4bit,             # QLoRA: 4B fits comfortably on ~16GB
        use_gradient_checkpointing="unsloth",  # long image+JSON sequences -> save VRAM
    )
    # Fine-tune the vision tower too, not just the LM head: reading bar/point
    # geometry against the axis scale is a visual skill, so the adapter has to
    # reach the image layers — text-only LoRA would leave the core gap unfixed.
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=True,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=0.0,
        bias="none",
        random_state=seed,
    )

    FastVisionModel.for_training(model)

    # max_steps overrides epochs when set (>0) — handy for a quick smoke run.
    steps_kw = {"max_steps": max_steps} if max_steps > 0 else {"num_train_epochs": epochs}

    trainer = SFTTrainer(
        model=model,
        tokenizer=processor,
        data_collator=UnslothVisionDataCollator(model, processor),
        train_dataset=dataset,
        args=SFTConfig(
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=grad_accum,
            warmup_steps=10,
            learning_rate=lr,
            fp16=not is_bf16_supported(),
            bf16=is_bf16_supported(),
            logging_steps=10,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            seed=seed,
            output_dir=str(Path(out) / "checkpoints"),
            report_to="none",
            # Required for vision SFT: keep the image column, skip TRL's text-only
            # dataset prep, and bound the text length (image tokens are separate).
            remove_unused_columns=False,
            dataset_kwargs={"skip_prepare_dataset": True},
            dataset_text_field="",
            max_seq_length=max_seq_length,
            **steps_kw,
        ),
    )

    n_eff = batch_size * grad_accum
    print(f"Training {base}  |  records={len(records)}  eff_batch={n_eff}  "
          f"{'max_steps=' + str(max_steps) if max_steps > 0 else 'epochs=' + str(epochs)}")
    trainer.train()

    out_dir = Path(out)
    adapter_dir = out_dir / "adapter"
    model.save_pretrained(str(adapter_dir))           # LoRA adapter (small, resumable)
    processor.save_pretrained(str(adapter_dir))
    _patch_transformers_4572_bug(adapter_dir)
    print(f"Saved LoRA adapter -> {adapter_dir}")

    if merge:
        # Merge to 16bit so the existing hf_vlm_provider loads it by path with no
        # adapter wiring — eval uses the identical code path as every baseline.
        merged_dir = out_dir / "merged"
        model.save_pretrained_merged(str(merged_dir), processor, save_method="merged_16bit")
        _patch_transformers_4572_bug(merged_dir)
        print(f"Saved merged 16bit model -> {merged_dir}  (eval with --provider hf --model {merged_dir})")


def main():
    p = argparse.ArgumentParser(description="LoRA fine-tune Qwen3-VL on synthetic chart->JSON.")
    p.add_argument("--train", nargs="+", required=True, help="one or more chat-format train.jsonl files")
    p.add_argument("--out", required=True, help="output dir (adapter/ + merged/ written here)")
    p.add_argument("--base", default=DEFAULT_BASE, help="base model id (e.g. Qwen/Qwen3-VL-8B-Instruct for launch)")
    p.add_argument("--data-root", default=".", help="fallback root for resolving relative image paths")
    p.add_argument("--labelfree-weight", type=float, default=1.5, help="oversample factor for label-free charts")
    p.add_argument("--epochs", type=float, default=1.0, help="training epochs (ignored if --max-steps > 0)")
    p.add_argument("--max-steps", type=int, default=0, help="cap steps (>0 overrides epochs; for smoke tests)")
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=2, help="per-device batch size")
    p.add_argument("--grad-accum", type=int, default=4, help="gradient accumulation steps")
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=16)
    p.add_argument("--max-seq-length", type=int, default=4096, help="text token cap (dense hard charts are long)")
    p.add_argument("--no-4bit", action="store_true", help="bf16 LoRA instead of 4bit QLoRA (needs more VRAM)")
    p.add_argument("--no-merge", action="store_true", help="save adapter only, skip the merged 16bit export")
    p.add_argument("--seed", type=int, default=3407)
    args = p.parse_args()

    train(
        train_paths=args.train,
        out=args.out,
        base=args.base,
        data_root=args.data_root,
        labelfree_weight=args.labelfree_weight,
        epochs=args.epochs,
        max_steps=args.max_steps,
        lr=args.lr,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        max_seq_length=args.max_seq_length,
        load_in_4bit=not args.no_4bit,
        merge=not args.no_merge,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
