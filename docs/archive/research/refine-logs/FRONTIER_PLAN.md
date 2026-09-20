# Full sweep → plan to beat frontier (2026-07-01)

**Trigger:** user directive — "full sweep, figure out what's wrong, set this model up to beat frontier. No training runs yet."
**Inputs:** completed R011b/R007b experiment (both arms trained+evaluated), failure decomposition of the new best model, paired frontier head-to-heads on shared common300 ids, generator-capability audit, scoring-mechanics audit.

## 1. Experiment verdict (R007b / R011b — CLOSED)

| Arm | cell@5_exact (common300) | valid | labeled / label-free |
|---|---:|---:|---|
| pinned base 4B | 13.0% | 78% | — |
| geom no-lever | 21.0% | 81% | — |
| geom + levers | 27.9% | 94% | — |
| numloss table (lever ×3) | 36.5% | 94.7% | 41.3 / 33.4 |
| **table-fair (lever OFF, val+best-ckpt) — NEW BEST** | **38.2%** | **96.3%** | **44.6 / 33.9** |
| R000 oracle ceiling | ~98% | — | — |

- **Lever REJECTED on the table target:** numloss − fair = **−1.59pp, 95% CI [−3.30, +0.05], P(lever better)=2.7%**, invalid worse (5.3 vs 3.7%). Its geometry-arm win was fixing a 19%-invalid problem the table target doesn't have. Do not use it again.
- **Fair protocol itself is worth ~+1.4pp** (38.2 vs the old unfair 36.8 anchor) — val+best-ckpt stays permanently.
- **Fine-tuning gate re-passed fairly:** fair − base = **+25.19pp, CI [+22.31, +28.28]** — audit-proof.

## 2. Where we stand vs frontier (paired, shared common300 ids, cell@5_exact)

| Frontier | N | frontier | fair-LoRA | gap |
|---|---:|---:|---:|---:|
| gpt-5.5 | 63 | 38.0% | 39.2% | **+1.2pp — parity/ahead** |
| claude-fable-5 | 86 | 44.2% | 38.4% | −5.8pp |
| gemini-3.1-pro | 64 | 64.9% | 36.6% | **−28.3pp ← the real bar** |
| gemini, label-free only | 41 | 57.3% | 33.9% | −23.4pp |

Real charts (real_v0, 8 OWID line charts): LoRA 67.2% vs base 31.2%; Gemini "100%" = **contamination artifact** (memorized famous series) — head-to-head invalid there; a contamination-resistant set is required for any frontier claim on real charts.

## 3. What's wrong — ranked, with evidence

1. **Gross misreads dominate, not calibration.** Of 8,431 exact cells: 38.1% correct, only **4.7%** in the 5–10% near-miss band, **48.9% >10% wrong**, 4.1% x-unmatched. Matched-bucket median rel err is 5.6%. → Precision polish (the lever, decode tricks) can't buy much; the model needs to *read hard charts better*, i.e. data + capacity.
2. **Training data has a magnitude ceiling at <1e6** (`chart_specs.py:203`: max scale 1e6 × rng<1 → max ~999,999). Real-world 1e8–1e9 charts (population, total CO₂) score **0%** — the model has never emitted an 8–10-digit number. The "B" tick-suffix branch is literally unreachable (`chart_specs.py:320` needs vmax≥1e9). Axis formats K/M/B/comma/offset barely or never seen.
3. **Visual/format diversity is one matplotlib default style.** No OWID/FRED/news/dark themes, x is always categorical (never a continuous year axis with sparse ticks), no scatter/area, no log scale, `minor_ticks` knob is dead code. Real-chart transfer is capped by this.
4. **Whole-chart invalids are expensive and fixable.** 3.7% of charts (11) parse-fail → all their cells count 0 in the denominator. Killer values: `"1,200"`, `"1.2B"`, `"12%"`, `"$5"`, truncated JSON — none repaired today. No constrained decoding anywhere.
5. **Worst slices:** horizontal_bar label-free **16.7%**, stacked_bar label-free **18.3%** (association/segment arithmetic), bar label-free 31%, line label-free 33%.
6. **x-label fuzzy-match (≥85) silently kills correct values** ("Jan" vs "January" ≈60 → miss). Affects all models symmetrically but costs us recoverable cells.

## 4. The plan (phased, gated, costed) — NO GPU until explicit go

