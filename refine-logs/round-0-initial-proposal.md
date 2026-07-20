# Research Proposal: Measure, Don't Guess — Renderer-Privileged Geometry Supervision for Exact Chart Digitization with a Small VLM

## Problem Anchor
- **Bottom-line problem**: A small VLM (Qwen3-VL-4B + LoRA) must recover the *exact numeric values* behind a chart image — especially when values are **not printed** and must be measured against the axis scale — and beat frontier VLMs (GPT-5.5, Claude Fable-5, Gemini-3.1-Pro) on this one narrow task.
- **Must-solve bottleneck**: The current LoRA (and frontier VLMs) **guess** pixel→value. It learns schema/chart-type reliably (97% schema-valid, 96.9% chart-type) but numeric precision is poor: full-set **cell@5 exact = 34.7%**, median relative value error ≈ 18.6%, worst on label-free charts and dense/stacked/horizontal bars. The model never learns *measurement*.
- **Non-goals**: Not chart QA / summarization / reasoning. Not a bigger model as the fix. Not a per-chart-type classical-CV detector pipeline. Not beating frontier on anything except exact value extraction.
- **Constraints**: ≤ ~$25 per round; Modal L4 (A100 only for 8B later); a *single* small autoregressive VLM that reuses the existing merged-model eval path; a synthetic matplotlib renderer that already knows **exact geometry** for unlimited charts; eval integrity rules from `EXPERIMENT_AUDIT.md` (pinned base control, identical decoder both arms, exact-numeric metric that excludes the label-free-pie proportion proxy, table-level dedup).
- **Success condition**: The geometry-supervised 4B beats the **pinned 4B base** on `common300` `cell@5_exact` by ≥ 3 pp with a paired-bootstrap 95% CI excluding 0 (the preregistered gate), and closes a meaningful fraction of the label-free gap to the best frontier model — with no new model architecture and the same decoder/metric in both arms.

