# Experiment Audit Report

**Date**: 2026-06-15
**Auditor**: External reviewer backend — Codex (`gpt-5.5`), xhigh reasoning, read-only sandbox (cross-model; executor = Claude/Opus, collects paths only)
**Project**: Unrender (Qwen3-VL-4B LoRA chart→JSON vs frontier VLMs)
**Audit target**: common300 base-vs-LoRA setup *before any GPU spend* — leakage, subset coverage, model revision pinning, resume guards, base-control isolation
**Trace**: `.aris/traces/experiment-audit/2026-06-15_run01/` (thread `019ecd6f-…`)

## Overall Verdict: 🔴 FAIL (for gating more GPU spend)

## Integrity Status: fail

> **One-line summary:** The common300 *ID-level* leak is genuinely fixed (300 unique test ids, 0 in train/val). The blocker is different and decisive: **no base-model control has ever been run** — there is no base predictions/report artifact anywhere — so the entire base-vs-LoRA comparison is currently **unsupported by data**, and the base model is **not revision-pinned**, so even once run it would not be reproducible.

---

## Checks

### A. Ground Truth Provenance: ✅ PASS
GT is loaded from dataset assistant messages, not model outputs (`unrender/eval/dataset.py:31`), embedded into predictions by `unrender/eval/run_baselines.py:157`, and scored from `r["gt"]` in `unrender/eval/score.py:71`. Synthetic labels come from `ChartSpec.to_chart_data()` (`unrender/data_gen/chart_specs.py:107`). Mock `perfect/noisy` providers do derive outputs from GT but are explicitly labeled non-real (`unrender/eval/providers.py:10`).

### B. Score Normalization: 🔴 FAIL (scoped)
Most metrics use GT denominators, e.g. `cell_accuracy = correct_pts / total_pts` (`unrender/eval/metrics.py:214`). **But label-free pies normalize predicted values by the model's own predicted total** (`unrender/eval/metrics.py:179`, `:184`) — a denominator derived from prediction statistics. It is disclosed as a proportion-only special case (`unrender/eval/metrics.py:149`), but per the checklist it still violates the rule. **Treat label-free pie results as a proportion/proxy metric, not exact numeric extraction.** (186/300 common300 items are label-free; pies = 31.)

### C. Result File Existence: 🔴 FAIL
LoRA reports exist and **match** documented numbers: full LoRA cell@5 = `0.3483` (`outputs/modal/qwen3vl4b-lora/report.json:7`); common300 LoRA cell@5 = `0.3683` (`outputs/modal/qwen3vl4b-lora/report.common300.json:9`). **The base control is explicitly not run yet** (`PREREGISTRATION.md:3`); the expected base path appears only as an example in `unrender/eval/paired_bootstrap.py:10`; artifact inventory found **no base predictions/report**. Tracker state is also stale/contradictory: README Phase 3 unchecked (`README.md:17`) while status review says training/eval completed (`MODEL_STATUS_REVIEW.md:20`).

### D. Dead Code Detection: ✅ PASS
Core metric functions are called: `score_sample` (`unrender/eval/score.py:81`, `paired_bootstrap.py:42`, `failures.py:47`), `aggregate` (`score.py:83`, `paired_bootstrap.py:114`), `score_rows` (`report.py:58`). Caveat: no saved paired-bootstrap result artifact exists yet.

### E. Scope Assessment: ⚠️ WARN
Actual scope: one 4B LoRA run, one seed, synthetic-v1 hard test, incomplete frontier coverage, no real-world set. Status docs are appropriately cautious (`MODEL_STATUS_REVIEW.md:207`), but README still states the "small model can beat frontier VLMs" bet (`README.md:8`), which is **not yet supported**.

### F. Evaluation Type: real_gt (on synthetic data) — with caveats
- LoRA / frontier evals: **real_gt on synthetic data**.
- Mock `perfect/noisy` providers: **synthetic_proxy**, explicitly non-baseline.
- Label-free pies: **real_gt for proportions only**, not absolute-value GT.

---

## Project-Specific Focus (the five things you asked about)

