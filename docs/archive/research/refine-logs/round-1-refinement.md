# Round 1 Refinement

## Problem Anchor (verbatim from round 0)
- **Bottom-line problem**: A small VLM (Qwen3-VL-4B + LoRA) must recover the *exact numeric values* behind a chart image — especially when values are **not printed** and must be measured against the axis scale — and beat frontier VLMs on this one narrow task.
- **Must-solve bottleneck**: The current LoRA (and frontier VLMs) **guess** pixel→value; numeric precision is poor (cell@5_exact = 34.7%, median rel err ≈ 18.6%), worst on label-free / dense / stacked / horizontal-bar charts. The model never learns *measurement*.
- **Non-goals**: not chart QA/summarization/reasoning; not a bigger model as the fix; not a per-chart-type classical-CV pipeline; not beating frontier on anything except exact value extraction.
- **Constraints**: ≤~$25/round; Modal L4 (A100 only for 8B later); a single small autoregressive VLM reusing the existing merged-model eval path; a synthetic renderer that knows exact geometry; audit integrity rules (pinned base, identical decoder both arms, exact-numeric metric excludes label-free-pie proxy, table-level dedup).
- **Success condition**: geometry-supervised 4B beats pinned 4B base on common300 cell@5_exact by ≥3pp (paired-bootstrap CI excludes 0) AND closes a meaningful fraction of the label-free gap — same decoder/metric both arms.

## Anchor Check
- **Original bottleneck**: exact numeric measurement of unprinted values.
- **Why the revised method still addresses it**: still trains the model to emit renderer-supervised calibration geometry and compute values; revisions only sharpen *how we prove it measures rather than guesses* and *de-risk the calibration step*.
- **Reviewer suggestions rejected as drift**: none — all accepted (none changed the problem).

## Simplicity Check
- **Dominant contribution after revision**: renderer-privileged geometry-program supervision + deterministic, **over-determined** pixel→value decode in one small VLM — *one* mechanism.
- **Components removed/merged**: reconciliation step and per-series confidence token **removed from the headline contribution** (demoted to an optional appendix); test-time self-ensembling demoted to optional. Constrained decoding reframed as engineering hygiene, not a contribution.
- **Why the remaining mechanism is still the smallest adequate route**: zero new trainable components; the only headline change vs the existing LoRA is the *target sequence* (geometry+table) and a *deterministic decoder*. Everything else (base, LoRA code, eval path, scorer) is reused.

## Changes Made