## Technical Gap
Two camps exist (see `LITERATURE_EDGE.md`). **VLM image→table** methods (DePlot, MatCha, UniChart, ChartVLM, OneChart, and Unrender's current LoRA) emit values as text tokens — they *regress values implicitly through language modeling*, which is exactly why they miss on unlabeled charts. **Classical CV** methods (ChartOCR, LineFormer, ChartDETR) *compute* values from detected geometry + axis calibration (tick pixel↔value) and are numerically precise, but require per-chart-type detectors, explicit axis OCR, and hand-labeled geometry — they are not one unified model and don't scale.

The missing mechanism: a **single VLM that predicts the calibration geometry and lets a deterministic transform compute the values** — trained at scale on **exact** geometry labels. Naive fixes fail: more data / longer training only sharpens the same "guess values as text" objective (the loss curve was still the schema, not the measurement); a bigger model inherits the same objective; prompting can't inject a measurement prior. OneChart is the closest precedent (auxiliary numeric token + self-eval, big gains on label-free at 0.2B) but it still trains image→table text — it never supervises *dense exact geometry*, because public chart corpora don't have it. Unrender's renderer does.

## Method Thesis
- **One-sentence thesis**: Train the 4B VLM to emit a *compact, renderer-grounded geometry program* — plot-box, two (pixel,value) tick anchors per axis, and per-mark pixel positions — and compute the data table with a **fixed deterministic pixel→value transform**, supervising the geometry with privileged labels the synthetic renderer knows exactly, so the model **measures** instead of **guessing**.
- **Why this is the smallest adequate intervention**: It changes only the *training target sequence* and adds a *pure-Python deterministic decoder* (like the existing JSON repair). **No new trainable components, no architecture change**: same Qwen3-VL-4B, same LoRA, same merged-model eval path, same scorer.
- **Why timely**: It is *Learning Using Privileged Information* applied to charts in the foundation-model era — privileged geometry at train time (free from the renderer), absent at test time. It turns the synthetic data moat into a *supervision* moat that frontier models structurally cannot match.

## Contribution Focus
- **Dominant contribution**: Renderer-privileged **geometry-program supervision + deterministic pixel→value decode** for a single small VLM — converting implicit value-guessing into explicit measurement, with exact synthetic geometry labels.
- **Optional supporting contribution**: The compact geometry+table target grammar with constrained decoding (kills the invalid-JSON/repetition failures: 28/1000 today) and an OneChart-style per-series self-eval confidence used to reconcile geometry-vs-table and drive cheap test-time medianing.
- **Explicit non-contributions**: no new detector head, no new loss function, no new architecture, no per-chart-type modules, no chart-QA capability.

## Proposed Method
### Complexity Budget
- **Frozen / reused**: Qwen3-VL-4B base (pinned Unsloth mirror), the LoRA/Unsloth training code, the merged-model `hf` eval provider, the scorer + paired-bootstrap, the synthetic renderer.
- **New trainable components**: **0** (zero) — only the supervision target changes.
- **New non-trainable code**: a deterministic `geometry→values` decoder + a compact target serializer in the renderer + a constrained-decoding grammar.
- **Tempting additions intentionally excluded**: auxiliary regression heads, a separate detection network, RL/preference tuning, multi-stage detector→OCR pipelines, an 8B jump (gated until 4B passes).

### System Overview
```
image ──▶ Qwen3-VL-4B + LoRA ──▶ compact GEOMETRY-PROGRAM + TABLE sequence
                                   │
                                   ▼
              deterministic pixel→value decoder (pure Python)
                 value = v0 + (p − p0)/(p1 − p0)·(v1 − v0)        ← per-axis, log-aware
                                   │
                                   ▼
              reconcile (geometry value vs emitted table value, by confidence)
                                   ▼
                              ChartData JSON  ──▶ existing scorer
```

### Core Mechanism
- **Input / output**: image → a single text sequence with two blocks. **GEOMETRY**: `chart_type`; plot box `(x0,y0,x1,y1)` in normalized coords; per value-axis two anchor pairs `(pixel_norm, value)` (the renderer's real tick positions+values — log-flag if log axis); per mark its measurable pixel (bar: baseline_px + top_px; line/scatter point: `(px,py)`; pie wedge: start+sweep angle). **TABLE**: the categorical x-labels, series names, and a fallback y per point.
- **Training signal**: standard next-token cross-entropy on this enriched target — *no new loss*. The geometry tokens are exact renderer outputs; the model is simply taught to emit them.
- **Deterministic decode**: Python maps each mark's pixel through the predicted axis calibration to a value; for label-free charts this is the only value source. For categorical/degenerate cases (e.g. label-free pie: only proportions identifiable) it falls back to the emitted table / proportion-proxy, consistent with the audit's exact-vs-proxy split.
- **Why this is the main novelty**: the value is *computed from predicted geometry*, not emitted as a guessed token — the first time exact renderer geometry is used as dense privileged supervision inside one small VLM.

### Optional Supporting Component
- **Per-series confidence + constrained decoding**: model emits a `conf∈{low,high}` token per series (self-supervised: high iff its decoded values match the renderer table within tol at train time, à la OneChart self-eval). Used (a) to reconcile geometry-vs-table value, (b) as the dispersion signal for optional test-time self-ensembling (sample K, per-cell median — Self-Ensembling 2026). Grammar-constrained decoding guarantees the geometry+table sequence parses, removing the 28 invalid-JSON loops. *Does not create sprawl: it is one extra token + a decode constraint, not a new module.*

### Integration
Attaches entirely at the data/target layer + a post-decoder. Training: identical `sft_lora.py` call, only the assistant target string changes (renderer now serializes geometry+table). Inference: the `hf` provider is unchanged; the deterministic decoder runs in the same place as `parse_chart_json`. Both base and LoRA arms use the identical decoder and decoder config — satisfying the audit's "isolate the fine-tuning effect" (the base arm simply won't emit valid geometry, which is the point).

### Training Plan
- **Curriculum** (one knob): Stage A — labeled + easy charts (model learns the geometry grammar where values are also printed, so geometry and table agree → strong signal). Stage B — label-free + hard charts (truncated axes, K/M suffixes, dense/stacked, augmented) where geometry is the *only* value source. Oversample label-free 1.5× as today.
- **Data**: regenerate synthetic v1 with the renderer emitting geometry; train v1+v0 mixed; the test split and `common300` are frozen and table-level-deduped (audit G).
- **Losses/schedule**: unchanged from the current recipe (2e-4, LoRA r=16, ~2 epochs); only the target sequence is richer. Add a held-out **val** metric + best-checkpoint selection (the prior run had none — a `MODEL_STATUS_REVIEW` gap).

### Failure Modes and Diagnostics
- **Calibration error compounds** (a wrong tick anchor scales every value): diagnose by scoring geometry-decoded vs table-emitted values separately; mitigate via the two-anchor redundancy + confidence reconciliation + the table fallback.
- **4B can't emit reliable geometry**: diagnose on Stage-A labeled charts (geometry should match printed values); if it fails there, the privileged-supervision hypothesis is falsified cheaply before any hard-set spend.
- **Synthetic→real gap**: diagnose on Self-Ensembling's WB-ChartExtract / a small real set; mitigate with augmentation already in the pipeline.

### Novelty and Elegance Argument
Closest work: **OneChart** (aux numeric token, image→table text) and **ChartOCR** (CV keypoints + axis calibration). The exact difference: we keep OneChart's single-model elegance but replace the implicit numeric token with **explicit renderer-supervised calibration geometry + deterministic decode** (ChartOCR's "compute, don't guess"), unified in one VLM and trained on **unlimited exact geometry** rather than hand labels. One mechanism, zero new trainable parts, reuses the entire stack.

