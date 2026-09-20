# R000 — Oracle-Geometry Ceiling Result ($0 gate)

**Date**: 2026-06-16 · `analysis/r000_oracle_ceiling.py` on `outputs/modal/qwen3vl4b-lora/predictions.jsonl` (1000 charts).
**Verdict**: ✅ **PASS** — proceed to the pinned base control + Stage-A.

## What it tested
For every chart the LoRA was scored on, regenerate its exact `ChartSpec` from its seed (`random_spec(Random(5678+idx), hard=True)`), capture the renderer's **ground-truth geometry** (`data_gen/geometry.py`), decode values deterministically (`eval/geometry_decode.py`) at several emittable precisions, score `cell@5_exact`. This is the *ceiling*: best case if the model localizes geometry perfectly at that precision. **Spec-regen mismatches: 0** (every regenerated `to_chart_data()` matched the stored GT — the mapping + capture are verified correct).

## Result — cell@5_exact (excludes label-free-pie proxy)
| frac precision | ticks | ALL | **matched (712)** | under (165) | over (95) |
|---|---|---:|---:|---:|---:|
| exact | all | 99.2% | **98.8%** | 99.9% | 100.0% |
| 4 dp | all | 99.1% | **98.7%** | 99.9% | 99.9% |
| **3 dp** | all | 98.3% | **97.9%** | 99.2% | 99.2% |
| 2 dp | all | 89.1% | **88.4%** | 89.9% | 89.6% |

**GATE (3dp ≈ 0.5px, over-determined fit, matched bucket): 97.9% ≫ 70% → PASS.**

## Interpretation
- **The deterministic decode is not the bottleneck.** Down to ~3-decimal fraction precision (≈0.5px on a hard-mode figure), perfect geometry recovers ~98% of values within 5%. Only at 2dp (coarse ~3-4px) does it dip to ~88%.
- **2-tick ≈ all-tick here** because GT ticks are exact; over-determination will matter under *noisy* emission (tested at Stage-A), not in the oracle.
- **The 27% cardinality failures are a model emission problem, not a decode problem** — the oracle hits ~99% even on the under/over buckets because it reconstructs from GT marks. So the whole bet reduces to: **can the 4B emit geometry at ~3dp precision?** → the Stage-A gate.
- **Risk relocated**: from "does the mechanism have headroom" (answered: yes, ~98%) to "can a 4B emit accurate coordinate/calibration tokens" (open, ~$2 to test at Stage-A).

## Next
Per the execution plan: (1) pinned base-4B on common300 (clears audit C/K, unblocks base-vs-LoRA), (2) Stage-A geometry-emission gate (≥80% decoded-vs-printed on labeled charts), then (3) train geometry-LoRA only if Stage-A passes.
