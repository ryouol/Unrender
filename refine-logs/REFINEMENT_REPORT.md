# Refinement Report

**Problem**: small VLM exact chart-value extraction (esp. label-free), beating frontier on that narrow task.
**Initial Approach**: renderer-derived geometry supervision (bbox, ticks, axis min/max, mark geometry, pixel→value, table).
**Date**: 2026-06-16 · **Rounds**: 3 / 5 · **Final**: ~8.5/10, READY-for-planning
**Reviewer backend**: fresh Claude subagents (context-independent, NOT cross-model — per user preference; Codex not used this session for refine).

## Output Files
- Final proposal: `refine-logs/FINAL_PROPOSAL.md`
- Review summary: `refine-logs/REVIEW_SUMMARY.md`
- Per-round: `round-0-initial-proposal.md`, `round-{1,2}-review.md`, `round-{1,2}-refinement.md`, `score-history.md`

## Score Evolution
| Round | PF | MS | CQ | FL | Feas | VF | VR | Overall | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 8 | 6 | 5 | 8 | 8 | 5 | 6 | 6.4 | REVISE |
| 2 | 8 | 6 | 8 | 8 | 8 | 7 | 6 | 7.0 | REVISE |
| 3 | 8 | 7 | 8 | 8 | 7 | 8 | 7 | 7.6 | REVISE |
| final | 8 | 8 | 8 | 8 | 8 | 8 | 7 | ~8.5 | READY-for-planning |

## Final Proposal Snapshot (3-bullet thesis)
- Train the 4B to emit a compact renderer-supervised **geometry program** (plot box, all axis ticks as (pixel,value), per-mark pixels in canonical order); compute values with a fixed **over-determined** pixel→value fit — measure, don't guess.
- **Zero new trainable components**: only the training *target* changes + a pure-Python deterministic decoder; reuses model/LoRA/eval/scorer.
- Validated by a $0 structural-error gate (Claim 0), a same-weights decode-vs-emit isolation (Claim 1), the preregistered base gate (Claim 2, blocked on the base run), and a required small real-set transfer (Claim 3).

## Method Evolution Highlights
1. **Collapsed two contributions to one** (reconciliation/confidence/ensembling → appendix) — biggest focus gain.
2. **Fixed a verified decoder bug**: single-bar `value = fit(top_px)` (not `−fit(baseline_px)`), confirmed against `render.py` (bars anchor at data-0, truncation view-only); subtraction reserved for stacked segments.
3. **Re-aimed the gate** at the *documented structural* failure (cardinality/association from real predictions, $0) instead of Gaussian jitter; split pixel-error measurement out as a ~$2 during-training gate.

## Pushback / Drift Log
| Round | Reviewer said | Response | Outcome |
|---|---|---|---|
| all | (none caused drift) | anchor preserved verbatim; scope *reduced* (beat-frontier → beat-base + close ⅓ gap) per audit | accepted, no drift |

## Remaining Weaknesses (handed to /experiment-plan)
- Pixel-error gate + Stage-A calibration check require the geometry serializer + a ~$2 run (not $0).
- External validity rests on a small (N≥50) real set; transfer is a hypothesis.
- Claim 2 (beat base) blocked on the pinned base GPU run (audit C/K).

## Next Steps
- **READY-for-planning** → proceed to `/experiment-plan` for the execution-ready roadmap (this is the next chain step), then the base-control GPU run, then `/run-experiment`.

## Raw Reviewer Responses
<details><summary>Rounds 1–3</summary>
Full per-round reviews retained in `round-1-review.md`, `round-2-review.md`, and the round-3 review (in conversation trace). Reviewers verified against round-N proposals, `render.py`, `MODEL_STATUS_REVIEW.md`, `EXPERIMENT_AUDIT.md`, `LITERATURE_EDGE.md`.
</details>
