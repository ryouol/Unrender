# Round 1 Review (fresh Claude subagent — context-independent, NOT cross-model)

> Reviewer backend: fresh Claude subagent (per user preference; Codex not used). This is context-independent self-family review, so it carries less independence weight than a cross-model review.

**Overall: 6.4 / 10 — Verdict: REVISE**

## Parsed scores
| Dimension | Score |
|---|---:|
| Problem Fidelity | 8 |
| Method Specificity | 6 |
| Contribution Quality | 5 |
| Frontier Leverage | 8 |
| Feasibility | 8 |
| Validation Focus | 5 |
| Venue Readiness | 6 |
| **Overall** | **6.4** |

## Action items (by priority)
1. **CRITICAL — de-risk calibration compounding cheaply.** Add a CPU-only oracle test: inject Gaussian pixel noise σ at ground-truth anchor pixels and mark pixels independently, run the deterministic decoder, plot cell@5_exact vs σ for geometry-decode vs a noise-matched direct-value model. Settles "does it compound worse than guessing" for ~$0 before GPU; also tells you how many anchors / whether robust fitting is needed. Note: `MODEL_STATUS_REVIEW` says errors are "badly wrong," not uniform miscalibration → the real failure may be mark localization, which geometry doesn't fix and adds tick-localization on top.
2. **CRITICAL — fix Claim 1 isolation.** base-vs-LoRA conflates "learned the grammar" with "learned to measure." Headline contrast must be **[geometry-LoRA decoded-from-geometry] vs [same weights, its own emitted table]** — same model/format/training, only decode path differs. table-only-LoRA is necessary but not sufficient (differs in both format and signal).
3. **CRITICAL — one contribution, not two.** Demote reconciliation + confidence token out of the headline pipeline (it can *mask* which mechanism works). Primary number = pure geometry-decode; table only for unidentifiable categorical/label-free-pie cases (reported separately, per audit B). Constrained decoding = hygiene, not contribution.
4. **IMPORTANT — over-determine calibration.** Emit all visible ticks + least-squares/robust fit, not 2 anchors (2 points fitting a 2-param line is exactly determined, NOT redundant).
5. **IMPORTANT — specify decoder per chart-type:** mark→series association, truncated-baseline + log-axis handling, categorical-x decode. Currently a one-liner hiding a TODO.
6. **IMPORTANT — promote a small real / out-of-renderer eval to REQUIRED** (synthetic-only train+test shares the generator → "learned this renderer" confound). Scope the claim to "beat pinned base + close label-free gap," not "beat frontier" (audit: N≈45, unsupported).

**Simplification:** delete reconciliation from headline (removes a confound AND a contribution); drop confidence token as a contribution; make test-time self-ensembling an optional appendix, not must-run.
**Modernization:** robust/over-determined calibration (all ticks + LSQ/RANSAC-lite) instead of 2 anchors. Otherwise toolkit already modern — do NOT add RL/aux-head/detector.
**Drift:** NONE — fixes sharpen the same anchored problem.

<details>
<summary>Full verbatim review</summary>

(Full review retained in conversation trace; key content parsed above. Reviewer relied on round-0-initial-proposal.md, MODEL_STATUS_REVIEW.md §1/§5, EXPERIMENT_AUDIT.md B/C/G/K, LITERATURE_EDGE.md.)

</details>
