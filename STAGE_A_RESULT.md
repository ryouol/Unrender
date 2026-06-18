# Stage-A Geometry Gate — Result (300-step smoke)

**Date**: 2026-06-18 · model `qwen3vl4b-geom-smoke` (geometry-supervision LoRA, **max_steps=300 ≈ 0.34 epoch**), eval geometry-decode on common300 (same 300 charts as base/table-LoRA).

## Numbers
| metric | geom-smoke (300 steps) | table-LoRA (2 ep) | base-4B | R000 ceiling |
|---|--:|--:|--:|--:|
| parse/valid rate | 70% | 97% | 78% | — |
| cell@5_exact (all) | **9.2%** | 36.8% | 13.2% | 98% |
| cell@5_exact (parseable-only) | **14.4%** | — | — | — |
| labeled / label-free | 8.7% / 9.7% | 41.5% / 33.8% | 14.2% / 12.2% | — |

Per type (parse% , cell@5_exact): multi_line 86%/15.0 · grouped_bar 71%/13.4 · line 72%/8.1 · bar 58%/5.7 · stacked_bar 70%/5.1 · horizontal_bar **36%/4.2** · pie 100%/0.0 (proxy-excluded).

## Read (the gate's three questions)
1. **Can it parse the grammar?** ✅ partially — 70% valid at 300 steps (up to 86% multi_line, 100% pie), structurally-correct ticks+marks (real calibration like `t:[[0.14,0.0],[0.266,200.0],…]`). Grammar is clearly learnable and rising.
2. **Are coordinates close enough?** ❌ not yet — 14.4% even where it parses. The model emits *plausible but imprecise* fractions; precision (the hard visual-localization skill) hasn't converged at 0.34 epoch.
3. **Does it beat table-LoRA (36.8%)?** ❌ no (9.2%) — and below base (13.2%) — but this is a 7×-undertrained smoke vs a 2-epoch model.

## Interpretation
Normal trajectory: **grammar learns fast, precision comes with training.** The smoke confirms the mechanism is learnable and structurally sound; it does NOT yet test converged precision. R000 proved perfect geometry → 98%, so the ceiling is intact; the open question is purely whether full training closes the emission-precision gap.

**Specific weaknesses to address:** horizontal_bar is degenerate (36% parse, marks collapse to the box edge — `ax:"x"` localization), and bar/stacked precision lag. Levers: full 2-epoch train, numeric-token-loss weighting on the fraction tokens, constrained decoding (lifts the 70%→ parse), and a horizontal_bar-specific check.

## Decision (NOT 8B)
Borderline-but-learnable. The decisive, cheap next test is the **full 2-epoch geometry train (~$2–4)** — it directly answers whether precision climbs from ~14% toward/past 36.8%. If it lands well short, the levers above (esp. numeric-token loss + horizontal_bar fix) come before any scale-up.
