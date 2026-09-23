# Experiment Tracker

Method: geometry-supervised "measure, don't guess" (Qwen3-VL-4B). Plan: `EXPERIMENT_PLAN.md`. Integrity: `EXPERIMENT_AUDIT.md`.

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|--------|-----------|---------|------------------|-------|---------|----------|--------|-------|
| R003 | M0a | build geometry serializer | renderer code | — | unit tests green | MUST | TODO | bbox + all ticks + per-mark px, canonical order; prereq for R000 |
| **R000** | **M0a** | **oracle-geometry CEILING (1st gate)** | decode matched rows w/ GT pixels+ticks | matched bucket | cell@5_exact | **MUST** | **DONE ✅** | **97.9% (3dp) ≫70% → PASS**; R000_RESULT.md; decode is not the limiter |
| R001b | M0b | constrained-decode baseline ($0) | existing LoRA + JSON/count grammar | full | invalid rate, cell@5 | MUST | TODO | recovers 28 invalid; = FAIR K2 baseline |
| R00c | M0c | real-set transfer probe (pull-fwd) | base + Gemini | 10–15 real FRED/OWID | cell@5_exact | MUST | TODO | gauge transfer wall before train (~$0.5) |
| R001 | M5 | structural-error decomposition (appendix) | table-only preds vs GT | labeled slice | cardinality/assoc err | NICE | TODO | demoted — failure is mostly calibration (73% bucket) |
| R002 | M5 | decoder robustness sim (appendix) | geometry-decode vs direct | injected error | cell@5 vs error | NICE | TODO | demoted from gate |
| R004 | M1 | C0 pixel/Stage-A gate (~$2) | geometry-emission run, labeled | Stage-A | decoded-vs-printed cell@5_exact | MUST | TODO | gate ≥80% |
| R005 | M1 | **pinned base control (clears audit C/K)** | base `unsloth/Qwen3-VL-4B-Instruct` rev `252d592b…` | common300 | cell@5_exact | MUST | **DONE ✅** | **base cell@5_exact = 13.2%** (22% invalid); 300/300, pinned, provenance recorded → `outputs/modal/base4b-common300/` |
| R006 | M2 | regen v1 with geometry | renderer | v0+v1 | row counts; table-level dedup | MUST | TODO | keep test+common300 frozen |
| R007a | M2 | **Stage-A smoke (300 steps)** | geometry-LoRA, L4, 0.34ep | train v1+v0 geom | parse%, cell@5_exact | MUST | **DONE ✅** | **70% parse, cell@5_exact 9.2% (14.4% parseable)** — grammar learnable, precision not converged; `STAGE_A_RESULT.md`. NOT 8B. |
| R007 | M2 | **full geometry train (2ep)** — DECISION | geometry-LoRA, L4, ~2ep + val/best-ckpt | train v1+v0 geom | val cell@5_exact | MUST | **AWAITING GO** | ~$2-4; tests if precision climbs 14%→>36.8%. Consider numeric-token-loss co-arm + horizontal_bar fix. |
| R007b | M2 | **numeric-token-loss on the TABLE target** (strategic pivot 06-23) | table LoRA + digit-token CE up-weight (×3), val+best-ckpt | common300 | cell@5_exact | MUST | **DONE ❌ LEVER REJECTED** | **36.52% vs fair 38.18%: gap −1.59pp, 95% CI [−3.30,+0.05], P(lever>fair)=2.7%; invalid worse (5.3 vs 3.7%)**. Lever does NOT transfer to the table target (its geometry-arm win was fixing a 19%-invalid problem tables don't have). Drop it. |
| R011b | M3 | FAIR baseline ablation | table-only LoRA **re-trained w/ val+best-ckpt** (`--numeric-loss-weight 1`) | common300 | cell@5_exact | MUST | **DONE ✅ NEW BEST MODEL** | **`qwen3vl4b-table-fair` = 38.18% cell@5_exact** (valid 96.3%, labeled 44.6 / label-free 33.9) — beats old unfair anchor 36.8% AND the lever arm. vs base: **+25.19pp, CI [+22.31,+28.28], PASS**. Paired vs frontier on shared common300 ids: **gpt-5.5 +1.2pp (parity), fable-5 −5.8pp, gemini −28.3pp**. |
| R011c | M3 | 27%-bucket analysis | geometry-decode vs direct on dropped/extra-mark rows | mismatched bucket | cell@5_exact | MUST | TODO | does geometry hurt the localization-failure rows? |
| R008 | M2 | eval geometry-LoRA | geometry-LoRA merged | common300 | cell@5_exact, schema-valid | MUST | TODO | identical decoder to base |
| R009 | M3 | **C1 measure-vs-guess** | same LoRA: geometry-decode vs table-emit | 155 label-free-exact | paired bootstrap (a)−(b) | MUST | TODO | headline; CI≠0 on label-free |
| R010 | M3 | **C2 base gate (table-only LoRA done; geometry-LoRA pending)** | base vs LoRA | common300 | paired bootstrap | MUST | **DONE (table-only) ✅** | **LoRA −base = +23.84pp, CI [+21.1,+26.8], PASS** → `outputs/modal/paired_base_vs_lora.json`. Re-run with geometry-LoRA when trained. |
| R011 | M3 | B3 ablations (free re-score) | table-only vs geometry-LoRA; 2-tick vs all-tick | label-free | cell@5_exact | MUST | TODO | isolates geometry vs fine-tuning |
| R012 | M4 | **C3 external validity** | base / geometry-LoRA / Gemini-3.1-Pro | FRED+OWID N≥50 | cell@5_exact | MUST | TODO | value-level CSV GT; ≥⅓ gap |
| R013 | M5 | failure slices + readability | geometry-LoRA | per-type/density/suffix; readable vs not | cell@5_exact, invalid rate | NICE | TODO | appendix |

**First three to launch (revised by /research-review, all ≤$0.5 / no training GPU):** R003 (build geometry serializer) → **R000 (oracle-geometry ceiling — STOP if <~70%)** → R001b (constrained-decode baseline, recovers 28 invalid + fair K2 baseline). R00c real-probe (~$0.5) in parallel. These decide whether the mechanism's ceiling justifies *any* training spend.
