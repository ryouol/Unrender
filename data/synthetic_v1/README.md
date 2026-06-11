# eval-v1 — frozen hard evaluation set

Pre-registered hard-mode evaluation set (git tag `eval-v1`). Supersedes
`eval-v0` for the headline benchmark; v0 stays frozen as the historical record.
See `CHANGELOG.md` at the repo root for what changed and why (scorer fixes are
model-neutral or favor the baselines; the generator escalation targets realism:
denser data, truncated/unrounded value axes, K/M/B ticks, similar palettes,
smaller figures, heavier degradation).

## What's committed vs regenerable

- **Committed:** `test.jsonl` (1000 held-out hard charts) and `val.jsonl` (500).
- **Not committed (regenerable):** `images/` and `train.jsonl` (3500).

## Reproduce

```bash
python -m unrender.data_gen.generate      --n 5000 --out data/synthetic_v1 --seed 5678 --hard
python -m unrender.data_gen.split_dataset --out data/synthetic_v1 --val-size 500 --test-size 1000   # split seed 7 (default)
```

Each chart is fully determined by `seed + index` on the hard RNG path
(`random_spec(hard=True)`); the easy path is untouched, so `eval-v0` still
reproduces byte-identically from its own recipe. Byte-identical images require
the same rendering stack as v0 (python 3.11.15, matplotlib 3.10.9, numpy 2.4.6,
pillow 12.2.0); labels are version-independent.

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
