# Numeric-loss-on-table — plan (pre-GPU)

**Date:** 2026-06-29 · **Branch:** integrity-common300
**Strategic source:** memory UPDATE 2026-06-23 ("STRATEGIC PIVOT … chase the numeric-token-loss lever
applied to the TABLE target — starts at 36.8%, drops geometry-decode complexity — higher-EV than more
geometry"). This doc turns that pivot into a clean, fair, single-launch GPU experiment.

## The bet
The one transferable win from the geometry arm was the **numeric-token-loss lever** (geom no-lever 21.0%
→ geom+lever 27.85%; invalid 19%→6%, a 3× reliability gain). Geometry *targets* lost to plain table
fine-tuning (36.8%). So: take the lever, drop geometry, apply the lever to the **table** target that is
already winning. Question: **does numeric-token-loss on the table target beat plain table fine-tuning?**

## Why this needs code before GPU (the gap)
`sft_lora.train()` trains a fixed number of epochs and merges the **final** checkpoint — no validation, no
best-checkpoint selection. That is the exact "no val/best-ckpt" flaw the audit pinned on the 36.8%
table-LoRA (tracker R011b: *"old control was unfair"*). If we launch numeric-loss-on-table on the current
code we get another final-checkpoint, no-val model and the comparison is uninterpretable.

**Fix (this PR, CPU-only):** add `eval_dataset` (the existing `val.jsonl`, capped + unweighted) +
`eval_strategy="steps"` + `load_best_model_at_end` on `eval_loss`. Both arms then share one fair protocol;
the lever delta is clean and the absolute numbers are defensible.

## Experiment design (matched protocol, only the lever differs)
Two training runs, identical except `--numeric-loss-weight`. Both: `v1,v0` table targets, label-free×1.5,
2 epochs, seed 3407, **val + best-checkpoint (new)**, greedy eval.

| Arm | Command knob | Delivers |
|-----|--------------|----------|
| **R011b** fair table baseline | `--numeric-loss-weight 1` | the *fair* baseline the audit demanded |
| **R007b** numeric-loss table | `--numeric-loss-weight 3` | the lever on top of the same protocol |

Eval both on **common300** (`--decode table`, the frozen 300 ids), then paired bootstrap: lever−baseline,
and each−pinned-base (13.2%). Greedy everywhere → internally consistent; constrained-decode is *not* needed
to make the lever comparison fair (see below).

## Gate / decision rule
- **Lever helps** if (numeric-table − fair-table) cell@5_exact CI excludes 0 on common300 (and on the
  label-free slice), invalid not worse → adopt the lever; this becomes the headline "precision lever".
- **Fair table re-baseline** is reported regardless (clears R011b; replaces the unfair 36.8% anchor).
- **Lever null** (CI includes 0) → the lever was a geometry-arm artifact, not transferable → stop spending
  on it; fall back to the fair table baseline as the project's best model and pivot effort to the
  contamination-resistant eval set.

## Exact GPU commands (DO NOT RUN until user go)
Data + base control already on the Volume; `gen` not needed. After this PR merges:
```
# step 0: smoke now exercises the NEW val/best-ckpt path (val on, size 64) — ~$0.5.
# Run this FIRST so load_best_model_at_end is validated cheaply, not mid-paid-run.
modal run modal_train.py::smoke
# fair table baseline (R011b)  — ~$2-4 on L4
modal run --detach modal_train.py::train --out-name qwen3vl4b-table-fair --numeric-loss-weight 1
# numeric-loss table arm (R007b) — ~$2-4 on L4
modal run --detach modal_train.py::train --out-name qwen3vl4b-table-numloss --numeric-loss-weight 3
# eval both on common300 (~$1 each)
modal run --detach modal_train.py::evaluate --model runs/qwen3vl4b-table-fair/merged   --subset common300
modal run --detach modal_train.py::evaluate --model runs/qwen3vl4b-table-numloss/merged --subset common300
# pull + paired bootstrap (local, $0)
modal volume get unrender-vol outputs ./outputs/modal
python -m unrender.eval.paired_bootstrap <fair-preds> <numloss-preds>      # lever effect
python -m unrender.eval.paired_bootstrap outputs/modal/base4b-common300/predictions.jsonl <numloss-preds>
```
Both `train` runs now default `--val-files v1,v0` (best-checkpoint on eval_loss). Total ≈ **$6-10**.

## Explicitly out of scope (and why)
- **Constrained / grammar decode (R001b):** the table arm's invalid rate is already ~3% synthetic / 0% real,
  vs 19% for geometry where R001b mattered. Both arms are greedy, so its absence does **not** confound the
  lever comparison. Skipped to keep the launch clean (no new decode dependency); revisit only if invalid
  rises.
- **Huge-magnitude reading** (real_v0 population / total-CO₂ charts scored 0%, the 10⁸–10⁹ series): a
  data/representation issue (K/M/B-suffix), independent of this lever. Tracked separately.
- **8B base:** locked until the 4B fair table arm + lever land (per EXPERIMENT_PLAN budget gate).

## Code changes in this PR (all CPU/local, no GPU)
1. `unrender/train/sft_lora.py` — `train()` gains `val_paths`/`val_size`/`n_evals`/`save_total_limit`;
   builds a capped, unweighted eval dataset; sets eval+save steps and `load_best_model_at_end` on
   `eval_loss` (greater_is_better=False). No-val path unchanged (smoke stays a pure plumbing check).
   New torch-free helper `_eval_save_steps`. CLI: `--val/--val-size/--n-evals/--save-total-limit`.
2. `modal_train.py` — `train_model()` + `train` entrypoint thread `val_files` (entrypoint default `v1,v0`),
   `val_size`, `n_evals`; `smoke` now turns val on (size 64) so the eval/best-ckpt path is validated for
   ~$0.5 before any multi-hour run.
3. `tests/test_train_config.py` — CPU unit tests for `_numeric_token_ids`, `_eval_save_steps`, and
   `load_records` oversampling/val-unweighting (no torch/unsloth import).