> **STATUS 2026-07-07 (boil-the-ocean pass):** eyes-on audit of rendered v2 found 2 supervision bugs
> — dark theme × dark palettes = invisible marks; 9-digit labels × dense charts = unreadable ink —
> both FIXED + regression-tested; **v2 regenerated + re-uploaded**. New levers (default off):
> `--type-weights` per-chart-type oversampling; self-consistency ensemble merger
> (`unrender/eval/ensemble.py`, k-run per-cell median vote — the no-retrain +2-5pp option vs frontier);
> training meta.json provenance. Considered and REJECTED for the one-shot (attribution/comparability):
> scatter/area chart types (changes EXTRACTION_PROMPT → invalidates every existing baseline), LoRA
> r=32, longer warmup — all deferred to P2.5 arms if needed. 68/68 tests.
>
> **STATUS 2026-07-01: P0 + P1 IMPLEMENTED** (58/58 tests, ruff-clean on changed files, CHANGELOG'd).
> P0 measured: fair 38.18→**38.86%** (invalid 11→**0**), numloss 36.52→37.69 (16→1), base 12.99→13.52
> (66→26); frontier paired numbers unchanged (repairs favor no one). P1 v2 generator built + visually
> verified (dark/B-suffix chart reads “-0.2B..1B”; OWID continuous 2002–2009 year axis) — the B-suffix
> dead-branch bug (`>=1e9` unreachable since values are `rng.random()*scale`) found+fixed with fractional
> thresholds; v0/v1 byte-frozen (fingerprint regression test). `gen_v2` Modal entrypoint ready (~$1–2,
> 20k charts) — NOT run. Next gates in order: run `gen_v2` → P2 retrain → P3 decode → P4 8B → P5 benchmark.

**Phase 0 — $0 free wins (re-score saved raw; no GPU, no API).**
- Extend `repair_json`/`_normalize_keys` (validate.py): numeric-value normalization (strip commas, expand K/M/B suffixes, %, $), brace-balancing for truncated JSON, quote/literal fixes, unwrap `{"chart":…}`. Symmetric for all models; never touches GT. Re-score fair + frontier lanes for free. Expected +1.5–4pp; keeps measurement honest via CHANGELOG + dual-report.
- Conservative pred-side x-normalization (year forms, month abbrevs). Expected +0.5–2pp.
- Unit-test everything (repair is pure Python).

**Phase 1 — data engine v2 (CPU ~$1–2) + prompt hardening ($0).**
- Magnitudes to 1e9 via a NEW value path (keep v0/v1 recipes byte-frozen; new `synthetic_v2`, own seed). Render large values in all real formats: raw digits, comma-grouped, K/M/B ticks (fix unreachable B), mpl offset `1e9`.
- Continuous/date x-axis line mode with sparse ticks (the OWID/FRED look); style themes (OWID, FRED, dark, news), legends outside, gridline variety; wire `minor_ticks`.
- Oversample worst slices (h-bar, stacked label-free); keep ~60% label-free; scale 5k→20k charts/set.
- Harden EXTRACTION_PROMPT: "raw numbers only (1.2B → 1200000000), copy x labels exactly, one point per category." Same string for every model.

**Phase 2 — retrain 4B on v0+v1+v2, fair protocol. GATED. (revised 2026-07-06 for one-shot)**
Expected +5–10pp synthetic (hard-chart mass + formats) and fixes the real-chart magnitude 0%s.
CORRECTED COST: the v2 mix is ~32.6k records → ~4.1k steps at 1.0 epoch ≈ 12.5h L4 (~$10) or
~4.2h A100 (~$9), + chained evals ~$2.5 → **~$11–13 total** (not the earlier $7 — that was the
old 9k-record mix). 1.0 epoch is MORE total gradient (4.1k steps) than the 38.86% model's 2.0
epochs (2.25k steps), on non-repeated data; best-ckpt selection guards the endpoint.
ONE-SHOT HARDENING (built 2026-07-06, $0): (a) `--eval-after real_v0,common300,v2:300` chains
the evals in the same container after merge (failure-isolated, each resumable); (b) crash
resume — relaunching the same command continues from the latest checkpoint instead of step 0;
(c) `modal run modal_train.py::check` preflight (~$0.02) verifies every referenced image exists,
ALL 20k v2 volume images decode, longest targets fit the 4096-token budget, and prints the
step/cost estimate. THE COMMAND:
```
UNRENDER_GPU=A100 modal run --detach modal_train.py::train \
  --train-files v2,v1,v0 --val-files v2,v1,v0 --epochs 1.0 \
  --out-name qwen3vl4b-v2 --eval-after real_v0,common300,v2:300
```
(L4 variant: drop UNRENDER_GPU — ~$1 cheaper, ~3× longer wall-clock.)

**Phase 3 — constrained decoding (R001b). DEPRIORITIZED 2026-07-06.**
P0's repairs already drove the fair model's invalid rate to **0/300** on common300 — the headroom
this phase targeted (+1.5–3pp from ~3.7% invalid) has collapsed to ~0. Revisit ONLY if the
v2-trained model shows a meaningful invalid rate on the chained evals.

**Phase 4 — 8B launch run (~$10–15 A100). GATED on Phases 0–3 shipping.**
Same recipe on Qwen3-VL-8B (long-planned; gates now passed). Expected +4–8pp over 4B.

**Phase 5 — the benchmark that defines "beats frontier" (~$3–5 API). GATED.**
Contamination-resistant real_v1, N≥50: post-cutoff data (2025H2–2026 FRED/OWID — FRED fetchable from the Mac with sandbox off), obscure country×indicator pairs, bar+line+multi. Run ours + gemini/gpt/fable on identical harness. This is where the product claim ("reads novel/private charts frontier can't memorize") is decided.

**Stack math vs Gemini (64.9%):** 38.2 now + 2–5 (P0) + 5–10 (P1+P2) + 1.5–3 (P3) + 4–8 (P4) ≈ **51–64**. Honest odds: beat gpt-5.5 ✅ already; beat fable-5 ~60–70%; beat gemini on synthetic-hard ~25–35%; **beat/match gemini on the novel-real benchmark ~40–55%** (its memorization edge removed, our domain match). Total new spend ≈ **$25–32**; spent to date ≈ $70 of the $150–350 budget.

## 5. Immediate next actions (all $0, no GPU — can start on go)
1. Phase-0 repair/normalization code + tests + free re-scores (fair, numloss, base, frontier lanes) → updated comparison table.
2. Generator v2 changes + regen preview (few hundred charts locally, visual spot-check) — still $0.
3. real_v1 source list (post-cutoff/obscure) drafted for review.

Commits pending: infer entrypoint + val/best-ckpt protocol + this sweep's docs (user to approve commit).
