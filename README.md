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
- [x] **Phase 3 — LoRA fine-tune + integrity audit** — the 4B LoRA (fair val/best-checkpoint protocol) scores **38.9% `cell@5_exact`** on the 300-chart hard held-out set vs **13.5%** for the pinned base — **+25.5pp, 95% CI [+22.7, +28.6]** — and **67% vs 31%** on real OWID charts. Pinned base control, leak-free split, and paired bootstrap all done. Receipts: [`RESULTS.md`](RESULTS.md).
- [~] **Phase 4 — Deploy** — one-command inference works (`modal run modal_train.py::infer`); public Hugging Face weights + demo still to publish.
- [ ] Phase 5 — Launch with reproducible receipts (weights, dataset, eval, demo)

> **Where the bet stands** (full numbers + caveats in [`RESULTS.md`](RESULTS.md)): fine-tuning
> decisively beats the base model and transfers to real charts. Against frontier it is **at
> parity with GPT-5.5** and **behind Claude and Gemini** on the hard synthetic set — so "narrow
> model beats frontier" is **partly demonstrated** (vs GPT-5.5, and on real charts modulo a
> contamination caveat), not yet a clean sweep. `synthetic_v2` (values to 1e9, real axis formats)
> is built and staged for the next retrain but **not yet trained** — today's numbers are the
> v0+v1 model.

## Results

Hard held-out set **common300** (`cell@5_exact` = ground-truth points recovered within 5%):

| System | cell@5_exact |
|---|---:|
| pinned base Qwen3-VL-4B | 13.5% |
| **table-LoRA (this project)** | **38.9%** |

Fine-tuning beats the base by **+25.5pp** (95% CI [+22.7, +28.6], paired bootstrap, PASS), and
drops invalid JSON from 9% to 0%. Paired against each frontier model on the charts both answered:
**parity with GPT-5.5** (+1.2pp, N=63), behind **Claude-fable-5** (−5.8pp, N=86) and
**Gemini-3.1-Pro** (−28.3pp, N=64).

Real-world transfer (**real_v0**, 8 OWID line charts, all label-free, ground truth from the
official CSVs): **table-LoRA 67% vs base 31%.** Gemini scores 100% here, but that is
**memorization of famous public series, not chart-reading** — so the real-chart head-to-head is
not valid until a contamination-resistant set exists. Every number is regenerated from saved
predictions by `python analysis/scoreboard.py` → [`RESULTS.md`](RESULTS.md).

## Use the model

The fine-tuned weights live on a Modal Volume (`unrender-vol`), so inference runs serverless —
**no local GPU needed.** Extract the data from one chart image in a single command:

```bash
pip install modal && modal setup                         # once (Modal account + CLI)
modal run modal_train.py::infer --image path/to/chart.png
```

It prints the strict-JSON `ChartData` and the CSV. Under the hood it loads the merged model on a
GPU worker, runs the same greedy decode + JSON repair as the eval harness, and returns:

```
=== JSON ===
{"chart_type": "line", "title": "Life expectancy",
 "x_axis": {"label": "Year", "unit": null},
 "y_axis": {"label": "Years", "unit": null},
 "series": [{"name": "USA", "points": [{"x": "2000", "y": 76.8}, {"x": "2001", "y": 76.9}, ...]}]}
=== CSV ===
Year,Years
2000,76.8
2001,76.9
...
```

- Defaults to the best model (`runs/qwen3vl4b-table-fair/merged`); pass `--model` to try another,
  or `--model unsloth/Qwen3-VL-4B-Instruct --revision <sha>` for the base.
- Pull the weights to run them yourself: `modal volume get unrender-vol runs/qwen3vl4b-table-fair`,
  then load `.../merged` with `transformers` (`AutoModelForImageTextToText` — see
  `unrender/eval/providers.py::hf_vlm_provider`).
- **Publishing (optional, not done):** `modal_train.py::publish` pushes the merged model to the
  Hugging Face Hub from the Volume (needs an `HF_TOKEN` Modal secret) so anyone can
  `from_pretrained` it. Left unrun — the weights are private until you publish.

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
| `unrender/schema/` | Pydantic `ChartData` schema, JSON validation + repair (fences, truncation, `"1.2B"`/`"1,200"`/`"12%"` number coercion), CSV export |
| `unrender/data_gen/chart_specs.py` | Random-but-coherent chart specs (the ground truth) |
| `unrender/data_gen/render.py` | matplotlib rendering for all 7 chart types |
| `unrender/data_gen/augment.py` | Degradations (blur, JPEG, rescale, rotate, noise) for the synthetic→real gap |
| `unrender/data_gen/generate.py` | Parallel dataset generation CLI |
| `unrender/data_gen/split_dataset.py` | Train/val/test split in chat-SFT JSONL |
| `unrender/eval/metrics.py` | The scorer: cell accuracy, exact-chart rate, label F1, … |
| `unrender/eval/providers.py` | Model providers (OpenAI / Anthropic / Gemini / local HF + mock) |
| `unrender/eval/run_baselines.py` | Run a model over the eval set → predictions (resumable, saves raw) |
| `unrender/eval/score.py` · `report.py` | Score predictions → report; aggregate → comparison table |
| `unrender/eval/paired_bootstrap.py` | Paired chart-level bootstrap (base-vs-LoRA gate: gap + 95% CI) |
| `unrender/eval/ensemble.py` | Self-consistency vote over k sampled runs (no-retrain inference lever) |

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

