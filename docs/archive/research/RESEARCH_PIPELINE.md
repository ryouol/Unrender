# Unrender — Research Pipeline Roadmap (status → frontier-beating)

**Direction**: from current status to a small VLM that beats frontier VLMs at exact chart-image→data extraction.
**Date**: 2026-06-16 · **Mode**: synthesis (constituent stages already run this session; experiments NOT yet run — gated below).
**Reviewer backend this session**: fresh Claude subagents (per user preference; Codex used only for the initial integrity audit).

## Where we actually are
- **Phase 1–2 (data engine + eval harness)**: done.
- **Phase 3 (4B LoRA)**: trained + evaluated. `cell@5_exact` = **34.7%** (full hard set) / **36.8%** (common300). Learns schema (97%) + chart-type (96.9%) reliably; **does not** learn exact measurement.
- **This session added**: integrity audit + fixes, literature edge, a refined method, a review-hardened experiment plan, a skeptical path review, and a claim ledger. **No new GPU spent.**
- **The honest claim today** (`RESULT_TO_CLAIM.md`): "pipeline works; LoRA learns structure not measurement; numeric gap quantified — 73% of valid predictions are calibration-shaped near-misses at 8.3% median error." **"Beats frontier" / "fine-tuning helped" are UNSUPPORTED** (base control never run; integrity=fail).

## The verified ceiling (be honest about the goal)
From the independent path review (recomputed + verified):
- **P(beat best frontier = Gemini-3.1-Pro on a real out-of-renderer set) ≈ 10–15%.** The gap is ~31pp; the highest-EV levers net ~+8–12pp combined; real transfer is unproven.
- **P(beat the pinned 4B base by ≥3pp on common300) ≈ 65–75%.**
- **Therefore the realistic destination of *this* method is "a measurably better small model that closes ≥⅓ of the label-free gap," not "beats frontier."** Frontier-beating, if reachable at all, likely needs the geometry method **plus** capacity (8B) **plus** real-data adaptation — and is a stretch goal, not the base case. The roadmap below is honest about that.

## Staged path with honest gates

```
[NOW] 4B LoRA: 34.7% exact, guesses values, base never run, integrity=fail
   │
   ▼  STAGE A — Decide the bet for $0  (the single next action)
A1. Build geometry serializer (renderer emits bbox/all-ticks/per-mark px)   [no GPU]
A2. R000 oracle-geometry ceiling: decode the 712 matched rows w/ GT pixels   [$0 CPU]
        ── GATE A ──  perfect-geometry cell@5 ≥ ~70% on matched bucket?
                       NO  → geometry bet is dead; pivot to numeric-token-loss
                             + constrained decoding only (no geometry paper).
                       YES → proceed.
A3. Constrained-decode-only baseline on existing LoRA (recovers 28 invalid;   [$0]
        = the FAIR baseline). A4. real-set probe: base+Gemini on 10–15 charts  [~$0.5]
   │
   ▼  STAGE B — Validity gates (~$4–6, clears the audit's central FAIL)
B1. Stage-A geometry-emission check (4B can emit usable geometry?)            [~$2]
        ── GATE B1 ── decoded-vs-printed ≥80% cell@5_exact? else stop.
B2. PINNED base control on common300 (rev 252d592b…)  ← clears audit C/K      [~$2–4]
   │
   ▼  STAGE C — Train & decide the contribution (~$4–6)
C1. Regen v1 w/ geometry; train geometry-LoRA (+val+best-ckpt+constrained)
        + numeric-token-loss co-arm.
C2. DECISIVE: geometry-decode > own table-emit on 155 label-free-exact (CI≠0)?
        AND geometry-LoRA beats the pinned base ≥3pp (CI≠0)?
        AND survives the FAIR baseline (not just fine-tuning)?
        ── GATE C ── pass → contribution is real (paper-worthy). fail → limitation.
   │
   ▼  STAGE D — External validity (~$1–2)
D1. FRED/OWID real charts (N≥50, value-level CSV GT): geometry-LoRA vs base vs Gemini.
        ── GATE D ── positive transfer + closes ≥⅓ label-free gap? → defensible paper.
   │
   ▼  STAGE E — Escalate ONLY if A–D pass (each its own decision)
E1. 8B run — justified only after the 4B recipe passes Gate C (don't scale a broken recipe).
E2. Reducto / product comparison — only on a real chart head-to-head, same scorer.
E3. Paper (auto-review-loop → paper-writing) — scope: "geometry supervision makes a
        small VLM measurably better at exact extraction," retire "beats frontier."
```

## The single next action
**Build the geometry serializer (A1) and run R000, the $0 oracle-geometry ceiling (A2).** It either green-lights the entire bet or kills it before one dollar of GPU. Everything downstream is gated on it.

## What would actually be needed to *beat frontier* (stretch path)
Geometry supervision alone is unlikely to clear Gemini's ~31pp lead. The honest frontier-beating recipe, if pursued, stacks: (1) geometry-decode (this method) + (2) numeric-token-loss + (3) constrained decoding + (4) test-time self-ensembling + (5) capacity (8B) + (6) real-data adaptation/distillation from a frontier teacher on real charts. Even then, frontier-beating on *real* charts is ~10–15% likely. Treat "beat base + close ⅓ gap + a clean privileged-geometry paper" as the win; "beat frontier" as the moonshot.

## Artifact map (everything produced this session)
| Stage | Artifact | Verdict |
|---|---|---|
| Integrity audit | `EXPERIMENT_AUDIT.md` / `.json` + trace | FAIL-to-gate-GPU (base arm missing) |
| Audit fixes | code (8 files, 28/28 tests) + remediation | code FAILs resolved; 2 pending the base run |
| Literature | `LITERATURE_EDGE.md` | geometry edge identified (OneChart/ChartOCR gap) |
| Method | `refine-logs/FINAL_PROPOSAL.md` (+ round logs) | ~8.5 READY-for-planning |
| Plan | `refine-logs/EXPERIMENT_PLAN.md` + `EXPERIMENT_TRACKER.md` | review-revised; R000 first |
| Path review | `RESEARCH_REVIEW.md` + trace | mock NeurIPS 5/10→7; ceiling verified |
| Claims | `RESULT_TO_CLAIM.md` | aspirational=NO, honest=YES; escalation gates |
| Roadmap | `RESEARCH_PIPELINE.md` (this file) | — |

## Pipeline status (for `/research-pipeline — resume`)
- idea-discovery-equivalent (lit + method + novelty/review): **accepted** (Claude reviews).
- experiment-bridge (run experiments): **pending** — gated on Gate A (R000) + budget + the base run.
- auto-review-loop / summary / paper-writing: **pending** — require results that don't exist yet.
- **Not auto-advanced**: running experiments spends GPU money and needs your go-ahead. The pipeline correctly stops at the $0 decision gate.
