# Preregistration — Base-vs-LoRA Gate (4B)

Date frozen: 2026-06-15 (before the base-4B control was run).

This file fixes the comparison and the decision rule **before** seeing base-model
results, so the outcome cannot be rationalized after the fact.

## Question

Did the LoRA fine-tune materially improve chart-to-data extraction over the
stock base model, measured on identical, leak-free charts?

## Fixed evaluation set

- `unrender/eval/subsets/common300.json` — 300 charts, `subset_fp=b02a6d7ad001bd9d`.
- Drawn only from the 494 charts that are held-out **test in both** the local and
  Modal splits (`common_pool_494.json`), so no chart is a Modal train/val leak
  (verified: 0 train, 0 val, 300 test against `modal_v1_split.json`).
- Stratified across all 44 `chart_type × labels_shown × density-band` cells,
  total-variation distance to the full v1 test distribution = 0.018.

## Models (identical prompt, decoder, and subset)

- **Candidate (A):** the merged LoRA at `runs/qwen3vl4b-lora/merged`
  (predictions already saved: `outputs/modal/qwen3vl4b-lora/`).
- **Control (B):** the base model the LoRA was trained on. Training used
  `FastVisionModel.from_pretrained("Qwen/Qwen3-VL-4B-Instruct", load_in_4bit=True)`,
  which Unsloth redirects to `unsloth/Qwen3-VL-4B-Instruct-unsloth-bnb-4bit` and
  whose **processor** is saved into `merged/`. The fair full-precision control is
  therefore the Unsloth mirror **`unsloth/Qwen3-VL-4B-Instruct`** pinned to
  revision **`252d592b59b0233b226875a44ac135cfa1d3f755`** (confirmed against the
  Hub on 2026-06-15: full precision — 2 safetensors shards — with its own
  preprocessor/tokenizer/chat_template), passed via `--revision`. An unpinned
  `Qwen/` HEAD is rejected as a different-processor confound.
- Decoder: greedy (`do_sample=False`, 4096-token cap) for both — the same control
  arm used for the saved LoRA predictions.

## Analysis

`python -m unrender.eval.paired_bootstrap` on `common300`: pooled cell@5% for each
model, paired chart-level bootstrap (10,000 resamples of charts, seed 0) of the
A−B difference, plus invalid-output rate and median relative error per model.

## Decision rule (all three required to conclude "fine-tuning helped")

1. **Effect size:** A beats B by **≥ 3.0 percentage points** at cell@5%.
2. **Significance:** the paired-bootstrap **95% CI of (A − B) excludes 0**.
3. **No regression:** A's invalid-output rate is **not worse** than B's.

`paired_bootstrap.py` encodes these as `MIN_GAP_PP=3.0`, CI-excludes-zero, and
A-invalid-not-worse, and prints PASS/FAIL.

## Pre-committed interpretation

- **PASS** → fine-tuning works; the gap to frontier is "more/better training."
  Proceed to the repaired-4B training runs (validation generation + checkpoint
  selection by val cell@5%, `sft_lora.py`), failure-directed synthetic data.
- **FAIL (gap < 3pp or CI includes 0)** → the fine-tune did not clearly help; the
  problem is the **recipe**, not capacity. Fix training (checkpoint selection,
  LR, target representation) before anything else. **8B stays locked.**
- **Regression (A invalid worse)** → decoding/repair must be fixed first
  (decoder selection on **Modal validation**, not test).

## Explicitly out of scope until this gate resolves

8B (control or fine-tune), decoder selection, Reducto benchmarking, and frontier
distillation. The four-way frontier table on `common300` additionally requires new
API calls (current frontier predictions cover only part of the subset).