Frozen eval sets are committed (test/val splits + a byte-exact regen recipe per
`data/*/README.md`), pre-registered so results can't be tuned after the fact: `data/synthetic_v0/`
(tag `eval-v0`, easy) and `data/synthetic_v1/` (hard) — the headline runs on **common300**, a
frozen, table-level-deduped, leak-free 300-chart subset of the v1 test set
(`unrender/eval/subsets/common300.json`). `data/synthetic_v2/` (values to 1e9 + real-world axis
formats/themes) is staged for the next retrain. A real-world set (`data/real_v0/`, OWID charts
with official-CSV ground truth) closes the synthetic-only gap.

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

The `hf` provider runs the base open model or your fine-tune on the GPU box; its
predictions drop into the same scorer. The **real-world** test set (`data/real_v0/`: Our World in
Data charts whose CSVs are downloadable, ground truth read from the official CSV — never
pixel-estimated) is built, so the claim isn't "only on my own synthetic data."

## Fine-tune (Phase 3)

Iteration base is **Qwen3-VL-4B**, launch base **Qwen3-VL-8B** (same Unsloth
path; the 2.5 family is skipped). LoRA fine-tune lives in
`unrender/train/sft_lora.py` — it feeds the chat-format split rows straight to
the trainer, so the prompt and JSON target match the eval harness exactly (no
re-specifying the task). The vision tower is fine-tuned too, since reading
label-free geometry is a visual skill, not just text generation.

**On Modal (what we use):** `modal_train.py` wraps the whole pipeline — data gen
onto a persistent Volume (exact pinned rendering stack, so the frozen recipes
reproduce byte-for-byte), Unsloth LoRA training, and eval through the same
harness as the frontier baselines. Per-second billing, nothing to terminate.

```bash
pip install modal && modal setup                  # once
modal run modal_train.py::gen                      # v0+v1 data -> Volume (CPU, ~$0.3)
modal run modal_train.py::check                    # preflight: data integrity + token budget + $ estimate
modal run modal_train.py::smoke                    # 30-step train + tiny eval, exercises val/best-ckpt (~$0.5)
# the fair-protocol LoRA that produced today's model (val + best-checkpoint on eval_loss):
modal run --detach modal_train.py::train --train-files v1,v0 --val-files v1,v0 --out-name qwen3vl4b-table-fair
modal run --detach modal_train.py::evaluate --model runs/qwen3vl4b-table-fair/merged --subset common300
modal volume get unrender-vol outputs ./outputs/modal   # pull predictions/reports
```

The staged next run adds `synthetic_v2` and chains eval into one shot (crash-safe — re-running the
same command resumes from the latest checkpoint):

```bash
modal run modal_train.py::gen_v2                   # synthetic_v2 -> Volume (or build locally + upload)
UNRENDER_GPU=A100 modal run --detach modal_train.py::train \
    --train-files v2,v1,v0 --val-files v2,v1,v0 --epochs 1.0 --out-name qwen3vl4b-v2 \
    --eval-after real_v0,common300 --type-weights multi_line:2,stacked_bar:2,horizontal_bar:2
```

**Or on any rented GPU box** (RunPod/Vast, ~$5–25/run), from the repo root:

```bash
pip install -e ".[train]"             # CUDA-only deps (Unsloth/TRL/bitsandbytes)

# images aren't committed — regenerate them byte-for-byte, then re-split:
python -m unrender.data_gen.generate      --n 5000 --out data/synthetic_v1 --seed 5678 --hard
python -m unrender.data_gen.split_dataset --out data/synthetic_v1

# LoRA fine-tune (v0+v1 mixed; label-free oversampled 1.5x; best checkpoint on a val set):
python -m unrender.train.sft_lora \
    --train data/synthetic_v1/train.jsonl data/synthetic_v0/train.jsonl \
    --val   data/synthetic_v1/val.jsonl   data/synthetic_v0/val.jsonl \
    --labelfree-weight 1.5 --epochs 2 --out runs/qwen3vl4b-table-fair
#   --max-steps 30 first for a cheap smoke run; --base Qwen/Qwen3-VL-8B-Instruct for launch.

# eval the merged model through the SAME scorer as the frontier baselines:
python -m unrender.eval.run_baselines --provider hf --model runs/qwen3vl4b-table-fair/merged \
    --data data/synthetic_v1/test.jsonl --out outputs/eval_v1/unrender-lora
python -m unrender.eval.score --predictions outputs/eval_v1/unrender-lora/predictions.jsonl
```

Then read `FAILURES.md`, generate charts targeting those failures, and repeat.
The biggest remaining credibility gap is still external: add a real-world test
set (see above) so "beats frontier" isn't only true on our own synthetic data.
Then deploy (Phase 4).

## Hardware

A MacBook does ~80% of the work (data generation, eval scripts, the demo app,
frontier-API benchmarking). GPUs are **rented** only for training runs
(RTX 4090 ~$0.40/hr, A100 80GB ~$0.7–1.2/hr; a full run is $5–25). Total project
budget is roughly $150–350 including failed runs and API eval costs.

## License

Apache-2.0.
