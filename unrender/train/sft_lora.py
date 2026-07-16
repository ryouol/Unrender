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
    # train (v0+v1 mixed, label-free oversampled 1.5x, best-ckpt on a val set):
    python -m unrender.train.sft_lora \
        --train data/synthetic_v1/train.jsonl data/synthetic_v0/train.jsonl \
        --val   data/synthetic_v1/val.jsonl   data/synthetic_v0/val.jsonl \
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
import math
import random
from pathlib import Path
from typing import List

from unrender.io_utils import read_jsonl

# Iteration base; --base swaps to Qwen3-VL-8B for the launch run.
# CAUTION: with load_in_4bit=True, Unsloth REDIRECTS this id to its own
# `unsloth/Qwen3-VL-4B-Instruct-unsloth-bnb-4bit` mirror and saves THAT
# tokenizer/processor into merged/. So the fair eval base-model control is NOT
# the canonical Qwen/ id loaded through plain transformers (different processor =
# confound) — it must be the Unsloth full-precision mirror pinned to the matching
# revision. See PREREGISTRATION.md and run_baselines.py --revision.
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


def _copies(mult: float, rng: random.Random) -> int:
    """Integer copies from a (possibly fractional) oversample multiplier — e.g.
    1.5 means 'half of them twice'. Always >= 1."""
    return max(1, int(mult) + (1 if rng.random() < (mult % 1) else 0))


def _parse_type_weights(spec: str) -> dict:
    """"multi_line:1.5,stacked_bar:2" -> {"multi_line": 1.5, "stacked_bar": 2.0}.
    The generic per-chart-type oversampling knob (the 2026-07 sweep's biggest
    per-type gaps vs Gemini are multi_line/stacked label-free). Empty -> {}."""
    out = {}
    for part in (s.strip() for s in (spec or "").split(",") if s.strip()):
        name, _, w = part.partition(":")
        out[name.strip()] = float(w) if w else 1.0
    return out


