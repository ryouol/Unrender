# Unrender

**Recover the exact underlying data from a chart image.** Unrender is a
specialized vision-language model (Qwen-VL + LoRA) fine-tuned to *un-render*
charts — turning a bar/line/pie image back into the structured JSON and CSV it
was drawn from.

**The bet:** frontier VLMs (GPT, Claude, Gemini) are surprisingly weak at
reading *exact* values off charts — especially when the numbers aren't printed
and must be measured against the axis scale. A small model trained on unlimited,
perfectly-labeled synthetic charts can beat them at this one narrow task, at a
fraction of the cost per chart. The win is a *narrow model + brutal eval + clean
product*, not a bigger model.

## Status

- [x] **Phase 1 — Synthetic data engine** (built, runs on a MacBook)
- [x] **Phase 2 — Eval harness + frontier baselines** (scorer + provider runners + comparison report)
- [ ] Phase 3 — LoRA fine-tune on a rented GPU
- [ ] Phase 4 — Deploy: Hugging Face Space demo + inference API
- [ ] Phase 5 — Launch with reproducible receipts (weights, dataset, eval, demo)

## Pipeline

```
PDF / chart image
   │  (render PDF page → image; later: crop chart region)
   ▼
Fine-tuned Qwen-VL + LoRA      image → strict JSON
   │
   ▼
JSON validator + 1 repair      pure Python, never an LLM (keeps the claim honest)
   │
   ▼
CSV export  (+ optional redraw of the chart for a visual sanity check)
```

Everything except the model is plain Python that runs anywhere. Only the model
needs a GPU, and only for training.

## What's here now: the synthetic data engine

The moat isn't the model — it's that we can generate **unlimited (image, exact
JSON) pairs**. Each chart is rendered with matplotlib from a known spec, so the
ground-truth label is exact by construction (the numbers printed on the chart
are formatted *from* the label).

| Module | Role |
|---|---|
| `unrender/prompts.py` | The one canonical extraction prompt (train = eval = inference) |
| `unrender/schema/` | Pydantic `ChartData` schema, JSON validation/repair, CSV export |
| `unrender/data_gen/chart_specs.py` | Random-but-coherent chart specs (the ground truth) |
| `unrender/data_gen/render.py` | matplotlib rendering for all 7 chart types |
| `unrender/data_gen/augment.py` | Degradations (blur, JPEG, rescale, rotate, noise) for the synthetic→real gap |
| `unrender/data_gen/generate.py` | Parallel dataset generation CLI |
| `unrender/data_gen/split_dataset.py` | Train/val/test split in chat-SFT JSONL |
| `unrender/eval/metrics.py` | The scorer: cell accuracy, exact-chart rate, label F1, … |
| `unrender/eval/providers.py` | Model providers (OpenAI / Anthropic / Gemini / local HF + mock) |
| `unrender/eval/run_baselines.py` | Run a model over the eval set → predictions (resumable, saves raw) |
| `unrender/eval/score.py` · `report.py` | Score predictions → report; aggregate → comparison table |

Chart types: `bar`, `horizontal_bar`, `grouped_bar`, `stacked_bar`, `line`,
`multi_line`, `pie`.

**The key knob:** ~half the charts are rendered *without* value labels. When
values aren't printed, the model must measure bar height / line position / pie
angle against the axis scale — exactly the skill frontier models lack.

## Quickstart

```bash
brew install python@3.11
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                                              # round-trip sanity checks

# Generate data (start small to prove the loop, then scale to 50k+).
python -m unrender.data_gen.generate --n 1000 --out data/synthetic
python -m unrender.data_gen.split_dataset --out data/synthetic --val-size 100 --test-size 200
```

Output:

```
data/synthetic/
  images/0000000.png ...        # the chart images
  labels/0000000.json ...       # exact ground-truth ChartData JSON
  manifest.jsonl                # {id, image, label, chart_type} per sample
  train.jsonl / val.jsonl / test.jsonl   # chat-format SFT rows
```

Generation runs across all CPU cores (~hundreds of charts/sec on Apple Silicon)
and is fully reproducible: sample `i` is always derived from `seed + i`, so you
can grow the set with `--start-index` without regenerating earlier samples.

## Output schema

