# eval-v0 — frozen evaluation set

Pre-registered evaluation set for Unrender (git tag `eval-v0`). Freezing it means
nobody — including us — can tune the generator or the test after seeing baseline
results: the ground truth and the recipe are committed.

## What's committed vs regenerable

- **Committed:** `test.jsonl` (1000 held-out charts) and `val.jsonl` (500) — the
  ground-truth labels + slice metadata + image paths. This is the frozen eval.
- **Not committed (regenerable):** `images/` (1.5 GB) and `train.jsonl` (3500).
  Regenerate them byte-for-byte from the recipe below; the deterministic
  seed + index mapping reproduces the exact same files the committed splits
  reference.

## Reproduce

```bash
python -m unrender.data_gen.generate     --n 5000 --out data/synthetic_v0 --seed 1234
python -m unrender.data_gen.split_dataset --out data/synthetic_v0 --val-size 500 --test-size 1000   # split seed 7 (default)
```

Each chart is fully determined by `seed + index`, so indices 0..4999 are stable.
Byte-identical **images** additionally require the same rendering stack:

| tool | version |
|---|---|
| python | 3.11.15 |
| matplotlib | 3.10.9 |
| numpy | 2.4.6 |
| pillow | 12.2.0 |

(Labels/ground truth are version-independent — only the rendered pixels depend on
matplotlib's version.)

## Composition (test split, n=1000)

- **labels_shown:** 543 label-free / 457 labeled — the label-free majority is the
  metric that matters (the model must read geometry, not OCR printed numbers).
- **chart types:** bar 199 · line 143 · grouped_bar 142 · stacked_bar 142 ·
  multi_line 141 · horizontal_bar 132 · pie 101.

Each row carries `meta: {labels_shown, chart_type, augmented}` so the scorer can
slice. See the repo README's "Eval harness" section for how to run baselines.
