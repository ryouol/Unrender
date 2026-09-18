# eval-v1 — frozen hard evaluation set

**Frozen historical evidence, not a current generation recipe.** The
[visibility audit](../../release/model-error-audit/README.md) confirmed hidden
metadata and clipped stacked targets. Current generation intentionally uses a
new contract and refuses to overwrite these files. Use
[the current dataset workflow](../../docs/SYNTHETIC_DATA.md) for new data.
The commands below describe old source revisions only; do not run them here.

Historical hard-mode evaluation set (git tag `eval-v1`). It replaced
`eval-v0` in the original experiment; both now remain qualified diagnostic evidence.
See `CHANGELOG.md` at the repo root for what changed and why (scorer fixes are
model-neutral or favor the baselines; the generator escalation targets realism:
denser data, truncated/unrounded value axes, K/M/B ticks, similar palettes,
smaller figures, heavier degradation).

## What's committed vs regenerable

- **Committed:** `test.jsonl` (1000 held-out hard charts) and `val.jsonl` (500).
- **Not committed (regenerable):** `images/` and `train.jsonl` (3500).

## Historical recipe (requires its original source revision)

```bash
python -m unrender.data_gen.generate      --n 5000 --out data/synthetic_v1 --seed 5678 --hard
python -m unrender.data_gen.split_dataset --out data/synthetic_v1 --val-size 500 --test-size 1000   # split seed 7 (default)
```

The old recipe used `seed + index` on its historical hard sampling path.
Current code produces different targets. Source, fonts, rendering environment
and exact split membership must match to attempt historical reconstruction;
original image hashes were not recorded.

## Composition (test split, n=1000)

- **labels_shown:** 622 label-free / 378 labeled.
- **chart types:** bar 207 · multi_line 167 · line 152 · grouped_bar 150 ·
  horizontal_bar 113 · stacked_bar 106 · pie 105.
- **augmented:** 945/1000 (hard split uses 0.95 augmentation fraction).
- **hard-mode features:** 15–60 points per single-series chart; 4–6
  similar-shade series on multi-series; ~60% truncated (non-zero) y-baselines;
  ~70% unrounded axis maxima; K/M/B tick suffixes on large-scale charts;
  gridlines off ~65%; smaller figures (3.2–5.5 × 2.6–4.2 in).

Each row carries `meta: {labels_shown, chart_type, augmented}` for the sliced
scorer. Label-free pies are scored on proportions (see `eval/metrics.py`).
