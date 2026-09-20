# Round 2 Review (fresh Claude subagent — context-independent, NOT cross-model)

**Overall: 7.0 / 10 — Verdict: REVISE** (up from 6.4). Reviewer read the renderer source and found a concrete headline-path bug.

## Parsed scores
| Dimension | R1 | R2 |
|---|---:|---:|
| Problem Fidelity | 8 | 8 |
| Method Specificity | 6 | 6 |
| Contribution Quality | 5 | **8** |
| Frontier Leverage | 8 | 8 |
| Feasibility | 8 | 8 |
| Validation Focus | 5 | **7** |
| Venue Readiness | 6 | 6 |
| **Overall** | 6.4 | **7.0** |

## Round-1 items: status
1. Calibration compounding — **PARTIAL**: Claim 0 injects Gaussian noise on *ground-truth* pixels → presumes correct localization/cardinality, but the documented failure (`MODEL_STATUS_REVIEW` §1–2) is *structural* (phantom categories, dropped/looping marks), not jitter. Test mis-targets the real failure; "realistic σ" is an unconstrained free parameter.
2. Claim 1 isolation — **RESOLVED** (same-weights geometry-decode vs table-emit; make label-free the claim, labeled the negative control).
3. One contribution — **RESOLVED** (reconciliation/confidence/ensembling demoted; headline is single mechanism; proxy segregated).
4. Over-determined calibration — **RESOLVED** (all ticks + LSQ + outlier reject; minor few-tick caveat — specify behavior on 3–5-tick axes, make reject-count a swept knob).
5. Real eval + scope — **PARTIAL**: rescope to "beat base + close label-free gap" is correct, but real set is disjunctive/unsized and X is uncommitted.

## NEW problems
- **N1 (CRITICAL, headline bug):** single-bar `value = fit(top_px) − fit(baseline_px)` is WRONG under a truncated axis. Verified against `render.py:43–46,74`: bars anchor at data-0, truncation is view-only (`set_ylim`), so `fit(baseline_px)=y_baseline` (floor), not 0 → under-reports by the floor on exactly the weak truncated-baseline slice. **Correct: `value = fit(top_px)`** (the tick-calibrated fit already encodes true-zero). Subtraction is correct ONLY for stacked segments (`fit(seg_top)−fit(seg_bottom)`, both interior pixels).
- **N2 (IMPORTANT):** mark→series association as free-text keys is token-fragile given documented "Country 296" phantom-category degeneration; emit marks in canonical/positional order and test association at Stage A.
- **N3 (MINOR):** headline label-free exact slice = **155** (186 label-free − 31 label-free pies); keep proxy carve-out from shrinking the headline denominator.
- **N4 (MINOR):** timeline must flag Claim 2 is blocked on the pinned base GPU run (rev `252d592b…`, audit C/K).

## Drift: NONE. Anchor preserved verbatim; scope reduction is honest, audit-forced.

<details><summary>Note</summary>Reviewer verified file paths: render.py:43-46,74,91-100; chart_specs.py:102,316; MODEL_STATUS_REVIEW.md:73-74 §2/§4; EXPERIMENT_AUDIT.md B/C/K. Same-family review (less independence weight than cross-model).</details>