```jsonc
{
  "chart_type": "bar | horizontal_bar | grouped_bar | stacked_bar | line | multi_line | pie",
  "title": "string or null",
  "x_axis": {"label": "string or null", "unit": "string or null"},
  "y_axis": {"label": "string or null", "unit": "string or null"},
  "series": [
    {"name": "string or null", "points": [{"x": "string or number", "y": 0.0}]}
  ]
}
```

## Eval harness (Phase 2)

Get the "before" numbers **before** training. Inference and scoring are
decoupled: each model run saves every raw response to a `predictions.jsonl`, and
the scorer reads those files — so you re-score for free when you tweak a metric,
and never re-pay an API. Runs are resumable (failed samples are retried, not
frozen in).

The **frozen eval set lives at `data/synthetic_v0/`** (tag `eval-v0`): 1000
held-out test charts, pre-registered so results can't be tuned after the fact.
Regenerate it byte-for-byte from the recipe in `data/synthetic_v0/README.md`.

```bash
pip install -e ".[eval]"          # adds rapidfuzz + openai/anthropic/google-genai
cp .env.example .env              # put your API keys here

# 1. Sanity-check the whole pipeline with mock providers — no API, no cost:
python -m unrender.eval.run_baselines --provider perfect --data data/synthetic_v0/test.jsonl
python -m unrender.eval.score --predictions outputs/eval_reports/perfect__oracle/predictions.jsonl
#   perfect -> 100% everything; try --provider noisy to see the metrics degrade.

# 2. Frontier baselines — each lab's flagship at temp 0 (~$25 for all three, resumable).
#    Pass --model to override when newer models ship.
python -m unrender.eval.run_baselines --provider anthropic --model claude-fable-5  --data data/synthetic_v0/test.jsonl --limit 300
python -m unrender.eval.run_baselines --provider openai    --model gpt-5.5         --data data/synthetic_v0/test.jsonl --limit 300
python -m unrender.eval.run_baselines --provider gemini    --model gemini-3.1-pro  --data data/synthetic_v0/test.jsonl --limit 300

# 3. Score each, build the sliced comparison, and dump the worst charts to stare at:
python -m unrender.eval.score   --predictions outputs/eval_reports/anthropic__claude-fable-5/predictions.jsonl
python -m unrender.eval.report  --reports outputs/eval_reports --out outputs/eval_reports/COMPARISON.md
python -m unrender.eval.failures --predictions outputs/eval_reports/anthropic__claude-fable-5/predictions.jsonl --n 15
```

**Headline metric:** `cell_accuracy` — fraction of ground-truth data points
recovered within 5% relative error. But the aggregate is nearly useless on its
own; the **slice is the deliverable**. `report.py` splits cell accuracy
**labeled vs label-free** (with the gap) and breaks label-free accuracy down
**per chart type**. When values aren't printed on the chart, the model must read
geometry against the axis scale — that label-free column is the wedge. The
scorer aligns series by fuzzy name and points by fuzzy x-label (robust to
ordering/label noise), and uses global best-match assignment so similar names
can't steal each other's match.

**The decision rule:** if label-free cell accuracy sits 15+ points below labeled
(expected, especially on grouped/stacked/multi-line), the wedge is confirmed →
proceed to a 2k-sample smoke train. If frontier models are strong even
label-free, do **not** train yet — escalate the generator (truncated y-axes,
dense multi-series, harder degradations) and re-baseline until the eval contains
a gap worth attacking.

The `hf` provider runs the base open model (and later your fine-tune) on the GPU
box; its predictions drop into the same scorer. Still to add for full
credibility: a small **real-world** test set (FRED / Our World in Data charts
whose CSVs are downloadable) so the claim isn't "only on my own synthetic data."

## Next steps (Phase 3)

Iteration base is **Qwen3-VL-4B**, launch base **Qwen3-VL-8B** (same Unsloth
path; the 2.5 family is skipped). Fine-tune with LoRA on a rented GPU (~$5–25/run)
using `data/synthetic_v0/train.jsonl`, run the Phase-2 scorer, read `FAILURES.md`,
generate charts targeting those failures, and repeat. Then deploy (Phase 4).

## Hardware

A MacBook does ~80% of the work (data generation, eval scripts, the demo app,
frontier-API benchmarking). GPUs are **rented** only for training runs
(RTX 4090 ~$0.40/hr, A100 80GB ~$0.7–1.2/hr; a full run is $5–25). Total project
budget is roughly $150–350 including failed runs and API eval costs.

## License

Apache-2.0.
