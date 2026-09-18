"""Standard Transformers/PEFT LoRA training with explicit vision and resume contracts.

Heavy imports are deferred so data/config checks remain usable without a GPU.
Training requires reviewed source receipts, an immutable base revision and the
exact candidate runtime lock. Dataset images and complete assistant targets are
verified by the loader/collator. GPU memory, quality and recovery still require
an actual Qwen canary; CPU correctness is not training-quality evidence.
"""

from __future__ import annotations

import argparse
import io
import math
import random
from pathlib import Path

from unrender.data_gen.provenance import read_split
from unrender.io_utils import resolve_image

# The requested repository and exact revision are loaded without mirror redirection.
DEFAULT_BASE = "Qwen/Qwen3-VL-4B-Instruct"


def _copies(mult: float, rng: random.Random) -> int:
    """Integer copies from a (possibly fractional) oversample multiplier — e.g.
    1.5 means 'half of them twice'. Always >= 1."""
    return max(1, int(mult) + (1 if rng.random() < (mult % 1) else 0))


def _parse_type_weights(spec: str) -> dict:
    """ "multi_line:1.5,stacked_bar:2" -> {"multi_line": 1.5, "stacked_bar": 2.0}.
    The generic per-chart-type oversampling knob (the 2026-07 sweep's biggest
    per-type gaps vs Gemini are multi_line/stacked label-free). Empty -> {}."""
    out = {}
    for part in (s.strip() for s in (spec or "").split(",") if s.strip()):
        name, _, w = part.partition(":")
        out[name.strip()] = float(w) if w else 1.0
    return out


def load_records(
    train_paths: list[str],
    data_root: str,
    labelfree_weight: float,
    seed: int,
    hbar_weight: float = 1.0,
    type_weights: dict | None = None,
) -> list[dict]:
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
    records: list[dict] = []
    n_labelfree_src = n_hbar_src = 0
    for tp in train_paths:
        split_path = Path(data_root) / tp
        for r in read_split(split_path):
            image = resolve_image(r["images"][0], split_path)
            if not Path(image).is_file():
                raise FileNotFoundError(f"training image not found: {image}")
            rec = {
                "image": image,
                "user": r["messages"][0]["content"],
                "assistant": r["messages"][1]["content"],
                "image_sha256": ((r.get("meta") or {}).get("generation") or {}).get("image_sha256"),
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


def build_dataset(records: list[dict]):
    """Wrap records in a HF Dataset whose transform yields vision messages
    on access — content becomes a list of {type:image|text} parts, image decoded
    lazily. The collator reads each example's `messages`."""
    from datasets import Dataset
    from PIL import Image

    ds = Dataset.from_list(records)

    def to_messages(batch):
        from unrender.data_gen.provenance import digest

        out = []
        for img_path, user, assistant, expected in zip(
            batch["image"], batch["user"], batch["assistant"], batch["image_sha256"], strict=True
        ):
            raw = Path(img_path).read_bytes()
            if not expected or digest(raw) != expected:
                raise ValueError("training image changed after source review")
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            out.append(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": image},
                            {"type": "text", "text": user},
                        ],
                    },
                    {"role": "assistant", "content": [{"type": "text", "text": assistant}]},
                ]
            )
        return {"messages": out}

    return ds.with_transform(to_messages)


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


