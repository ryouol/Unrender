# Research Proposal: Measure, Don't Guess — Renderer-Privileged Geometry Supervision with Over-Determined Deterministic Decode for Exact Chart Digitization (Qwen3-VL-4B)

*Refined over 3 review rounds (fresh-Claude reviewer; score 6.4 → 7.0 → 7.6 → ~8.5 READY-for-planning). Reviewer was same-model-family (context-independent, not cross-model).*

## Problem Anchor
- **Bottom-line problem**: a small VLM (Qwen3-VL-4B + LoRA) must recover the *exact numeric values* behind a chart image — especially when values are **not printed** and must be measured against the axis scale — and beat frontier VLMs on this one narrow task.
- **Must-solve bottleneck**: the current LoRA (and frontier VLMs) **guess** pixel→value; numeric precision is poor (cell@5_exact = 34.7%, median rel err ≈ 18.6%), and errors are large/structural (phantom categories, repetition loops), worst on label-free / dense / stacked / horizontal-bar charts.
- **Non-goals**: not chart QA/summarization/reasoning; not a bigger model as the fix; not a per-chart-type CV pipeline; not beating frontier on anything except exact value extraction.
- **Constraints**: ≤~$25/round; Modal L4 (A100 only for 8B later); a single small autoregressive VLM reusing the existing merged-model eval path; a synthetic renderer that knows exact geometry; audit integrity rules (pinned base, identical decoder both arms, exact-numeric metric excludes label-free-pie proxy, table-level dedup).
- **Success condition**: geometry-supervised 4B beats the pinned 4B base on common300 cell@5_exact by ≥3pp (paired-bootstrap CI excludes 0) **and** closes ≥1/3 of the base→best-frontier label-free gap — same decoder/metric both arms.

## Technical Gap
Three camps (see `LITERATURE_EDGE.md`): (1) **VLM image→table** (DePlot/MatCha/UniChart/ChartVLM/OneChart + the current LoRA) regress values implicitly as text → guess, weakest unlabeled; (2) **CV keypoint** (ChartOCR/LineFormer/ChartDETR) compute values from geometry + axis calibration → precise but per-type, hand-labeled, non-unified; (3) **OneChart** bridges with an aux numeric token but still trains image→table text and never supervises **dense exact geometry**, because public corpora lack it. Unrender's renderer has exact geometry for unlimited charts. Caveat from `MODEL_STATUS_REVIEW`: errors are structural, not uniform miscalibration — so the method must prove both that geometry-decode helps *and* that the 4B can localize marks/ticks; both are tested cheaply (Claim 0) before committing GPU.

## Method Thesis
Train the 4B to emit a compact renderer-grounded **geometry program** — plot box, **all** axis tick (pixel,value) pairs, and per-mark pixels **in canonical order** — and compute the table by a fixed **over-determined** pixel→value transform, so the model **measures** instead of **guessing**. Zero new trainable components; same model/LoRA/eval-path/scorer. This is Learning-Using-Privileged-Information for charts: exact geometry supervised at train time (free from the renderer), absent at test time.

## Contribution Focus
- **Dominant (only) contribution**: renderer-privileged geometry-program supervision + over-determined deterministic decode in one small VLM.
- **Out of headline** (appendix/hygiene): reconciliation, per-series confidence token, test-time self-ensembling, constrained-decode grammar. No new head/loss/architecture/detector/module.

## Proposed Method
### Complexity Budget
Frozen/reused: Qwen3-VL-4B (pinned Unsloth mirror), LoRA/Unsloth code, `hf` provider, scorer + paired-bootstrap, renderer. New trainable: **0**. New non-trainable: renderer geometry serializer; deterministic decoder (over-determined fit + per-type rules); constrained-decode grammar (hygiene, bounds cardinality). Excluded: aux head, detector, RL, multi-stage pipeline, 8B (gated), reconciliation/confidence in headline.

