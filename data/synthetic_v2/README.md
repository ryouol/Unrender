# synthetic_v2 — real-transfer training set (2026-07-01)

**Frozen historical evidence, not a current generation recipe.** The
[visibility audit](../../release/model-error-audit/README.md) confirmed hidden
metadata and clipped stacked targets. Current generation intentionally uses a
new contract and refuses to overwrite these files. Use
[the current dataset workflow](../../docs/SYNTHETIC_DATA.md) for new data.
The commands below describe old source revisions only; do not run them here.

Originally built to address apparent real-chart gaps in the 2026-07-01 sweep
(`refine-logs/FRONTIER_PLAN.md` P1; changes in `CHANGELOG.md`): value magnitudes
to **1e9** (v0/v1 capped below 1e6 — the model scored 0% on real population/CO₂
charts under the now-rejected real_v0 annotations), real-world value-axis formats (K/M/B suffixes incl. the previously
unreachable **B**, comma-grouped ticks, full raw digits, mpl offset notation),
**continuous numeric year x-axes** with sparse ticks on line charts (the
OWID/FRED look), owid/dark/news **themes**, wired minor ticks, ~55% label-free,
density mixing easy+hard, heavy augmentation (0.95).

Generated LOCALLY (M4 Pro) and uploaded to the Modal volume — data gen is
CPU-only, so local is free. Same pinned rendering stack as the Modal image,
but matching package versions alone does not establish identical image bytes.

## What's committed vs regenerable

- **Committed:** `test.jsonl` (1000) and `val.jsonl` (500) — labels + slice
  metadata + image paths.
- **Not committed (regenerable):** `images/`, `labels/`, `manifest.jsonl`,
  `train.jsonl` (18,500).

## Historical recipe (requires its original source revision)

```bash
python -m unrender.data_gen.generate      --n 20000 --out data/synthetic_v2 --seed 9012 --v2 --workers 10
python -m unrender.data_gen.split_dataset --out data/synthetic_v2 --val-size 500 --test-size 1000   # split seed 7 (default)
```

The historical recipe used `seed + index` (indices 0..19999).
**Recipe code version matters:** this set was regenerated 2026-07-07 after the
visual audit (dark-theme-safe palettes; huge-magnitude dense charts forced
label-free — see CHANGELOG). Reproducing it requires its original source, not arbitrary later code.
Byte-identical images additionally require the frozen rendering stack:

| tool | version |
|---|---|
| python | 3.11.15 |
| matplotlib | 3.10.9 |
| numpy | 2.4.6 |
| pillow | 12.2.0 |

## Prompt version

Rows bake the **v1 `EXTRACTION_PROMPT`** (default) so results stay comparable
with every existing arm. `EXTRACTION_PROMPT_V2` exists (`unrender/prompts.py`)
but must only be adopted when ALL compared arms re-run on it together
(`split_dataset --prompt-v2`).

## Upload to Modal (once, free)

```bash
modal volume put unrender-vol data/synthetic_v2 data/synthetic_v2
```

This upload/training route is historical. The current loader resolves relative
images from the split directory and requires generation receipts for new data.
Do not combine historical and current targets without an explicit reviewed recipe.