### G. Leakage: 🔴 FAIL (under strict checklist) / ID-level PASS
- **Direct common300 leak: PASS.** `common300.json` is a 12-key dict with `n_actual=300`, `n_candidates=494`, `subset_fp=b02a6d7ad001bd9d` (`unrender/eval/subsets/common300.json:2`). Pool = local-test ∩ Modal-test (`common_pool_494.json:2`). Computed overlaps: common300 ∩ train = **0**, ∩ val = **0**, ∩ test = **300**.
- **Table-level dedup missing.** Exact full-label dups = 0, but stricter table-hashes (incl. series names/axes) found **one train/val duplicate group**; looser data-table hashes found **train/test degenerate-pie duplicates** (`outputs/modal/data_v1/train.jsonl:90`, `val.jsonl:35`). These do **not** touch common300, but the generator/split lacks table-level dedup — a latent leak for future freezes.

### H. Subset Coverage: ⚠️ WARN
common300 is genuinely 300 items, **stratified** across 44 chart-type × label × density cells (`common300.json:12`). Composition: bar 62, grouped_bar 45, horizontal_bar 33, line 46, multi_line 50, pie 31, stacked_bar 33; 186 label-free / 114 labeled. **Not** model-success-selected (no survivorship bias in subset construction). **But** current frontier predictions cover only part of it: eval-v1 all-frontier `ok` ∩ common300 = **45**; frontier+LoRA `ok` = **44**. New API calls are needed to cover the fixed subset (`PREREGISTRATION.md:66`).

### I. Model Revision Pinning: 🔴 FAIL
Base defaults **unpinned**: `unrender/eval/providers.py:25`, `unrender/train/sft_lora.py:54`, `modal_train.py:141`. `--revision` exists but is optional (`run_baselines.py:190`). Training calls `FastVisionModel.from_pretrained` **without a revision** (`sft_lora.py:176`). LoRA `meta.json:2` records only provider/model/data — **no revision/fingerprint/gen-config**. Deps are mostly unpinned ranges (`pyproject.toml:24`). → The base-vs-LoRA comparison is **not reproducible** as configured.

### J. Resume Guards: ⚠️ WARN
Good guards exist: resume-config mismatch check (`run_baselines.py:112`), duplicate-id scoring **fails loudly** (`score.py:92`), subset-coverage check fails on missing ids (`score.py:100`). **But** historical meta files are too minimal to enforce these retrospectively, and full reports can shift denominators via `infra_error` exclusions (observed in eval-v1 OpenAI/Gemini reports — relates to the "billing-truncated 158/83/255" history).

### K. Base Control Isolation: 🔴 FAIL — **the central failure**
The code *can* isolate the fine-tuning effect **if both arms are run**: shared prompt (`unrender/prompts.py:10`), same HF provider (`providers.py:138`), same scorer (`score.py:57`), paired bootstrap requires both arms + coverage (`paired_bootstrap.py:68`). **But the base arm does not exist.** Therefore every base-vs-LoRA conclusion is currently **unsupported, not merely weak**. There is also no recorded gen-config/seed/processor fingerprint to *prove* the two arms would be held identical once run (ties to check I).

---

## Claim Impact
- **C1 — LoRA full-v1 result (cell@5 = 34.8%):** supported.
- **C2 — LoRA common300-only result (cell@5 = 36.8%):** supported.
- **C3 — common300 ID-level leak fix:** supported.
- **C4 — 3-provider eval-v0 / eval-v1 intersection tables:** supported (as intersection-only).
- **C5 — Frontier comparisons ("we vs Gemini/GPT/Claude"):** needs qualifier — `ok`-intersection + incomplete coverage (N≈44–45 on common300).
- **C6 — Label-free pie accuracy:** needs qualifier — proportion-normalized proxy, not absolute numeric.
- **C7 — Any base-vs-LoRA result / "fine-tuning helped over base":** **UNSUPPORTED** — base arm never run.
- **C8 — Any paired-bootstrap gate outcome:** **UNSUPPORTED** — requires both arms.
- **C9 — Any "small model beats frontier" result claim:** **UNSUPPORTED** at this stage.
- **C10 — Reproducibility of base/LoRA comparison:** **UNSUPPORTED** until revisions/fingerprints pinned.

## Action Items — MUST-FIX before GPU spend (severity-ordered)
1. **Run the pinned base-4B control on common300** and save `predictions.jsonl`, `meta.json`, `report.common300.json`, and paired-bootstrap output. *(Without this, base-vs-LoRA is undefined.)*
2. **Pin & record provenance in both arms:** exact base HF revision, adapter/merged-model fingerprint, processor/tokenizer config, generation config (`do_sample`, max tokens, seed), `dataset_fp`, `subset_fp`. Make `--revision` required.
3. **Split label-free pie proportion scoring into a clearly named proxy metric** (e.g. `pie_proportion@5`), or additionally report absolute-value failure, so it is never pooled into "exact numeric extraction."
4. **Add table-level dedup checks** before any future train/val/test freeze (hash on the data table, not just image id).
5. **Do not cite frontier/common300 comparisons** until frontier runs cover the *same* fixed subset — otherwise label them explicitly as partial / intersection-only (N≈45).