### System Overview
```
image ─▶ 4B+LoRA ─▶ GEOMETRY-PROGRAM (marks in canonical order) [+ TABLE for categorical/unidentifiable only]
                     │ deterministic decoder (pure Python):
                     │   fit each axis from ALL its ticks (LSQ + MAD-reject; log-space if log;
                     │     ≥4 ticks → reject ≤ceil(n/4) worst; 2–3 ticks → plain LSQ; ticks must bracket marks)
                     │   per-type mark→value (below); marks positional ⇒ association is order, not free-text
                     ▼
               ChartData JSON ─▶ existing scorer (cell@5_exact; label-free pie → proxy column)
```

### Core Mechanism + per-chart-type decoder spec
- **GEOMETRY target**: `chart_type`; plot box `(x0,y0,x1,y1)` normalized; **all value-axis ticks** `(pixel_norm, value)` (+log-flag); **for numeric-x line/scatter, also all x-axis ticks** `(pixel_norm, value)`; per mark its pixel(s) in **canonical order** (series in legend order; within series left-to-right by x).
- **Axis fit**: LSQ through all emitted ticks (per axis); log-space if log-flag; ≥4 ticks → reject ≤`ceil(n/4)` worst residuals > k·MAD; 2–3 ticks → plain LSQ. Emitted ticks must **bracket** the marks (else extrapolation error grows — a diagnostic, not a silent failure).
- **Per-type mark→value** (corrected & verified against `render.py`):
  - **bar / horizontal_bar / grouped_bar**: each bar emits `top_px` + positional (series,x); **`value = fit(top_px)`** — no baseline subtraction (bars anchor at data-0, truncation is view-only via `set_lim`, so the tick-calibrated `fit` already encodes true-zero even off-screen).
  - **stacked_bar**: each segment emits `(seg_bottom_px, seg_top_px)`; `value_seg = fit(seg_top_px) − fit(seg_bottom_px)` (both interior pixels — the only case where subtraction is correct).
  - **line / multi_line / scatter**: each point emits `(px, py)` positionally; `y = fit_y(py)`; x = emitted label (categorical) **or** `fit_x(px)` using the x-axis ticks (numeric x).
  - **pie**: wedge `(start,sweep)`; labeled → values iff total identifiable; **label-free → proportions = proxy column** (audit B), never in the exact headline.
  - **categorical x**: emitted as text, not decoded.
- **Training signal**: next-token CE on the enriched target. No new loss.

### Training Plan
Curriculum: **Stage A** (labeled+easy: geometry agrees with printed values → grammar + the during-training calibration/association gate) → **Stage B** (label-free+hard: geometry is the only value source). Label-free oversampled 1.5×. Data: regenerate v1 with geometry serialized; train v1+v0; frozen, table-level-deduped test + common300 (audit G). Recipe unchanged (2e-4, r=16, ~2 epochs) **+ held-out val metric + best-checkpoint selection** (prior run lacked both).

### Failure Modes and Diagnostics
- **Compounding** (anchor error scales every value) → Claim 0b structured-error curve (pre-commit), all-tick robust fit.
- **Mark localization / cardinality is the true failure** → Claim 0a-i measures cardinality+association error $0 from existing predictions; **cardinality blow-up → constrained-decode grammar bound** (the grammar, not positional order, caps phantom marks).
- **4B can't emit coordinates as text** → Stage-A geometry-emission check (decoded values vs printed values); falsified for ~$2 before hard-set spend.
- **Synthetic→real gap** → required FRED/OWID eval (N≥50).

### Novelty and Elegance
Keeps OneChart's single-model elegance; replaces the implicit numeric token with explicit renderer-supervised, over-determined calibration geometry + deterministic decode (ChartOCR's "compute, don't guess"), unified in one VLM trained on unlimited exact geometry. One mechanism, zero new trainable parts, reuses the whole stack.

## Claim-Driven Validation Sketch