def _eval_save_steps(total_steps: int, n_evals: int) -> int:
    """Eval/save interval giving ~`n_evals` checkpoints over a `total_steps` run.
    Floored at 10 and capped at the run length so at least one eval always fires
    (load_best_model_at_end needs a recorded metric). save_steps == eval_steps, so
    the HF 'save must be a multiple of eval' constraint holds trivially. Pure
    arithmetic -> unit-testable off the GPU box."""
    if total_steps <= 0:
        return 10
    return min(total_steps, max(10, total_steps // max(1, n_evals)))


def _train_owned(
    train_paths: list[str],
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
    val_paths: list[str] | None = None,
    val_size: int = 256,
    n_evals: int = 5,
    save_total_limit: int = 3,
    type_weights: str = "",
    seed: int = 3407,
    base_revision: str = "",
    checkpoint_commit=None,
) -> None:
    from unrender.data_gen.provenance import digest
    from unrender.data_gen.review import require_training_sources
    from unrender.train.loss import validate_numeric_weight

    validate_numeric_weight(numeric_loss_weight)
    source_reviews = require_training_sources(train_paths, val_paths or [], data_root)
    from unrender.train.checkpoints import latest
    from unrender.train.recipe import (
        inventory,
        record_identity,
        require_revision,
        runtime_identity,
        source_identity,
    )

    require_revision(base_revision)
    import importlib.metadata

    if importlib.metadata.version("transformers") != "5.17.0":
        raise ValueError("training requires the verified Transformers 5.17.0 lifecycle")
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForImageTextToText,
        AutoProcessor,
        BitsAndBytesConfig,
        TrainingArguments,
        set_seed,
    )

    if not torch.cuda.is_available():
        raise ValueError("Qwen training requires a CUDA canary host")
    set_seed(seed)
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    from unrender.train.collator import ReviewedVisionCollator

    tw = _parse_type_weights(type_weights)
    records = load_records(
        train_paths, data_root, labelfree_weight, seed, hbar_weight=hbar_weight, type_weights=tw
    )
    dataset = build_dataset(records)

    # Validation set for best-checkpoint selection (the fairness fix — the old
    # table-LoRA merged the FINAL checkpoint with no val, which the audit flagged
    # as an unfair anchor). Unweighted (natural distribution) and capped so the
    # eval passes stay cheap; the [:val_size] slice is deterministic because
    # load_records shuffles by `seed`. None => no eval (smoke stays a plumbing check).
    eval_dataset = None
    if val_paths:
        val_records = load_records(
            val_paths, data_root, labelfree_weight=1.0, seed=seed, hbar_weight=1.0
        )
        if val_size and len(val_records) > val_size:
            val_records = val_records[:val_size]
        eval_dataset = build_dataset(val_records)
        print(f"Validation: {len(val_records)} records (best-checkpoint selection on eval_loss)")

    for path, receipt in source_reviews.items():
        if digest(Path(path).read_bytes()) != receipt["split_sha256"]:
            raise ValueError("training split changed after source review")

    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(repo_id=base, revision=base_revision)).resolve()
    if snapshot.name != base_revision:
        raise ValueError("base snapshot did not resolve to the requested immutable revision")
    base_files = inventory(snapshot)
    processor_config_hash = digest((snapshot / "preprocessor_config.json").read_bytes())
    if any(
        receipt["processor_config_sha256"] != processor_config_hash
        for receipt in source_reviews.values()
    ):
        raise ValueError("loaded processor differs from the reviewed model inputs")
    processor = AutoProcessor.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False
    )
    quantization = (
        BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        )
        if load_in_4bit
        else None
    )
    model = AutoModelForImageTextToText.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        dtype=compute_dtype,
        device_map={"": torch.cuda.current_device()},
        quantization_config=quantization,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    if load_in_4bit:
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )
    model = get_peft_model(
        model,
        LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=0.0,
            bias="none",
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
    )
    # all-linear covers both vision and language projections, excluding output
    # heads according to PEFT. Record the actual adapted module list in the recipe.
    adapted_modules = sorted(
        name for name, module in model.named_modules() if hasattr(module, "lora_A")
    )
    if not adapted_modules:
        raise ValueError("no LoRA target modules were adapted")

    # max_steps overrides epochs when set (>0) — handy for a quick smoke run.
    steps_kw = {"max_steps": max_steps} if max_steps > 0 else {"num_train_epochs": epochs}

    # Best-checkpoint selection on the val set (only when a val set was built).
    # eval_loss under each arm's OWN objective (the numeric-weighted CE for the
    # lever arm, plain CE for the baseline) — within-arm selection, so the
    # lever-vs-baseline contrast stays clean. ~n_evals eval points over the run.
    eval_kw: dict = {}
    if eval_dataset is not None:
        eff_batch = batch_size * grad_accum
        total_steps = (
            max_steps if max_steps > 0 else math.ceil(math.ceil(len(records) / eff_batch) * epochs)
        )
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
        print(
            f"eval/save every {es} steps over {total_steps} steps; "
            f"load best of last {save_total_limit} on eval_loss"
        )

    # One objective for both weight-one and numeric-weighted runs. Normalize
    # over the full optimizer batch, not separate microbatch weighted means.
    from unrender.train.trainer import reviewed_trainer_type

    tok = getattr(processor, "tokenizer", processor)
    trainer_cls = reviewed_trainer_type()
    trainer = trainer_cls(
        numeric_ids=sorted(_numeric_token_ids(tok)),
        numeric_weight=numeric_loss_weight,
        model=model,
        processing_class=processor,
        data_collator=ReviewedVisionCollator(processor, max_length=max_seq_length),
        train_dataset=dataset,
        eval_dataset=eval_dataset,
        args=TrainingArguments(
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=grad_accum,
            warmup_steps=10,
            learning_rate=lr,
            fp16=compute_dtype == torch.float16,
            bf16=compute_dtype == torch.bfloat16,
            logging_steps=10,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            seed=seed,
            output_dir=str(Path(out) / "checkpoints"),
            logging_dir=str(Path(out) / "logs"),
            run_name=Path(out).name,
            report_to="none",
            remove_unused_columns=False,
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            **steps_kw,
            **eval_kw,
        ),
    )

    import tempfile

    # Bind the actual loaded processor, runtime, inputs, loss and Trainer settings
    # before the first optimizer update or selection of a resumable checkpoint.
    with tempfile.TemporaryDirectory(prefix="unrender-processor-") as directory:
        processor.save_pretrained(directory)
        processor_files = inventory(Path(directory))
    if inventory(snapshot) != base_files:
        raise ValueError("base snapshot changed while the model was loading")
    identity = {
        "base": {"repository": base, "revision": base_revision, "files": base_files},
        "processor": {"files": processor_files},
        "source_inputs": {
            "reviews": source_reviews,
            "records": records,
            "validation_records": val_records if val_paths else [],
        },
        "hyperparameters": {
            "trainer": trainer.args.to_dict(),
            "numeric_loss_weight": numeric_loss_weight,
            "numeric_ids": list(trainer.numeric_ids),
            "lora_r": lora_r,
            "adapted_modules": adapted_modules,
            "attention_implementation": "sdpa",
            "lora_alpha": lora_alpha,
            "load_in_4bit": load_in_4bit,
            "loss_contract": "whole-optimizer-batch-weighted-ce-v1",
            "collator": {
                "class": type(trainer.data_collator).__qualname__,
                "max_length": max_seq_length,
                "image_tokens": None,
                "labels": "assistant-only",
                "truncation": False,
            },
        },
        "runtime": runtime_identity(),
        "source_code": source_identity(),
    }
    out_dir = Path(out)
    # Trainer creates its output directory during construction; an empty
    # checkpoints directory is not a checkpoint and may precede recipe sealing.
    checkpoint_root = out_dir / "checkpoints"
    if checkpoint_root.is_dir() and not any(checkpoint_root.iterdir()):
        checkpoint_root.rmdir()
    record_identity(out_dir, identity)
    if checkpoint_commit:
        checkpoint_commit()
    trainer.checkpoint_identity = identity
    trainer.checkpoint_model_format = "lora"
    trainer.checkpoint_commit = checkpoint_commit
    resume = latest(checkpoint_root, identity, model_format="lora", fp16=trainer.args.fp16)
    trainer.train(resume_from_checkpoint=str(resume) if resume else None)

    adapter_dir = out_dir / "adapter"
    model.save_pretrained(str(adapter_dir))  # LoRA adapter (small, resumable)
    processor.save_pretrained(str(adapter_dir))
    print(f"Saved LoRA adapter -> {adapter_dir}")

    if merge:
        # Reload the exact higher-precision base before merging. Never merge
        # LoRA updates into dequantized 4-bit approximations of the base weights.
        import gc

        del trainer, model
        gc.collect()
        torch.cuda.empty_cache()
        if inventory(snapshot) != base_files:
            raise ValueError("base snapshot changed before merge")
        base_model = AutoModelForImageTextToText.from_pretrained(
            snapshot,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=compute_dtype,
            device_map={"": torch.cuda.current_device()},
            attn_implementation="sdpa",
        )
        merged = PeftModel.from_pretrained(base_model, adapter_dir, local_files_only=True)
        merged = merged.merge_and_unload(safe_merge=True)
        merged.config.use_cache = True
        merged_dir = out_dir / "merged"
        merged.save_pretrained(merged_dir, safe_serialization=True)
        processor.save_pretrained(merged_dir)
        print(f"Saved merged model -> {merged_dir}")


