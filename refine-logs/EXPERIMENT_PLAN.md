# Experiment Plan

**Problem**: a small VLM (Qwen3-VL-4B + LoRA) must recover *exact numeric values* from charts (especially label-free, where values must be measured against the axis), and beat the pinned base + close ≥⅓ of the label-free gap to the best frontier VLM.
**Method Thesis**: train the 4B to emit a compact renderer-supervised **geometry program** (plot box → all axis ticks as (pixel,value) → per-mark pixels in canonical order) and compute values via an **over-determined** deterministic pixel→value fit — *measure, don't guess*. Zero new trainable components.
**Date**: 2026-06-16
**Source**: `refine-logs/FINAL_PROPOSAL.md` (3-round refined, ~8.5 READY-for-planning); integrity gated by `EXPERIMENT_AUDIT.md`.

> ## Strategic Revision (post `/research-review`, 2026-06-16 — VERIFIED)
> A holistic review re-computed the LoRA's failure structure from the 1000 saved predictions (verified independently — see `RESEARCH_REVIEW.md`):
>
> | Bucket | rows (of 972 valid) | cell@5 | median rel err |
> |---|---:|---:|---:|
> | **cardinality-matched** | **712 (73%)** | **44.9%** | **8.3%** |
> | dropped marks (under) | 165 | 13.2% | 52.0% |
> | extra marks (over) | 95 | 20.1% | 54.8% |
> | invalid (the "loops") | 28 (2.8%) | 0% | — |
>
> **Implication:** the EV lives in the **73% calibration-shaped majority** (8.3% median error — just outside the 5% tol), which is *exactly* what geometry-decode targets. The "phantom-category" loops are confined to 2.8% (cardinality blow-up among valid = **0**) — the proposal over-weighted them. The 27% dropped/extra-mark bucket is localization failure geometry does **not** fix.
>
> **Changes to this plan (applied below):**
> 1. **ADD R000 — $0 oracle-geometry ceiling (NEW FIRST GATE):** decode the 712 matched rows using renderer-GT mark pixels + GT ticks; if perfect-geometry decode < ~70% cell@5 on the matched bucket, **STOP — mechanism ceiling too low**, before any GPU. (Needs the serializer R003; ~$0 CPU after that. Strictly more decisive than the old B0 structural sim.)
> 2. **ADD — constrained-decode-only baseline ($0):** recovers the 28 invalid rows AND establishes the *fair* fine-tuning baseline (the old B3 table-only control had no val-selection/grammar → would over-credit geometry). K2 fix.
> 3. **ADD co-headline arm — numeric-token loss weighting (~$3):** review ranks this highest lift-per-dollar (+2–5pp) on the matched bucket; run alongside geometry, not "second-line."
> 4. **PULL FORWARD — B4-lite real probe ($0.5):** base + Gemini on 10–15 real FRED/OWID charts *before* the main train, to learn the transfer-wall height early (the #1 kill shot, previously tested last).
> 5. **DEMOTE** the structural-noise sim (old B0 0a-i/0b) to appendix; **CUT** test-time self-ensembling from the headline (inflates inference cost, undercuts the cheap-small-model story).
> 6. **Retire the "beats frontier" framing** — verified ceiling: P(beat Gemini on real) ≈10–15%, P(beat base ≥3pp) ≈65–75%. Defensible claim = "geometry supervision makes a small VLM measurably better at exact extraction; closes ≥⅓ of the label-free gap," NOT "beats frontier."
>
> The revised run order is in **Run Order and Milestones** below (table updated). Net budget unchanged (~$10–13).

## Claim Map
| Claim | Why It Matters | Minimum Convincing Evidence | Linked Blocks |
|-------|----------------|-----------------------------|---------------|
| **C0** (gate) | If geometry-decode compounds worse than guessing under the model's *real* error, the thesis is dead — cheap to check first | On renderer GT + the model's measured structural/pixel error, geometry-decode (all-tick robust) ≥ noise-matched direct-value on cell@5_exact; Stage-A decoded values match printed values ≥80% | B0 |
| **C1** (dominant) | Isolates "measure vs guess" on one set of weights — rules out "richer target just regularizes training" | Same geometry-LoRA: geometry-decode > its own emitted-table on the 155-item label-free-exact slice; paired bootstrap (a)−(b) CI excludes 0; ≈ on labeled (negative control) | B1, B3 |
| **C2** (secondary, blocked) | The preregistered fine-tuning gate; needs the base arm the audit flagged missing | Geometry-LoRA beats pinned base (rev `252d592b…`) on common300 cell@5_exact by ≥3pp, CI excludes 0, invalid not worse | B2 |
| **C3** (external) | Guards against "learned this renderer," not chart measurement | On FRED/OWID real charts (N≥50, value-level CSV GT): positive transfer; closes ≥⅓ of base→best-frontier label-free gap | B4 |

**Anti-claims to rule out**: (i) "gain is just fine-tuning / longer target" → B1 same-weights decode-vs-emit + B3 table-only-LoRA arm; (ii) "gain is renderer memorization" → B4 real set; (iii) "deterministic decode is unnecessary" → B3 decode-necessity arm; (iv) "calibration compounds" → B0.

## Paper Storyline
- **Main paper must prove**: C1 (measure>guess, same weights), C2 (beats pinned base), C3 (transfers), with B3 isolating that *geometry* (not fine-tuning per se) is the cause.
- **Appendix can support**: B0 robustness curves; per-slice/per-type failure analysis (B5); readability-controlled metrics; the optional confidence/self-ensembling appendix from the proposal.
- **Intentionally cut**: aux regression head, detector net, RL, 8B (gated until 4B passes C1+C2), multi-chart-type CV pipeline.

## Experiment Blocks

### Block B0: Decode-robustness gate (Claim C0) — runs BEFORE training
- **Claim tested**: C0. **Why**: $0–$2 go/no-go that kills the idea cheaply if calibration compounds, and sizes the calibration robustness (how many ticks / reject count).
- **Dataset/split/task**: renderer ground-truth geometry for a labeled (Stage-A) slice of synthetic_v1; the existing `outputs/modal/qwen3vl4b-lora/predictions.jsonl` (table-only) for structural-error measurement.
- **Compared systems**: geometry-decode (all-tick robust fit) vs geometry-decode (2-tick) vs noise-matched direct-value baseline.
- **Metrics**: cell@5_exact vs injected-error level (decisive); curve crossing point.
- **Setup**: **0a-i** ($0, from existing predictions): measure cardinality + series-association error vs GT. **0a-ii** (~$2, needs the new geometry serializer + a small Stage-A geometry-emission run): measure real per-mark/tick *pixel* error. **0b** ($0): feed measured structural perturbations (drop/dup/swap/heavy-tail) + pixel noise through the deterministic decoder.
- **Success**: all-tick-robust geometry-decode ≥ direct-value at the measured error level, AND Stage-A decoded-vs-printed ≥80% cell@5_exact.
- **Failure interpretation**: if geometry-decode loses at realistic error → the privileged-geometry thesis is falsified for ≤$2; do not train. If only Stage-A calibration fails → the 4B can't emit geometry; reconsider target encoding before spend.
- **Table/figure**: Fig "robustness of decode vs guess under measured error." **Priority: MUST-RUN (gate).**

### Block B1: Measure-vs-guess isolation (Claim C1) — the dominant result
- **Claim tested**: C1. **Why**: isolates the mechanism on identical weights (controls for fine-tuning, format, training).
- **Dataset/split**: common300, the **155-item label-free-exact slice** (= 186 label-free − 31 label-free pies; pies reported separately as proxy per audit B); labeled slice = negative control.
- **Compared systems**: the *same* geometry-LoRA scored (a) geometry-decode vs (b) its own emitted table. Context arms: pinned base, table-only LoRA (existing).
- **Metrics**: cell@5_exact (decisive) + median rel err; **paired bootstrap on (a)−(b)** (reuse `paired_bootstrap.py`).
- **Setup**: identical decoder/decoding config both scorings; readability-controlled variant reported alongside (see Readability control).
- **Success**: (a) > (b) on label-free with CI excluding 0; (a) ≈ (b) on labeled.
- **Failure interpretation**: (a) ≈ (b) on label-free → geometry tokens don't carry measurement signal; the contribution fails even if C2 passes.
- **Table/figure**: Table 1 (headline). **Priority: MUST-RUN.**

### Block B2: Base-control gate (Claim C2) — clears audit C/K
- **Claim tested**: C2. **Why**: preregistered fine-tuning gate; supplies the base arm the audit found missing.
- **Dataset/split**: common300 (frozen, table-level deduped).
- **Compared systems**: pinned 4B base (`unsloth/Qwen3-VL-4B-Instruct`, rev `252d592b59b0233b226875a44ac135cfa1d3f755`) vs geometry-LoRA, **identical decoder + metric both arms**.
- **Metrics**: cell@5_exact; paired bootstrap; gate = gap≥3pp, CI excludes 0, invalid not worse.
- **Setup**: the enforced `--revision` guard (already in `run_baselines`); `meta.json` records revision/gen-config/fingerprints both arms.
- **Success**: gate passes. **Failure**: fine-tuning (incl. geometry) doesn't beat base → stop before 8B.
- **Table/figure**: Table 1 (base row). **Priority: MUST-RUN (blocked until base run lands).**

### Block B3: Novelty + simplicity ablations
- **Claim tested**: C1 anti-claims (i),(iii). **Why**: prove *geometry* causes the gain, and that deterministic decode + over-determined fit are each necessary.
- **Compared systems** (mostly free re-scoring of existing predictions): (1) table-only-LoRA vs geometry-LoRA (does geometry help beyond fine-tuning?); (2) geometry-decode vs all-tick-robust-off (2-tick) (does over-determination matter?); (3) geometry-LoRA scored table-emit vs geometry-decode (decode necessity — same as B1 but framed as ablation).
- **Metrics**: cell@5_exact on label-free slice.
- **Success**: geometry-LoRA > table-only-LoRA; all-tick-robust ≥ 2-tick; decode > table-emit. **Failure**: if table-only-LoRA ≈ geometry-LoRA → the win is fine-tuning, not geometry (kills the contribution).
- **Table/figure**: Table 2 (ablations). **Priority: MUST-RUN (cheap).**

### Block B4: External validity (Claim C3)
- **Claim tested**: C3. **Why**: synthetic train+test share the generator; real transfer is the credibility gap.
- **Dataset**: FRED + OWID charts with downloadable CSV ground truth, N≥50 (value-level GT; WB-ChartExtract only if value-level GT confirmed).
- **Compared systems**: geometry-LoRA vs pinned base vs best frontier (Gemini-3.1-Pro).
- **Metrics**: cell@5_exact (small N, honest CI).
- **Success**: positive transfer + closes ≥⅓ of base→best-frontier label-free gap. **Failure**: no transfer → claim scoped to "synthetic only," major limitation.
- **Table/figure**: Table 3 (real-world). **Priority: MUST-RUN.**

### Block B5: Failure analysis (appendix)
- **Claim tested**: none (diagnosis). **Why**: shows what geometry still misses; guides next round.
- **Compared systems**: geometry-LoRA across slices — chart type, density band, truncated baseline, K/M/B suffix, augmented; readable vs unreadable.
- **Metrics**: cell@5_exact per slice; invalid-output rate.
- **Priority: NICE-TO-HAVE (appendix).**

## Readability control (cross-cutting, addresses MODEL_STATUS_REVIEW concern)
Some synthetic charts are illegible even to a careful human (36-cat bars at 400×280, overlapping labels). To avoid measuring *information loss* instead of *chart reading*, every headline table (B1/B2) is reported **twice**: full common300 and a **human-readable subset** (charts passing a legibility heuristic: min figure size, max category density, no severe label overlap; flag built from renderer spec params + a one-time spot check). The readable-subset number is the honest "can the model measure when a human could" claim; the gap between them quantifies benchmark-induced loss.

## Run Order and Milestones (revised by /research-review, ranked by decision-value/dollar)
| Milestone | Goal | Runs | Decision Gate | Cost | Risk |
|-----------|------|------|---------------|------|------|
| **M0a** | **Mechanism ceiling (NEW first gate)** | Build geometry serializer (R003); **R000 oracle-geometry decode** on the 712 matched rows (GT pixels+ticks) | **perfect-geometry cell@5 ≥ ~70% on matched bucket — else STOP (no GPU)** | **$0** | low, decisive |
| **M0b** | Free baseline-lifters | Constrained-decode-only on existing LoRA (recovers 28 invalid; = fair K2 baseline); structural sim → appendix | invalid→~0; record fair baseline cell@5 | **$0** | low |
| **M0c** | Transfer probe (pull-forward) | base + Gemini on 10–15 real FRED/OWID charts | gauge real-set gap before train (K1) | **~$0.5** | informative |
| **M1** | Pixel gate + base control (clears audit C/K) | B0 0a-ii Stage-A geometry-emission (~$2); **pinned base control on common300** (~$2–4, rev `252d592b…`) | Stage-A calibration ≥80%; base artifact exists + pinned + fingerprinted | **$4–6** | med (may stop) |
| **M2** | Train the method (+ co-arm) | Regen v1 w/ geometry (~$0.3); geometry-LoRA train, L4, ~2ep, **+val + best-checkpoint + constrained decode**; **+ numeric-token-loss arm** (~$3) | schema-valid ≥95%; val cell@5_exact improves over fair base | **$3–5** | med |
| **M3** | Decisive results | B1 (decode-vs-emit, 155 slice) + B2 (base vs LoRA bootstrap) + B3 ablations vs **fair** baseline + 27%-bucket analysis | C1 (a)>(b) label-free CI≠0; C2 ≥3pp CI≠0; geometry survives the *fair* baseline | **~$1** | high (real test) |
| **M4** | External validity | Full B4 FRED/OWID (N≥50) (~$1–2) | positive transfer; ≥⅓ gap closed | **$1–2** | high |
| **M5** | Polish | B5 slices + readability + qualitative; self-ensembling (appendix only) | — | **~$0** | low |

## Compute and Data Budget
- **Total ≈ $8–13** (L4 ~$0.80/hr; eval/inference dominates), well under the $25 cap. 8B is deferred until C1+C2 pass.
- **Data prep**: extend the renderer to serialize geometry (plot bbox, all ticks, per-mark pixels) into the target; regenerate v1; keep test + common300 frozen and table-level-deduped (audit G). Build the FRED/OWID real set (N≥50) with CSV GT.
- **Human eval**: only the one-time legibility spot-check for the readability heuristic.
- **Biggest bottleneck**: M0 geometry serializer correctness (everything downstream depends on exact geometry targets) and M3 (the decisive test).

## Risks and Mitigations
- **Calibration compounding** → B0 gate before any training ($0–$2).
- **4B can't emit coordinates/association as text** → positional (canonical-order) mark emission + constrained-decode grammar (bounds cardinality) + Stage-A gate; falsified for ~$2.
- **Base run is the audit's central gap** → M1 runs it first (pinned), unblocking C2 and clearing audit C/K simultaneously.
- **Synthetic→real gap** → B4 required, claim scoped accordingly.
- **Readability confound** → dual reporting (full vs readable subset).

## Final Checklist
- [x] Main paper tables covered (T1 headline B1/B2, T2 ablations B3, T3 real B4)
- [x] Novelty isolated (B1 same-weights decode-vs-emit + B3 table-only-LoRA)
- [x] Simplicity defended (zero new trainable components; B3 over-determination + decode-necessity ablations; no aux head/detector)
- [x] Frontier contribution justified (privileged-info + deterministic decode + constrained decoding — necessity shown in B0/B3, not decorative)
- [x] Must-run vs nice-to-have separated (B0–B4 must; B5 appendix)
- [x] Integrity gates inherited from EXPERIMENT_AUDIT.md (pinned base, identical decoder both arms, cell@5_exact excl. pie proxy, table-level dedup)
