# Round 2 Refinement

## Problem Anchor (verbatim)
*(unchanged — see round-1-refinement.md)*

## Anchor Check
Original bottleneck (exact numeric measurement of unprinted values) preserved. All round-2 fixes are correctness/validity sharpenings; none change the problem. No drift.

## Simplicity Check
Dominant contribution unchanged and still singular: renderer-privileged geometry supervision + over-determined deterministic decode. Round-2 actually *simplifies* the headline decoder (delete a wrong subtraction term). No components added.

## Changes Made

### 1. FIX the truncated-bar decoder bug (N1, CRITICAL) — verified against renderer source
- **Reviewer said**: `value = fit(top_px) − fit(baseline_px)` under-reports truncated bars by the axis floor.
- **Verified**: `render.py:74` draws `ax.bar(x, row)` (default `bottom=0`, anchored at data-0); `render.py:45` truncates *view-only* via `set_lim(y_baseline, …)`. So the visible bar bottom clips to the axis floor → `fit(baseline_px)=y_baseline≠0`.
- **Action**: single-bar decode is now **`value = fit(top_px)`** (the tick-calibrated affine already encodes true-zero even when off-screen). Subtraction is retained **only** for stacked segments (`render.py:95–100`: `bottom=bottom`), where both segment pixels are interior: `value_seg = fit(seg_top_px) − fit(seg_bottom_px)`.
- **Impact**: removes a systematic error on the truncated-baseline slice (the weak 31.2% slice); strictly simpler.

### 2. Re-aim Claim 0 at the DOCUMENTED failure (localization/cardinality/structure), not Gaussian jitter (item 1, CRITICAL)
- **Reviewer said**: injecting Gaussian noise on ground-truth pixels presumes correct localization/cardinality — but `MODEL_STATUS_REVIEW` §1–2 shows the real failure is structural (phantom "Country 296", dropped/looping marks), and "realistic σ" was a free parameter.
- **Action**: Claim 0 is now a **two-stage, model-calibrated** study:
  - **0a (measure real error, $0)**: from the *existing* `outputs/modal/qwen3vl4b-lora/predictions.jsonl` on a **labeled (Stage-A) slice**, compute the model's actual per-mark pixel error, **cardinality error** (missing/extra marks), and series-association error vs renderer ground truth. This fixes the input distribution empirically instead of asserting σ.
  - **0b (decode robustness under realistic, structured error, $0)**: feed those *measured* error distributions — including **non-Gaussian structural perturbations** (drop a mark, duplicate, swap adjacent x-association, heavy-tail bias) — through the deterministic decoder; compare geometry-decode (all-tick robust vs 2-tick) to a noise-matched direct-value baseline; report cell@5_exact vs error level.
  - **Gate**: proceed to GPU only if geometry-decode dominates direct-value under the *measured* error level AND a Stage-A check shows the 4B emits geometry whose decoded values match printed values within tol on labeled charts (threshold preregistered, e.g. ≥80% Stage-A cell@5_exact).
- **Impact**: the gate now tests the failure the project actually has; can no longer pass spuriously.

### 3. Canonical/positional mark emission + Stage-A association test (N2, IMPORTANT)
- **Action**: marks are emitted in a **canonical order** (per series, left-to-right by x; series in legend order) so the (series, x) association is **positional**, not a free-text key the model must reproduce hundreds of times. Stage-A 0a additionally reports association accuracy; if low, the positional scheme is the mitigation tested before hard-set spend.
- **Impact**: reduces exposure to the documented phantom-category/looping degeneration.

### 4. Commit numeric scope + a single sized real set (item 5, N3)
- **Action**: real/out-of-renderer eval is now **one** named set — **FRED + Our-World-in-Data charts with downloadable CSV ground truth**, fixed **N ≥ 50** (WB-ChartExtract only if confirmed to have value-level CSV GT, not QA pairs). Preregistered scope claim: **"close ≥ 1/3 of the pinned-base→best-frontier label-free cell@5_exact gap"** on common300, plus *any* positive transfer on the real set (reported with honest CI). Headline label-free **exact** slice defined as **155** items (186 label-free − 31 label-free pies; pies stay in the proxy column).
- **Impact**: falsifiable scope; external-validity concern discharged with a committed N.