## Claim-Driven Validation Sketch
### Claim 1 (dominant): Geometry supervision raises exact-numeric accuracy over the identical base, isolating the fine-tuning effect.
- **Minimal experiment**: pinned 4B base vs geometry-LoRA on `common300`, identical decoder + metric; preregistered paired bootstrap.
- **Baseline/ablation**: (i) pinned base; (ii) current table-only LoRA (the existing arm) vs (iii) geometry LoRA — isolates geometry's contribution beyond fine-tuning per se.
- **Metric**: `cell@5_exact` (excludes label-free-pie proxy), plus median rel err; gate = gap ≥ 3pp, CI excludes 0, invalid-rate not worse.
- **Expected evidence**: geometry-LoRA > table-only LoRA > base on cell@5_exact, largest gain on **label-free** charts (mirrors OneChart's +19–29% there).

### Claim 2 (supporting): Values computed from geometry beat values emitted as text, on the same model.
- **Minimal experiment**: at inference, score the *same* geometry-LoRA two ways — (a) deterministic geometry-decoded values, (b) its own emitted table values — on label-free charts.
- **Metric**: cell@5_exact, median rel err.
- **Expected evidence**: (a) > (b) on label-free; ≈ on labeled (where both see printed numbers) — demonstrating measurement, not guessing.

## Experiment Handoff Inputs
- **Must-prove claims**: geometry-LoRA > base (gated); geometry-decode > table-emit on label-free (Claim 2).
- **Must-run ablations**: table-only LoRA vs geometry-LoRA (geometry's marginal value); geometry-decode vs table-emit; (cheap) test-time self-ensembling on/off.
- **Critical datasets/metrics**: `common300` (frozen, deduped) + label-free slice; `cell@5_exact`; paired bootstrap; optional WB-ChartExtract for transfer.
- **Highest-risk assumptions**: (1) calibration error doesn't compound worse than guessing; (2) 4B can emit reliable geometry tokens; (3) deterministic decode robust to small geometry mispredictions.

## Compute & Timeline Estimate
- Data regen with geometry: CPU, ~$0.3. Geometry-LoRA train (L4, ~2 epochs): ~$2–4. Base control + LoRA eval on common300: ~$2–4. Ablations (table-only already exists; geometry-decode vs table-emit is free re-scoring): ~$1. **Total ≈ $6–10**, within the ≤$25 round.
- Timeline: ~1 day (regen + train + eval + score).