def train(*args, **kwargs) -> None:
    """Own one local writer for the whole recipe/load/train/export lifecycle.

    Remote callers must additionally hold distributed ownership. OS file locks
    alone are not a Modal Volume lock.
    """
    import inspect

    from unrender.eval.ledger import run_owner

    arguments = inspect.signature(_train_owned).bind(*args, **kwargs)
    arguments.apply_defaults()
    from unrender.data_gen.review import require_training_sources
    from unrender.train.recipe import require_revision

    values = arguments.arguments
    require_training_sources(values["train_paths"], values["val_paths"] or [], values["data_root"])
    require_revision(values["base_revision"])
    with run_owner(Path(values["out"])):
        _train_owned(*arguments.args, **arguments.kwargs)


def main():
    p = argparse.ArgumentParser(description="LoRA fine-tune Qwen3-VL on synthetic chart->JSON.")
    p.add_argument(
        "--train", nargs="+", required=True, help="one or more chat-format train.jsonl files"
    )
    p.add_argument(
        "--val",
        nargs="+",
        default=None,
        help="validation splits for eval-loss checkpoint selection; omit for final checkpoint",
    )
    p.add_argument(
        "--val-size",
        type=int,
        default=256,
        help="cap on val records used per eval (deterministic subset)",
    )
    p.add_argument(
        "--n-evals", type=int, default=5, help="approx number of eval/save points across the run"
    )
    p.add_argument(
        "--save-total-limit", type=int, default=3, help="checkpoints to keep (best is always kept)"
    )
    p.add_argument("--out", required=True, help="output dir (adapter/ + merged/ written here)")
    p.add_argument("--base-revision", required=True, help="immutable Hub commit")
    p.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help="base model id (e.g. Qwen/Qwen3-VL-8B-Instruct for launch)",
    )
    p.add_argument(
        "--data-root", default=".", help="base directory for relative train/val split paths"
    )
    p.add_argument(
        "--labelfree-weight",
        type=float,
        default=1.5,
        help="oversample factor for label-free charts",
    )
    p.add_argument(
        "--type-weights",
        default="",
        help='per-type oversampling, e.g. "multi_line:1.5,stacked_bar:1.5"',
    )
    p.add_argument(
        "--epochs", type=float, default=1.0, help="training epochs (ignored if --max-steps > 0)"
    )
    p.add_argument(
        "--max-steps", type=int, default=0, help="cap steps (>0 overrides epochs; for smoke tests)"
    )
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=2, help="per-device batch size")
    p.add_argument("--grad-accum", type=int, default=4, help="gradient accumulation steps")
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=16)
    p.add_argument(
        "--max-seq-length",
        type=int,
        default=4096,
        help="complete input token limit; oversized examples fail without truncation",
    )
    p.add_argument(
        "--no-4bit", action="store_true", help="bf16 LoRA instead of 4bit QLoRA (needs more VRAM)"
    )
    p.add_argument(
        "--no-merge", action="store_true", help="save adapter only, skip the merged 16bit export"
    )
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
        base_revision=args.base_revision,
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
