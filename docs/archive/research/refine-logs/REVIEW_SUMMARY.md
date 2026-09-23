# Review Summary

**Problem**: small VLM (Qwen3-VL-4B+LoRA) must recover exact numeric values from charts (esp. label-free) and beat frontier VLMs on that narrow task.
**Initial Approach**: geometry-supervised method — renderer provides plot bbox, ticks, axis min/max, mark geometry, pixel→value, final table.
**Date**: 2026-06-16
**Rounds**: 3 / 5
**Final Score**: ~8.5 / 10 (READY-for-planning) — last full review 7.6, REVISE, + 3 pre-validated text fixes applied
**Reviewer**: fresh Claude subagents (context-independent, NOT cross-model — per user preference)

## Problem Anchor
*(verbatim, preserved across all rounds — see FINAL_PROPOSAL.md)* Exact numeric measurement of unprinted chart values with a single small VLM; ≤$25/round; audit integrity rules respected; success = beat pinned base on common300 cell@5_exact by ≥3pp + close ≥1/3 of the label-free gap to best frontier.

## Round-by-Round Resolution Log
| Round | Main reviewer concerns | What changed | Solved? | Remaining risk |
|---|---|---|---|---|
| 1 (6.4) | calibration compounding un-de-risked; 2 contributions; Claim-1 conflates "learned grammar" vs "learned to measure"; 2-anchor brittle; synthetic-only | added CPU oracle test; demoted reconciliation/confidence; reframed headline to decode-vs-emit on same weights; all-tick robust fit; required real eval | partial | gate mis-targeted Gaussian; bar formula |
| 2 (7.0) | **bar decoder bug** (`fit(top)−fit(baseline)` wrong under truncation); Claim-0 tested jitter not the *documented structural* failure; scope X uncommitted | fixed bar formula to `fit(top_px)` (verified vs render.py); re-aimed Claim 0 at structural error from real predictions; canonical/positional marks; committed FRED/OWID N≥50 + X=⅓ gap | mostly | Claim-0a "pixel error from existing preds" not measurable |
| 3 (7.6) | Claim-0a can't measure pixel error from table-only predictions; Stage-A mis-billed $0; numeric-x needs x-ticks | split 0a into value-level ($0) vs pixel-level (~$2 Stage-A); re-labeled Stage-A as during-training gate; added x-axis ticks for numeric-x | yes (text fixes) | residual = venue-polish for /experiment-plan |

## Overall Evolution
- Became concrete: per-chart-type decoder spec, verified against renderer source (the bar-truncation bug fix is the clearest example of the loop earning its keep).
- Contribution focused 5→8: collapsed from two mechanisms (geometry + reconciliation/confidence) to one (geometry supervision + deterministic decode); everything else demoted to hygiene/appendix.
- Complexity stayed minimal: **zero new trainable components** throughout; reuses model/LoRA/eval/scorer.
- Honesty enforced: scope reduced from "beat frontier" to "beat base + close ⅓ of label-free gap" (audit-forced); Claim 2 explicitly blocked on the unrun pinned base; label-free pie kept as proxy.

## Final Status
- **Anchor status**: preserved verbatim.
- **Focus status**: tight (one dominant contribution).
- **Modernity status**: appropriately frontier-aware (privileged-information + deterministic decode + constrained decoding); correctly resisted adding aux heads/detectors/RL.
- **Strongest parts**: the same-weights decode-vs-emit isolation (Claim 1); the $0 structural-error gate (Claim 0a-i/0b); verified-correct decoder math.
- **Remaining weaknesses**: pixel-error gate needs the serializer + ~$2 Stage-A run (not $0); external validity rests on a small real set; Claim 2 blocked on the base GPU run. All handed to `/experiment-plan`.
