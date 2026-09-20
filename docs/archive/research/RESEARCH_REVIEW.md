# Research Review — Unrender's path to beating frontier VLMs

**Date**: 2026-06-16
**Reviewer**: fresh Claude subagent (senior-ML-reviewer + strategist role; context-independent, NOT cross-model — per user preference; Codex not used). Reviewer read FINAL_PROPOSAL, EXPERIMENT_PLAN, EXPERIMENT_AUDIT, MODEL_STATUS_REVIEW, LITERATURE_EDGE, and re-computed the failure decomposition from the 1000 saved predictions.
**Trace**: `.aris/traces/research-review/2026-06-16_run02/`
**Scope**: holistic strategic go/no-go over the whole path (audit + method + plan), not a method micro-review.

## The linchpin finding (independently verified)
The LoRA's errors split into two populations (recomputed by me from `predictions.jsonl` — matches the reviewer):

| Bucket | rows (of 972 valid) | cell@5_exact | median rel err |
|---|---:|---:|---:|
| **cardinality-matched** | **712 (73%)** | **44.9%** | **8.3%** |
| dropped marks (under) | 165 | 13.2% | 52.0% |
| extra marks (over) | 95 | 20.1% | 54.8% |
| invalid ("loops") | 28 (2.8%) | 0% | — |

Cardinality blow-up among valid rows = **0**. So the "phantom-category / Country-296" pathology is confined to the 2.8% invalid outputs — NOT pervasive. **The EV is the 73% calibration-shaped majority (8.3% median error, just outside the 5% tol) — exactly what geometry-decode targets.** The 27% dropped/extra-mark bucket is localization failure geometry does not fix.

## Verdict on the bet
**Sound enough to test, but more sound on the majority and exactly as fragile on the minority as feared; the headline "beats frontier" thesis is not what the evidence will support.** The decoder math is verified correct against `render.py` (bars anchor at data-0; `value = fit(top_px)`).

## Kill shots (ranked by probability; whether the plan caught them early)
1. **K1 — synthetic→real transfer fails (~45%)**: tested LAST in the original plan → **now pulled forward** (M0c real probe, $0.5).
2. **K2 — gain is fine-tuning/grammar, not geometry (~35%)**: the original B3 table-only control was unfair (no val-selection/grammar) → **now re-run as a fair baseline** (R011b).
3. **K3 — frontier capacity wall (~30% to beat frontier; ~10% to beat base)**: goalposts already (correctly) moved to "beat base + close ⅓ gap."
4. **K4 — 4B can't emit usable geometry (~30%)**: caught cheaply by Stage-A gate (~$2).
5. **K5 — calibration compounds on the bad bucket (~20%)**: partially caught; now also probed by R011c (27%-bucket analysis).

## Honest ceiling (verified)
- P(beat best frontier = Gemini on a real set): **~10–15%** (31pp gap; transfer unproven).
- P(beat pinned base by ≥3pp on common300): **~65–75%** (matched-bucket headroom + val-selection + grammar that the prior run lacked).
- **Defensible paper claim**: *"Renderer-privileged geometry supervision + deterministic decode gives a +Xpp cell@5_exact gain over an identically-trained, identically-decoded table-output baseline on label-free charts (same weights, paired-bootstrap CI excludes 0), and closes ≥⅓ of the small-model→frontier gap; zero new trainable parameters."* NOT "small model beats frontier" — retire that framing (README).

## Interventions ranked by expected cell@5-lift-per-dollar
1. **Numeric-token loss weighting** (+2–5pp, ~$3) — attacks the 73% near-miss bucket; promote to co-headline (was "second-line").
2. **Constrained decoding alone** (recovers 2.8% invalid + bounds phantom bucket, ~$0) — run first, alone, as the baseline-lifter and the fair K2 control.
3. **Geometry-decode (the proposed method)** (+3–8pp, ~$4–6) — the novel bet; strong on majority, neutral on minority.
4. **Test-time self-ensembling** (+2–4pp, ~$2–4) — orthogonal booster, but inflates inference cost → appendix, CUT from headline.
5. **Targeted hard data** (+1–3pp, ~$1–2) — attacks weak slices.

## Mock NeurIPS review
- **Score 5/10 (borderline), confidence 4/5.** Strengths: novel privileged-info-for-charts, strong hygiene (pinned base, paired bootstrap, exact-vs-proxy split), clean same-weights isolation, zero new params. Weaknesses: mechanism targets only ~73% of error; contribution confounded with grammar+val-selection unless the fair baseline is run; transfer tested last; frontier comparison underpowered (N≈45); single seed/size.
- **→7 (accept-ish) requires**: (i) oracle-geometry ceiling showing real headroom; (ii) geometry still wins over a *fair* baseline (same recipe+grammar), CI≠0; (iii) positive real-set transfer with absolute numbers (N≥50); (iv) 27%-bucket analysis showing geometry doesn't degrade cardinality rows.

## Ranked go/no-go (applied to EXPERIMENT_PLAN.md / TRACKER)
1. **R000 oracle-geometry ceiling ($0, NEW first gate)** — STOP if perfect-geometry decode < ~70% on the matched bucket.
2. Constrained-decode-only baseline ($0) — fair K2 baseline + recovers invalids.
3. Real-set probe ($0.5) — transfer wall height before train.
4. Stage-A emission gate (~$2) → pinned base control (~$2–4, clears audit C/K).
5. Train geometry-LoRA + numeric-token-loss co-arm.
6. Decisive: decode-vs-emit (C1) + base bootstrap (C2) + fair-baseline ablation + 27%-bucket analysis.
7. Full real eval (C3). CUT self-ensembling to appendix; DEMOTE structural-noise sim to appendix.

## Claims matrix (what's sayable under each outcome)
| If… | Then claim |
|---|---|
| R000 oracle < 70% | mechanism dead; pivot to numeric-loss + constrained decoding only; no geometry paper |
| C1 (a)>(b) label-free CI≠0 AND survives fair baseline | "geometry supervision carries measurement signal" — core contribution stands |
| C1 holds but C2 base gap <3pp | method helps decode but not enough vs base; report as negative/limitation |
| C2 ≥3pp but C3 real transfer ≈0 | "improves synthetic exact extraction; does not transfer" — scoped limitation |
| C2 ≥3pp AND C3 closes ≥⅓ gap | the target paper: small-VLM exact-extraction method, frontier-beating as aspiration |
| beats Gemini on real (≤15% likely) | the dream headline — only then is "beats frontier" sayable |

## Status
Plan + tracker updated with this re-ranking. The single most decisive next action is **R000 (oracle-geometry ceiling, $0)** — it can kill or green-light the whole bet before any GPU spend.
