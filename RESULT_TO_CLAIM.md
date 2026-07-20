# Result-to-Claim Verdict — Unrender (common300 base-vs-LoRA)

**Date**: 2026-06-16
**Judge**: consolidated from independent reviews — the cross-model Codex audit (`EXPERIMENT_AUDIT.json`, claims C1–C10) + the fresh-Claude path review (`RESEARCH_REVIEW.md`, verified ceiling + claims matrix). No new Codex call (per user preference; heavy judgment already done independently — avoiding redundant adjudication).
**Evidence pre-check**: `evidence_check.py` returned `value_not_found` ×3 — a **false negative** (it can't traverse nested `tracks/0.05/metrics`); direct read confirms the cited numbers are real: full `cell_accuracy`=0.3483 / `cell_accuracy_exact`=0.3471; common300 =0.3683 / 0.3680. Evidence EXISTS.
**Integrity**: `EXPERIMENT_AUDIT.json` `integrity_status = fail` (base arm never run) → per protocol, **confidence downgraded to LOW** and base-vs-LoRA claims carry **[INTEGRITY CONCERN]**.

## Headline verdict (UPDATED 2026-06-17 — base control now RUN)
- *"the table-only 4B LoRA beats the pinned base / fine-tuning helped"* → **claim_supported: YES** (base run done: LoRA +23.84pp on common300 cell@5_exact, 95% CI [+21.10,+26.79], invalid 3% vs 22%; preregistered gate PASS — `BASE_VS_LORA_RESULT.md`). **Audit central FAIL CLEARED.**
- *"the 4B LoRA learns schema/chart-type reliably but NOT exact numeric measurement, gap quantified"* → **claim_supported: YES** (97% schema-valid, cell@5_exact 34.7%; 73% of valid at 8.3% median error).
- *"GEOMETRY supervision helps beyond table-only fine-tuning"* → **NOT YET TESTED** (geometry-LoRA untrained; the C1 contrast is the real contribution test; R000 shows decode ceiling ~98%, so de-risked but unproven on a trained model).
- *"small model beats frontier"* → **claim_supported: NO** (Gemini ≈61% on the harder intersection vs LoRA 36.8%; common300 frontier coverage N≈45). Note the base is a weak/unselected anchor, so +23.8pp over it is a real-but-low-bar win.

## Per-claim ledger (consolidated)
| Claim | Status | Basis |
|---|---|---|
| LoRA full-set cell@5_exact = 34.7% (all=34.8%) | ✅ supported | report.json verified |
| LoRA common300 cell@5_exact = 36.8% | ✅ supported | report.common300.json verified |
| common300 leak fixed (id-level AND data-table level) | ✅ supported | audit G + table-dedup test passes |
| pie label-free correctly separated as proportion proxy | ✅ supported | audit B remediation; metrics split |
| failure decomposition (73% matched @ 8.3% err / 27% cardinality / 2.8% loops) | ✅ supported | independently recomputed (RESEARCH_REVIEW.md) |
| frontier comparison (vs Gemini/GPT/Claude) | ⚠️ qualified | intersection-only, N≈45 — not citable as general |
| **base-vs-LoRA delta / "fine-tuning helped"** | ❌ unsupported | **base arm never run** (audit C/K) |
| **"small model beats frontier"** | ❌ unsupported | N≈45; verified P≈10–15% on real; retire framing |
| geometry-supervised method gains | ⏳ untested | method not built/run yet (plan M0–M3) |
| reproducibility of base/LoRA comparison | ❌ unsupported | until pinned base run + provenance recorded |

## What evidence is needed before each escalation
**Before an 8B run** — do NOT scale until the 4B recipe is proven:
1. R000 oracle-geometry ceiling ≥~70% on the matched bucket ($0 — else the mechanism is dead and 8B won't save it).
2. C2: 4B geometry-LoRA beats the **pinned** base on common300 by ≥3pp, paired-bootstrap CI excludes 0.
3. C1: geometry-decode > the model's own table-emit on the 155 label-free-exact slice, vs a **fair** baseline (same val-selection + grammar). Only after these does 8B's extra cost have a justified hypothesis.

**Before a Reducto (commercial) comparison**:
1. A **real, out-of-renderer** eval set (FRED/OWID, N≥50, value-level CSV GT) — synthetic common300 is not a valid basis for a product/competitor comparison.
2. Run Reducto + Unrender + frontier on the *same* real charts, same scorer. Report cell@5_exact with honest CI. (Reducto is a real-document parser; only a real-chart head-to-head is meaningful.)

**Before paper claims**:
1. C1 (geometry carries measurement signal, fair baseline, CI≠0) + C2 (beats pinned base) + C3 (real transfer, N≥50) + the novelty/27%-bucket ablations.
2. Scope the claim to *"renderer-privileged geometry supervision makes a small VLM measurably better at exact extraction; closes ≥⅓ of the label-free gap; zero new trainable params"* — NOT "beats frontier." (Mock NeurIPS 5→7 path in RESEARCH_REVIEW.md.)

**Before product claims**:
1. Diverse real-world eval (multiple sources, readability-controlled — report full vs human-readable subset), latency/cost per chart, and a calibrated reliability/confidence signal (OneChart-style + self-ensembling appendix).
2. Synthetic numbers support none of the above — product claims need the real-world distribution.

## Routing
- Verdict on the *current* aspirational claim = **NO / unsupported** → do not commit "beats frontier" or "fine-tuning helped" anywhere (retire README framing — already softened).
- Verdict on the *honest* claim = **YES** → "pipeline works; LoRA learns structure not measurement; numeric gap quantified and decomposed."
- **Next action (single, decisive, $0)**: R000 oracle-geometry ceiling. It green-lights or kills the geometry bet before any GPU spend. Then M1 pinned base control (clears the audit's central FAIL and unblocks C2).
- Confidence: **LOW** (integrity=fail until the base run lands). No research-wiki present → wiki update skipped. No Codex trace (no Codex call made).
