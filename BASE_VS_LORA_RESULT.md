# Base-4B vs LoRA on common300 — the result that clears the audit

**Date**: 2026-06-17 · **This is the base control the audit (`EXPERIMENT_AUDIT.md`) flagged as never-run.**
Modal app `ap-d0Yo23kiUeQRT4zkGHPiUg` (pinned base, ~$2–4 L4) completed all 300 charts; scoring + paired bootstrap done locally (free).

## Setup (integrity)
- **Base**: `unsloth/Qwen3-VL-4B-Instruct`, **revision `252d592b59b0233b226875a44ac135cfa1d3f755`** (pinned — the Unsloth mirror the LoRA was trained on; the `--revision` guard now enforces this).
- **LoRA**: existing table-only merged model (`runs/qwen3vl4b-lora`).
- **Identical decoder both arms** (greedy, same harness), **same metric** (`cell@5_exact`, excludes label-free-pie proxy), **same 300 ids** (subset_fp `b02a6d7ad001bd9d`), paired by id. Provenance recorded in both `meta.json`s.

## Result
| | cell@5_exact | cell@2_exact | schema-valid | invalid | median rel err |
|---|---:|---:|---:|---:|---:|
| **base-4B (pinned)** | 13.2% | 10.2% | 78.0% | 22.0% | 50.0% |
| **LoRA (table-only)** | 36.8% | 31.1% | 97.0% | 3.0% | 16.9% |

**Paired bootstrap (N=300, 10k resamples):** LoRA − base = **+23.84 pp**, 95% CI **[+21.10, +26.79]**, P(LoRA>base)=1.000.
**Preregistered gate (PREREGISTRATION.md): PASS — fine-tuning helped.** gap≥3pp ✓ · CI excludes 0 ✓ · A-invalid-not-worse (3% vs 22%) ✓.
Artifact: `outputs/modal/paired_base_vs_lora.json`.

## What this now supports (and what it does NOT)
- ✅ **SUPPORTED**: fine-tuning the 4B (even table-only) massively beats the pinned base on exact extraction (+23.8pp, tight CI) and is 7× more reliable (3% vs 22% invalid). Audit C7/C8/C10 → supported.
- ✅ **Audit central FAIL (C/K) CLEARED**: the base arm exists, is pinned, paired, coverage-checked.
- ❌ **Still NOT supported**: that *geometry supervision* helps *beyond* table-only fine-tuning (the geometry-LoRA isn't trained yet — that's the C1 contrast). And "beats frontier" (Gemini ≈61% on the harder intersection; LoRA 36.8%) remains a non-claim.
- **Read carefully**: the base is a *weak, unselected* anchor (the audit/review flagged this). +23.8pp over a 13.2% base is a real win but a low bar; the meaningful contribution test is still geometry-LoRA vs the *fair* table-only LoRA (C1/B3).