### 5. Few-tick robust-fit behavior (item 4 caveat) + Claim 2 dependency surfaced (N4)
- **Action**: axis fit specifies: ≥4 ticks → LSQ + reject up-to-`ceil(n/4)` worst residual ticks above k·MAD; 2–3 ticks → plain LSQ, no reject (reject-count is a swept knob in 0b). Timeline now flags **Claim 2 cannot report until the one pinned base GPU run lands** (rev `252d592b59b0233b226875a44ac135cfa1d3f755`, audit C/K).

---

## Revised Proposal (round 2)

# Measure, Don't Guess — Renderer-Privileged Geometry Supervision with Over-Determined Deterministic Decode for Exact Chart Digitization (Qwen3-VL-4B)

## Problem Anchor
*(verbatim — see round-1-refinement.md)*

## Technical Gap
*(unchanged)* VLMs guess pixel→value as text; CV methods compute from geometry but are per-type/hand-labeled/non-unified; OneChart bridges with an aux numeric token but never supervises dense exact geometry (public corpora lack it). Unrender's renderer has exact geometry for unlimited charts. **Caveat carried forward**: current errors are large/structural (not uniform miscalibration) — so the method must prove geometry-decode helps *and* that the 4B can localize marks/ticks at all; both are tested cheaply (Claim 0) before GPU.

## Method Thesis
Train the 4B to emit a compact renderer-grounded geometry program — plot box, **all** value-axis tick (pixel,value) pairs, and per-mark pixels **in canonical order** — and compute the table by a fixed **over-determined** pixel→value transform, so the model **measures** instead of **guessing**. Zero new trainable components; same model/LoRA/eval-path/scorer.

## Contribution Focus
- **Dominant (only) contribution**: renderer-privileged geometry-program supervision + over-determined deterministic decode in one small VLM.
- **Out of headline**: reconciliation, confidence token, self-ensembling, constrained decoding (hygiene). No new head/loss/architecture/detector/module.

## Proposed Method
### Complexity Budget
Frozen/reused: 4B (pinned Unsloth mirror), LoRA/Unsloth code, `hf` provider, scorer + paired-bootstrap, renderer. New trainable: **0**. New non-trainable: renderer geometry serializer; deterministic decoder (over-determined fit + per-type rules); constrained-decode grammar (hygiene). Excluded: aux head, detector, RL, multi-stage pipeline, 8B (gated), reconciliation/confidence in headline.

### System Overview
```
image ─▶ 4B+LoRA ─▶ GEOMETRY-PROGRAM (marks in canonical order) [+ TABLE for categorical/unidentifiable only]
                     │ deterministic decoder (pure Python):
                     │   fit axis from ALL ticks (LSQ + MAD-reject; log-space if log; ≥4 ticks → reject up to ceil(n/4))
                     │   per-type mark→value (below); marks positional ⇒ association needs no free-text key
                     ▼
               ChartData JSON ─▶ existing scorer (cell@5_exact; label-free pie → proxy column)
```

### Core Mechanism + per-chart-type decoder spec (corrected)
- **GEOMETRY target**: `chart_type`; plot box `(x0,y0,x1,y1)` normalized; **all** value-axis ticks `(pixel_norm, value)` (+log-flag); per mark its pixel(s) in **canonical order** (series in legend order; within series left-to-right by x).
- **Axis fit**: LSQ through all emitted ticks; log-space if log-flag; ≥4 ticks → reject up-to-`ceil(n/4)` worst residuals > k·MAD; 2–3 ticks → plain LSQ.
- **Per-type mark→value**:
  - **bar / horizontal_bar / grouped_bar**: each bar emits `top_px` + positional (series,x); **`value = fit(top_px)`** (NOT minus a baseline — bars anchor at data-0, truncation is view-only; `fit` already encodes true-zero).
  - **stacked_bar**: each segment emits `(seg_bottom_px, seg_top_px)`; `value_seg = fit(seg_top_px) − fit(seg_bottom_px)` (both interior pixels).
  - **line / multi_line / scatter**: each point emits `(px, py)` positionally; `y = fit(py)`; x = emitted label (categorical) or `fit_x(px)` (numeric x).
  - **pie**: wedge `(start,sweep)`; labeled → values iff total identifiable; **label-free → proportions = proxy column** (audit B), never in exact headline.
  - **categorical x**: emitted as text, not decoded.
- **Training signal**: next-token CE on the enriched target. No new loss.

### Optional (appendix only, never in headline)
Confidence token (OneChart-style), geometry/table reconciliation, test-time self-ensembling. Reported separately.