## Remediation (2026-06-15, post-audit — code/setup fixes landed)

The reviewer's verdict above is preserved as-issued. Below is what was fixed in code
(GPU-free, all 28 tests green) and what still requires the one gated GPU run.

| Check | Audit | Fix landed | Status now |
|---|---|---|---|
| **B** Score normalization | FAIL | `metrics.py` now buckets points into exact vs label-free-pie proxy; `aggregate` reports `cell_accuracy_exact` + `pie_proportion_accuracy` + counts; `score.py`/`report.py` surface them. Re-scored existing reports: headline **unchanged** (`0.3483`), exact-numeric = **34.7%** full / **36.8%** common300 (proxy inflation = +0.1pp). Test added. | ✅ **resolved (code)** |
| **I** Revision pinning | FAIL | `run_baselines.run()` now **refuses an unpinned Hub `hf` model** (`--revision` required; local merged/adapter dirs exempt — content-fingerprinted). meta already records `model_revision`/`gen_config`/`dataset_fp`/`subset_fp` (the audit judged the *legacy* `meta.json`). Test added. | ✅ **resolved (code)**; legacy LoRA `meta.json` stays thin until its next run |
| **G** Leakage (table-level) | FAIL(strict) | `data_table_signature()` added; regression test asserts **common300 ∩ train = 0 at data-table level** (passes on committed data — the id-level fix holds at table level too). | ✅ **resolved for common300**; generator-time dedup for *future* freezes still a TODO |
| **E** Scope | WARN | README Phase 3 reconciled → *in progress*; base control pending; "beats frontier" relabeled the **hypothesis under test**. | ✅ **mitigated (docs honest)** |
| **C** Result existence (base arm) | FAIL | Cannot be fixed in code — base control must be **run**. Command wired + pinning enforced. | ⏳ **pending GPU run** |
| **K** Base control isolation | FAIL | Code is ready: shared prompt/scorer/provider, `paired_bootstrap` requires *both* arms + coverage, pinning now enforced. | ⏳ **pending GPU run** |
| **H** Coverage (frontier ∩ common300 ≈ 45) | WARN | Needs more frontier API calls on the fixed subset (cheap, **not** GPU) — folded into `/experiment-plan`. | ◻ open (API spend) |
| **J** Resume guards | WARN | Guards already strong (dedup/coverage/resume-config raise); only legacy meta is thin. | ◻ acceptable |
| **A/D/F** | PASS | — | ✅ |

**Net:** the two remaining FAILs (**C**, **K**) share one root cause — *the base-model control has not been run*. The code is now ready and pinning is enforced, so **one ~$1–3 L4 eval clears the gate**:

```bash
# 1. Pinned base-4B control on common300 (the missing arm). --revision is now REQUIRED.
modal run --detach modal_train.py::evaluate \
  --model unsloth/Qwen3-VL-4B-Instruct \
  --revision 252d592b59b0233b226875a44ac135cfa1d3f755 \
  --subset common300
#    (confirm the revision matches the Unsloth mirror present when the LoRA was trained)

# 2. Paired bootstrap — the preregistered base-vs-LoRA gate (both arms, same 300 ids):
python -m unrender.eval.paired_bootstrap \
  --a outputs/modal/qwen3vl4b-lora/predictions.jsonl                 --label-a LoRA \
  --b outputs/modal/eval_v1__Qwen3-VL-4B-Instruct__common300/predictions.jsonl --label-b base-4B \
  --subset unrender/eval/subsets/common300.json \
  --out outputs/modal/paired_base_vs_lora.json
```

## Notes on Audit Limits
This audit catches common integrity-failure patterns via cross-model code reading; it is a safety net, not a proof of correctness. Set-overlap and composition figures above were computed by the reviewer from the JSONL/JSON artifacts and should be reproduced by `tests/test_integrity.py` as regression guards. The base-arm and pinning fixes (items 1–2) are the gate: clearing them converts C7–C10 from *unsupported* to *testable*.