### Claim 0 (GATE before GPU): under the model's *real, structured* error, geometry-decode beats direct value-guessing — and the 4B can emit usable geometry.
- **0a-i (value-level, $0 from existing `qwen3vl4b-lora/predictions.jsonl`)**: measure cardinality error (missing/extra marks) and series-association error vs renderer GT on the labeled slice. *(Pixel error is NOT derivable here — current predictions are table-only with no pixel fields.)*
- **0a-ii (pixel-level, needs the geometry serializer + a small Stage-A geometry-emission run, ~$2)**: measure real per-mark/tick pixel-localization error on the labeled slice.
- **0b (decoder robustness, $0 given 0a)**: feed the *measured* distributions — structural perturbations (drop/dup/swap/heavy-tail) from 0a-i, pixel noise from 0a-ii — through the deterministic decoder; geometry-decode (all-tick-robust vs 2-tick) vs noise-matched direct-value; cell@5_exact vs error level.
- **Gate**: proceed to full training only if geometry-decode dominates direct-value at the measured error level (0b) AND the Stage-A run shows decoded values match printed values ≥ (preregistered) 80% cell@5_exact. *(Note: the value-level half is genuinely pre-GPU/$0; the pixel/Stage-A half is a ~$2 during-training checkpoint gate, not $0.)*

### Claim 1 (dominant): on one set of weights, geometry-decode beats the model's own emitted table — isolating "measure vs guess."
- Same geometry-LoRA weights, scored (a) geometry-decode vs (b) its own emitted table, on the **155-item common300 label-free-exact slice** (= 186 label-free − 31 label-free pies; re-score on those ids) — this is the claim; labeled slice = negative control. Secondary context arms: pinned base, table-only LoRA. Metric cell@5_exact + median rel err; paired bootstrap on (a)−(b).
- Expected: (a) > (b) on label-free; ≈ on labeled.

### Claim 2 (secondary, preregistered gate — BLOCKED on the base GPU run): geometry-LoRA beats the pinned 4B base on common300 (gap≥3pp, CI excludes 0, invalid not worse). Cannot report until the pinned base control (`unsloth/Qwen3-VL-4B-Instruct`, rev `252d592b59b0233b226875a44ac135cfa1d3f755`) is run (audit C/K).

### Claim 3 (external validity, REQUIRED): geometry-LoRA vs base vs best frontier on FRED + OWID real charts (N≥50, value-level CSV GT; WB-ChartExtract only if it has value-level GT). Preregistered scope: **close ≥1/3 of the base→best-frontier label-free gap** on common300 + any positive real-set transfer (honest CI). NOT "beats frontier."

## Experiment Handoff Inputs
- **Must-prove**: Claim 0 gate (0a-i $0 + 0a-ii/0b ~$2); Claim 1 (geometry-decode > table-emit, label-free, same weights); Claim 3 (transfer).
- **Must-run ablations**: 2-tick vs all-tick-robust (Claim 0b); geometry-decode vs table-emit; table-only-LoRA vs geometry-LoRA (context).
- **Critical data/metrics**: common300 (frozen, deduped) + 155-item label-free-exact slice; FRED/OWID N≥50; cell@5_exact; paired bootstrap.
- **Highest-risk assumptions**: (1) localization/cardinality (→ Claim 0a/0b + Stage-A gate); (2) coordinate/association emission as text (→ positional scheme + grammar bound + Stage-A); (3) real transfer (→ Claim 3).

## Compute & Timeline
- **Claim 0a-i + structural 0b**: CPU, **$0** (genuine pre-GPU gate on the structural failure). **Claim 0a-ii + Stage-A emission**: ~$2 (needs the geometry serializer; during-training checkpoint gate). Data regen w/ geometry: ~$0.3. Geometry-LoRA train (L4): ~$2–4. **Claim 2 base control + LoRA eval (BLOCKED until the pinned base run lands)**: ~$2–4. Claim 1 decode-vs-emit + table-only context: ~$1 (mostly free re-scoring). FRED/OWID eval: ~$1–2. **Total ≈ $8–13**, ≤$25.
- Order: 0a-i + structural 0b ($0) → build serializer → 0a-ii/Stage-A (~$2 gate) → regen + train → Claim 1 → Claim 2 (after base run) → Claim 3.