### Training Plan
Curriculum: Stage A (labeled+easy: geometry agrees with printed values → grammar + Claim-0 association/calibration check) → Stage B (label-free+hard: geometry is the only value source). Label-free oversampled 1.5×. Data: regenerate v1 with geometry serialized; v1+v0; frozen, table-level-deduped test + common300 (audit G). Recipe unchanged (2e-4, r=16, ~2 epochs) **+ held-out val metric + best-checkpoint selection** (prior run lacked both, `MODEL_STATUS_REVIEW` §5).

### Failure Modes and Diagnostics
- Compounding → Claim 0b σ/structured-error curve (pre-GPU).
- Mark-localization/cardinality is the true failure → Claim 0a measures it from existing predictions; Stage-A gate.
- 4B can't emit coordinates/association as text → Stage-A association+calibration check; falsified for ~$2.
- Synthetic→real → required FRED/OWID eval (N≥50).

### Novelty and Elegance
Keeps OneChart's single-model elegance; replaces the implicit numeric token with explicit renderer-supervised, over-determined calibration geometry + deterministic decode (ChartOCR "compute, don't guess"), unified in one VLM on unlimited exact geometry. One mechanism, zero new trainable parts.

## Claim-Driven Validation Sketch

### Claim 0 (GATE, CPU-only, $0): under the model's *measured* (structured, non-Gaussian) localization error, geometry-decode beats direct value-guessing — and the 4B can emit usable geometry at Stage A.
- **0a**: from existing `qwen3vl4b-lora/predictions.jsonl` (labeled slice) + renderer GT, measure real per-mark pixel error, cardinality error, association error.
- **0b**: feed those (incl. drop/duplicate/swap/bias perturbations) through the decoder; geometry-decode (all-tick-robust vs 2-tick) vs noise-matched direct-value; cell@5_exact vs error level.
- **Gate**: GPU only if geometry-decode dominates at the measured error level AND Stage-A geometry-decoded values match printed values ≥ (preregistered, e.g.) 80% cell@5_exact.

### Claim 1 (dominant): on one set of weights, geometry-decode beats the model's own emitted table — isolating "measure vs guess."
- Same geometry-LoRA, scored (a) geometry-decode vs (b) own emitted table, on the **155-item label-free-exact** slice (the claim) and labeled (negative control). Secondary context: pinned base, table-only LoRA. Metric cell@5_exact + median rel err; paired bootstrap on (a)−(b).
- Expected: (a) > (b) on label-free; ≈ on labeled.

### Claim 2 (secondary, preregistered gate — BLOCKED on base GPU run): geometry-LoRA beats the pinned 4B base on common300 (gap≥3pp, CI excludes 0, invalid not worse). Cannot report until the pinned base run (`252d592b…`) lands (audit C/K).

### Claim 3 (external validity, REQUIRED): geometry-LoRA vs base vs best frontier on FRED/OWID real charts (N≥50, value-level CSV GT). Preregistered scope: **close ≥1/3 of the base→best-frontier label-free gap** + positive real-set transfer (honest CI). Not "beats frontier."

## Experiment Handoff Inputs
- Must-prove: Claim 0 (gate); Claim 1 (geometry-decode > table-emit, label-free, same weights); Claim 3 (transfer).
- Must-run ablations: 2-tick vs all-tick-robust (Claim 0b); geometry-decode vs table-emit; table-only-LoRA vs geometry-LoRA (context).
- Critical data/metrics: common300 (frozen, deduped) + 155-item label-free-exact slice; FRED/OWID N≥50; cell@5_exact; paired bootstrap.
- Highest-risk assumptions: (1) localization/cardinality (→ Claim 0a/0b + Stage-A gate); (2) coordinate/association emission as text (→ positional scheme + Stage-A); (3) real transfer (→ Claim 3).

## Compute & Timeline
- Claim 0a/0b + Stage-A: CPU, **$0** (gates everything). Data regen w/ geometry: ~$0.3. Geometry-LoRA train (L4): ~$2–4. **Claim 2 base control + LoRA eval (BLOCKED until the pinned base run lands)**: ~$2–4. Claim 1 decode-vs-emit + table-only context: ~$1 (mostly free re-scoring). FRED/OWID eval: ~$1–2. **Total ≈ $6–11**, ≤$25.
- Order: Claim 0 (hours, gates) → regen+train → Claim 1 → Claim 2 (after base run) → Claim 3.