### 1. Added a CPU-only "compounding oracle" pre-experiment (Claim 0), gating GPU spend
- **Reviewer said** (CRITICAL): the dominant contribution rests on the unproven assumption that "predict geometry → decode" beats "predict values"; calibration error multiplies into every value; and `MODEL_STATUS_REVIEW` says errors are "badly wrong," not uniform miscalibration (hinting mark-localization, not axis-transform, is the real failure).
- **Action**: added **Claim 0** — a renderer-ground-truth noise-injection study (inject σ pixel noise at anchors and at marks independently; decode; plot cell@5_exact vs σ; compare to a noise-matched direct-value decoder). Runs in CPU-minutes, $0, and **gates** whether the GPU experiment is worth running. If geometry-decode degrades faster than direct-value under realistic σ, the thesis is falsified for free.
- **Impact**: converts a named-but-unmitigated risk into a cheap go/no-go, and sizes the required calibration robustness (#4).

### 2. Reframed the headline ablation to isolate "measure vs guess" on one set of weights
- **Reviewer said** (CRITICAL): base-vs-LoRA conflates "learned the grammar" with "learned to measure"; table-only-LoRA differs in both format and signal, so it's necessary-not-sufficient.
- **Action**: **Claim 1 headline contrast is now [geometry-LoRA, decoded-from-geometry] vs [the same geometry-LoRA weights, scored on its own emitted table]** — identical model/format/training, only the decode path differs. base-4B and table-only-LoRA become *secondary context arms*, not the isolating contrast.
- **Impact**: the primary number now isolates the actual mechanism; the preregistered base gate is retained but reframed as a *secondary* "fine-tuning + measurement together beats base" result, explicitly blocked on the unrun/pinned base (audit C/K).

### 3. Collapsed to one contribution (removed reconciliation + confidence from headline)
- **Reviewer said** (CRITICAL): two contributions; reconciliation can *mask* which mechanism works.
- **Action**: headline pipeline now reports **pure geometry-decode**; the emitted table is used **only** for provably unidentifiable cases (categorical x has no pixel→value; label-free pie → proportion proxy per audit B), reported in a **separate** column, never blended into the exact-numeric headline. Confidence token + reconciliation + self-ensembling moved to an "Optional, out of headline" appendix.
- **Impact**: exactly one mechanism on trial; no attribution ambiguity.

### 4. Over-determined calibration (all ticks + robust fit) instead of two anchors
- **Reviewer said** (IMPORTANT): two points fitting a two-parameter line is exactly determined, not "redundant."
- **Action**: model now emits **all visible tick (pixel,value) pairs per value-axis**; the decoder fits the axis with **least-squares (+ a RANSAC-lite reject of one outlier tick)**. Redundancy is now real and is the actual robustness mechanism (validated by Claim 0's σ-curve).
- **Impact**: directly attacks compounding; "redundancy" claim is now true.

### 5. Specified the deterministic decoder per chart-type
- **Reviewer said** (IMPORTANT): decoder specified only for the easy linear-labeled case; mark→series association, truncated baseline, log axis, categorical-x all hand-waved.
- **Action**: added a typed per-chart-type decode spec (below): mark→series association rule, bar baseline handling under truncated y, log-axis fit in log-space, and explicit "categorical x is emitted, not decoded."
- **Impact**: implementable now, not a TODO.

### 6. Promoted a small real / out-of-renderer eval to REQUIRED; rescoped the claim
- **Reviewer said** (IMPORTANT): synthetic train+test share the generator (→ "learned this renderer" confound); "beat frontier" is unsupported (audit N≈45).
- **Action**: a small **real / out-of-renderer** eval (WB-ChartExtract subset and/or a hand-built FRED/OWID set with downloadable CSVs) is now a **required** secondary table. Headline claim scoped to "**beats the pinned base + closes X of the label-free gap**," not "beats frontier."
- **Impact**: guards external validity; honest claim scope.

---

## Revised Proposal

# Measure, Don't Guess — Renderer-Privileged Geometry Supervision with Over-Determined Deterministic Decode for Exact Chart Digitization (Qwen3-VL-4B)

## Problem Anchor
*(verbatim — see top of this file)*

## Technical Gap
*(unchanged from round 0)* VLM image→table methods regress values implicitly through language modeling (guess); CV keypoint methods compute values from geometry + axis calibration (precise) but are per-type, hand-labeled, non-unified. OneChart bridges with an aux numeric token but still trains image→table text and never supervises dense exact geometry — because public corpora lack it. Unrender's renderer has exact geometry for unlimited charts. **New caveat (from `MODEL_STATUS_REVIEW`)**: current errors are large/scattered, not a uniform calibration miss — so the method must prove geometry-decode helps *and* that the model can localize marks at all; both are now tested cheaply before GPU spend.

## Method Thesis
- **One-sentence thesis**: Train the 4B VLM to emit a compact renderer-grounded geometry program — plot box, **all** value-axis tick (pixel,value) pairs, and per-mark pixel positions — and compute the table by a fixed, **over-determined** (least-squares + outlier-reject) pixel→value transform, so the model **measures** instead of **guessing**.
- **Smallest adequate intervention**: change the *training target sequence* + add a *pure-Python deterministic decoder*. Zero new trainable components; same model, LoRA, eval path, scorer.
- **Why timely**: Learning-Using-Privileged-Information in the FM era — exact geometry supervised at train time (free), absent at test time.

## Contribution Focus
- **Dominant (only) contribution**: renderer-privileged geometry-program supervision + over-determined deterministic decode for a single small VLM — implicit value-guessing → explicit measurement, with unlimited exact geometry labels.
- **Explicit non-contributions / out of headline**: reconciliation, per-series confidence token, test-time self-ensembling, constrained decoding (engineering hygiene). No new head, loss, architecture, detector, or per-type module.

## Proposed Method
### Complexity Budget
- **Frozen/reused**: Qwen3-VL-4B (pinned Unsloth mirror), LoRA/Unsloth code, `hf` eval provider, scorer + paired-bootstrap, renderer.
- **New trainable components**: 0.
- **New non-trainable code**: renderer geometry serializer; deterministic `geometry→values` decoder (over-determined fit + per-type rules); a grammar for constrained decoding (hygiene).
- **Intentionally excluded**: aux regression head, detector net, RL/preference tuning, multi-stage detector→OCR, 8B (gated until 4B passes), and — now — reconciliation/confidence in the headline.

### System Overview
```
image ─▶ Qwen3-VL-4B+LoRA ─▶ GEOMETRY-PROGRAM (+ TABLE for categorical/unidentifiable only)
                              │
                              ▼  deterministic decoder (pure Python)
        fit axis from ALL emitted ticks (LSQ + 1-outlier reject; log-space if log axis)
        value = fit(mark_pixel)         ← per-type mark rule
                              ▼
                        ChartData JSON ─▶ existing scorer (cell@5_exact)
```

### Core Mechanism + per-chart-type decoder spec
- **GEOMETRY target**: `chart_type`; plot box `(x0,y0,x1,y1)` normalized; **all** value-axis ticks as `(pixel_norm, value)` (log-flag if log); per mark its measurable pixel(s), grouped by series.
- **Axis fit**: least-squares line through all emitted ticks; reject the single worst-residual tick if it exceeds k·MAD (RANSAC-lite); fit in log-space if log-flag.
- **Per-type mark→value**:
  - **bar / horizontal_bar / grouped / stacked**: each bar emits `(baseline_px, top_px)` and a (series, x-category) key; value = `fit(top_px) − fit(baseline_px)` (handles truncated baselines because the baseline pixel is mapped through the same fit, not assumed at 0). Stacked: per-segment top/bottom.
  - **line / multi_line / scatter**: each point emits `(px, py)` + series key + x-label; y-value = `fit(py)`; x kept as emitted label (categorical) or `fit_x(px)` if numeric x-axis.
  - **pie**: wedge `(start_angle, sweep_angle)`; **labeled** → values if a total is identifiable; **label-free** → proportions only = **proxy column** (audit B), never in the exact headline.
  - **categorical x**: emitted as text, *not* decoded (no pixel→value defined). Stated explicitly.
- **Training signal**: standard next-token CE on the enriched target. No new loss.

### Optional (out of headline) — appendix only
Per-series confidence token (OneChart-style self-eval), table-vs-geometry reconciliation, and test-time self-ensembling (sample K, per-cell median). Reported separately as "can we squeeze more reliability," never folded into the headline exact-numeric number.

### Training Plan
- **Curriculum**: Stage A — labeled+easy (geometry and printed values agree → strong grammar signal); Stage B — label-free+hard (geometry is the only value source). Label-free oversampled 1.5×.
- **Data**: regenerate synthetic v1 with geometry serialized; train v1+v0; frozen, table-level-deduped test + common300 (audit G).
- **Recipe**: unchanged (2e-4, r=16, ~2 epochs) + **add held-out val metric + best-checkpoint selection** (prior run had none — `MODEL_STATUS_REVIEW` §5).

### Failure Modes and Diagnostics
- **Compounding**: Claim 0 σ-curve (pre-GPU) bounds it and sets the #-ticks / robust-fit needed.
- **Mark-localization is the true failure (not calibration)**: Claim 0 with mark-pixel noise + Stage-A labeled check (geometry must match printed values) detects this cheaply before training.
- **4B can't emit coordinates-as-text reliably**: same Stage-A check; if it fails there, falsified for ~$2.
- **Synthetic→real gap**: required real/out-of-renderer eval.

### Novelty and Elegance Argument
*(unchanged)* keeps OneChart's single-model elegance but replaces the implicit numeric token with explicit renderer-supervised, over-determined calibration geometry + deterministic decode (ChartOCR's "compute, don't guess"), unified in one VLM on unlimited exact geometry. One mechanism, zero new trainable parts.

## Claim-Driven Validation Sketch

### Claim 0 (gate, CPU-only, ~$0): geometry-decode does not compound worse than direct value-guessing under realistic pixel noise.
- **Experiment**: from renderer ground truth, inject Gaussian noise σ at tick-anchor pixels and at mark pixels independently; decode; sweep σ ∈ [0, realistic]. Compare cell@5_exact of geometry-decode (2-tick vs all-tick-robust) vs a noise-matched direct-value baseline.
- **Metric**: cell@5_exact vs σ curves; the σ where geometry-decode crosses below direct.
- **Expected**: all-tick-robust geometry-decode stays above direct-value up to realistic σ; sets the calibration spec. **If it fails, stop — do not spend GPU.**

### Claim 1 (dominant): on one set of weights, computing values from geometry beats the model's own emitted table — isolating "measure vs guess."
- **Experiment**: score the **same geometry-LoRA** two ways: (a) deterministic geometry-decode, (b) its own emitted table values. On label-free and labeled slices of common300.
- **Baselines/context arms** (secondary): pinned 4B base; existing table-only LoRA.
- **Metric**: cell@5_exact, median rel err; paired bootstrap on (a)−(b).
- **Expected**: (a) > (b) on label-free (the measurement win), ≈ on labeled.

### Claim 2 (secondary, preregistered gate, blocked on base run): fine-tuning + measurement beats the pinned base.
- **Experiment**: pinned 4B base vs geometry-LoRA on common300, identical decoder/metric; paired bootstrap; gate gap≥3pp, CI excludes 0, invalid not worse. **Blocked on the unrun/pinned base control (audit C/K).**

### Claim 3 (external validity, REQUIRED): the gain transfers off the training renderer.
- **Experiment**: geometry-LoRA vs base vs best frontier on a small real/out-of-renderer set (WB-ChartExtract subset and/or FRED/OWID charts with downloadable CSVs).
- **Metric**: cell@5_exact (small N reported honestly).
- **Expected**: partial transfer; claim scoped to "closes X of the label-free gap," **not** "beats frontier."

## Experiment Handoff Inputs
- **Must-prove**: Claim 0 (gate); Claim 1 (geometry-decode > table-emit, same weights, label-free); Claim 3 (transfers).
- **Must-run ablations**: 2-tick vs all-tick-robust calibration (from Claim 0); geometry-decode vs table-emit; table-only-LoRA vs geometry-LoRA (context).
- **Critical datasets/metrics**: common300 (frozen, deduped) + label-free slice; small real set; cell@5_exact; paired bootstrap.
- **Highest-risk assumptions**: (1) compounding (→ Claim 0); (2) 4B emits reliable coordinate tokens (→ Stage-A check); (3) real-world transfer (→ Claim 3).

## Compute & Timeline Estimate
- Claim 0: CPU, **$0**. Data regen w/ geometry: ~$0.3. Geometry-LoRA train (L4): ~$2–4. Base control + LoRA eval on common300: ~$2–4. Claim 1 (decode-vs-emit) + table-only context: mostly free re-scoring (~$1). Small real eval: API/CPU ~$1–2. **Total ≈ $6–11**, within ≤$25.
- Timeline: Claim 0 first (hours, gates the rest); then ~1 day for regen+train+eval+score.