def load_records(train_paths: List[str], data_root: str, labelfree_weight: float, seed: int,
                 hbar_weight: float = 1.0, type_weights: dict | None = None) -> List[dict]:
    """Read the chat-format split rows into lightweight records, oversampling the
    slices that matter.

    Label-free charts are the skill that matters (the model must read geometry,
    not OCR printed numbers — see chart_specs.py), so we let them appear
    `labelfree_weight`x as often. `hbar_weight` independently oversamples
    horizontal_bar (kept for recipe continuity); `type_weights` is the generic
    per-chart-type version. Multipliers compose (a label-free h-bar gets both).
    Images stay on disk here; the dataset transform loads them lazily per batch.
    """
    rng = random.Random(seed)
    type_weights = type_weights or {}
    records: List[dict] = []
    n_labelfree_src = n_hbar_src = 0
    for tp in train_paths:
        for r in read_jsonl(tp):
            rec = {
                "image": _resolve_image(r["images"][0], data_root),
                "user": r["messages"][0]["content"],
                "assistant": r["messages"][1]["content"],
            }
            meta = r.get("meta") or {}
            mult = 1.0
            if not meta.get("labels_shown", True):
                n_labelfree_src += 1
                mult *= labelfree_weight
            ct = meta.get("chart_type")
            if ct == "horizontal_bar":
                n_hbar_src += 1
                mult *= hbar_weight
            mult *= type_weights.get(ct, 1.0)
            records.extend(rec for _ in range(_copies(mult, rng)))

    rng.shuffle(records)
    print(
        f"Loaded {len(records)} training records from {len(train_paths)} file(s) "
        f"(label-free src: {n_labelfree_src} x{labelfree_weight}; "
        f"horizontal_bar src: {n_hbar_src} x{hbar_weight}; type_weights={type_weights})"
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


def _numeric_token_ids(tokenizer) -> set:
    """Token ids whose surface form contains a digit — the fraction/number tokens
    the geometry target's precision lives in. Up-weighting their loss makes the
    model care about 0.314 vs 0.341 (the Stage-A coordinate-precision failure).
    Pure Python (no torch) so it's unit-testable off the GPU box."""
    out = set()
    for tid in range(len(tokenizer)):
        tok = tokenizer.convert_ids_to_tokens(tid)
        if isinstance(tok, str) and any(ch.isdigit() for ch in tok):
            out.add(tid)
    return out


def _latest_checkpoint(out: str):
    """Newest checkpoint dir under <out>/checkpoints, or None. Lets a relaunch
    of the SAME run RESUME instead of restarting from step 0 — the one-shot
    insurance for a multi-hour container dying mid-train. Only reuse an
    --out-name when the config is identical; a fresh run name starts fresh."""
    root = Path(out) / "checkpoints"
    if not root.exists():
        return None
    ckpts = [d for d in root.iterdir()
             if d.is_dir() and d.name.startswith("checkpoint-") and d.name.split("-")[-1].isdigit()]
    if not ckpts:
        return None
    return str(max(ckpts, key=lambda d: int(d.name.split("-")[-1])))


def _eval_save_steps(total_steps: int, n_evals: int) -> int:
    """Eval/save interval giving ~`n_evals` checkpoints over a `total_steps` run.
    Floored at 10 and capped at the run length so at least one eval always fires
    (load_best_model_at_end needs a recorded metric). save_steps == eval_steps, so
    the HF 'save must be a multiple of eval' constraint holds trivially. Pure
    arithmetic -> unit-testable off the GPU box."""
    if total_steps <= 0:
        return 10
    return min(total_steps, max(10, total_steps // max(1, n_evals)))


def train(
    train_paths: List[str],
    out: str,
    base: str = DEFAULT_BASE,
    data_root: str = ".",
    labelfree_weight: float = 1.5,
    hbar_weight: float = 1.0,
    numeric_loss_weight: float = 1.0,
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
    val_paths: List[str] | None = None,
    val_size: int = 256,
    n_evals: int = 5,
    save_total_limit: int = 3,
    type_weights: str = "",
    seed: int = 3407,
) -> None:
    # Heavy, CUDA-only imports stay inside the function (see module docstring).
    from unsloth import FastVisionModel, is_bf16_supported
    from unsloth.trainer import UnslothVisionDataCollator
    from trl import SFTConfig, SFTTrainer

    tw = _parse_type_weights(type_weights)
    records = load_records(train_paths, data_root, labelfree_weight, seed,
                           hbar_weight=hbar_weight, type_weights=tw)
    dataset = build_dataset(records)

    # Validation set for best-checkpoint selection (the fairness fix — the old
    # table-LoRA merged the FINAL checkpoint with no val, which the audit flagged
    # as an unfair anchor). Unweighted (natural distribution) and capped so the
    # eval passes stay cheap; the [:val_size] slice is deterministic because
    # load_records shuffles by `seed`. None => no eval (smoke stays a plumbing check).
    eval_dataset = None
    if val_paths:
        val_records = load_records(val_paths, data_root, labelfree_weight=1.0, seed=seed, hbar_weight=1.0)
        if val_size and len(val_records) > val_size:
            val_records = val_records[:val_size]
        eval_dataset = build_dataset(val_records)
        print(f"Validation: {len(val_records)} records (best-checkpoint selection on eval_loss)")

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

    # Best-checkpoint selection on the val set (only when a val set was built).
    # eval_loss under each arm's OWN objective (the numeric-weighted CE for the
    # lever arm, plain CE for the baseline) — within-arm selection, so the
    # lever-vs-baseline contrast stays clean. ~n_evals eval points over the run.
    eval_kw: dict = {}
    if eval_dataset is not None:
        eff_batch = batch_size * grad_accum
        total_steps = max_steps if max_steps > 0 else math.ceil(math.ceil(len(records) / eff_batch) * epochs)
        es = _eval_save_steps(total_steps, n_evals)
        eval_kw = {
            "eval_strategy": "steps",
            "eval_steps": es,
            "save_strategy": "steps",
            "save_steps": es,
            "save_total_limit": save_total_limit,
            "load_best_model_at_end": True,
            "metric_for_best_model": "eval_loss",
            "greater_is_better": False,
            "per_device_eval_batch_size": batch_size,
        }
        print(f"eval/save every {es} steps (~{max(1, total_steps // es)} evals over ~{total_steps} steps); "
              f"load best of last {save_total_limit} on eval_loss")

    # Numeric-token loss weighting (the precision lever, default off = vanilla SFT):
    # up-weight cross-entropy on digit-bearing tokens so the model learns fraction
    # precision harder. We recompute CE manually from logits (calling the model
    # WITHOUT labels, so Unsloth's fused CE doesn't drop the logits we need).
    trainer_cls = SFTTrainer
    if numeric_loss_weight and numeric_loss_weight != 1.0:
        import torch

        tok = getattr(processor, "tokenizer", processor)
        _num_tensor = torch.tensor(sorted(_numeric_token_ids(tok)), dtype=torch.long)
        _w = float(numeric_loss_weight)
        print(f"numeric-token loss weighting: {_num_tensor.numel()} digit-bearing tokens x{_w}")

        class _NumWeightedSFTTrainer(SFTTrainer):
            def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
                from torch.nn import functional as F
                labels = inputs.pop("labels")
                outputs = model(**inputs)                      # logits, no fused loss
                inputs["labels"] = labels
                V = outputs.logits.size(-1)
                sl = outputs.logits[..., :-1, :].contiguous().view(-1, V)
                lab = labels[..., 1:].contiguous().view(-1).to(sl.device)
                ce = F.cross_entropy(sl, lab, ignore_index=-100, reduction="none")
                mask = lab != -100
                isnum = torch.isin(lab, _num_tensor.to(lab.device))
                w = torch.where(isnum & mask, _w, 1.0)
                loss = (ce * w)[mask].sum() / w[mask].sum().clamp_min(1.0)
                return (loss, outputs) if return_outputs else loss

        trainer_cls = _NumWeightedSFTTrainer

    trainer = trainer_cls(
        model=model,
        tokenizer=processor,
        data_collator=UnslothVisionDataCollator(model, processor),
        train_dataset=dataset,
        eval_dataset=eval_dataset,
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
            **eval_kw,
        ),
    )

    n_eff = batch_size * grad_accum
    print(f"Training {base}  |  records={len(records)}  eff_batch={n_eff}  "
          f"{'max_steps=' + str(max_steps) if max_steps > 0 else 'epochs=' + str(epochs)}")
    resume = _latest_checkpoint(out)
    if resume:
        print(f"RESUMING from {resume} (delete {Path(out) / 'checkpoints'} for a fresh start)")
    trainer.train(resume_from_checkpoint=resume)

    out_dir = Path(out)
    # Provenance: the exact recipe this run used, next to its weights — the
    # eval side already records meta.json; training gets the same paper trail.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "meta.json").write_text(json.dumps({
        "train_paths": train_paths, "val_paths": val_paths, "base": base,
        "labelfree_weight": labelfree_weight, "hbar_weight": hbar_weight,
        "type_weights": tw, "numeric_loss_weight": numeric_loss_weight,
        "epochs": epochs, "max_steps": max_steps, "lr": lr,
        "batch_size": batch_size, "grad_accum": grad_accum, "lora_r": lora_r,
        "lora_alpha": lora_alpha, "max_seq_length": max_seq_length,
        "val_size": val_size, "n_evals": n_evals, "seed": seed,
        "n_records": len(records),
    }, indent=2, sort_keys=True) + "\n")

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
    p.add_argument("--val", nargs="+", default=None,
                   help="val.jsonl file(s) for best-checkpoint selection on eval_loss; omit to disable (final-ckpt)")
    p.add_argument("--val-size", type=int, default=256, help="cap on val records used per eval (deterministic subset)")
    p.add_argument("--n-evals", type=int, default=5, help="approx number of eval/save points across the run")
    p.add_argument("--save-total-limit", type=int, default=3, help="checkpoints to keep (best is always kept)")
    p.add_argument("--out", required=True, help="output dir (adapter/ + merged/ written here)")
    p.add_argument("--base", default=DEFAULT_BASE, help="base model id (e.g. Qwen/Qwen3-VL-8B-Instruct for launch)")
    p.add_argument("--data-root", default=".", help="fallback root for resolving relative image paths")
    p.add_argument("--labelfree-weight", type=float, default=1.5, help="oversample factor for label-free charts")
    p.add_argument("--type-weights", default="",
                   help='per-chart-type oversampling, e.g. "multi_line:1.5,stacked_bar:1.5" (composes with the others)')
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
        val_paths=args.val,
        val_size=args.val_size,
        n_evals=args.n_evals,
        save_total_limit=args.save_total_limit,
        out=args.out,
        base=args.base,
        data_root=args.data_root,
        labelfree_weight=args.labelfree_weight,
        type_weights=args.type_weights,
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
