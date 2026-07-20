# real_v0 — the real-chart transfer eval

Everything else in this repo is measured on **synthetic** charts (common300). This
set answers the only question that decides the project's direction:

> On charts the model never trained on — does our fine-tune transfer, and is
> frontier (Gemini) actually weak at exact extraction the way the bet assumes?

See `MODEL_STATUS_REVIEW.md` ("Claim Boundaries") and the audit: real-world
validity is the gate that has never been tested.

## The one rule

You supply each chart's **exact true values by hand**, read off a source that
*publishes the numbers* (FRED, OWID, a data table behind the figure) — **never
machine-estimated from the pixels.** If the ground truth were a model's guess, the
benchmark would measure nothing. ~15–20 charts is enough for a first read; spread
them across chart types and across `labels_shown` true/false.

## Quick start — auto-source from FRED + OWID (needs internet)

FRED and OWID publish the rendered chart PNG **and** the official data CSV at
parallel URLs, so the ground truth is read straight from the published data — no
hand-typing, no pixel-estimation. Run this **on a machine with internet** (the
agent sandbox has none):

```
python -m unrender.eval.fetch_real_set            # -> data/real_v0/{images,labels} (9 line charts)
python -m unrender.eval.build_real_set --dir data/real_v0
```

It seeds real **line** time series (US unemployment, rates, CPI, GDP, payrolls, life
expectancy — all `labels_shown=false`, the measure-off-the-axis case). Line-only by
design (FRED/OWID series are line charts); add bar/pie charts of your own via the
manual workflow below for full type coverage.

## Workflow (manual / add your own)

1. **Drop images** into `images/` (e.g. `images/us_unemployment.png`).
2. **Label each** — copy `labels/_TEMPLATE.json` to `labels/<name>.json`, fill in
   the true values. Set `labels_shown` honestly (are exact numbers printed on the
   chart?) — it drives the labeled-vs-label-free slice the thesis turns on.
3. **Build** the eval set (validates every label, fails loudly on a typo):

   ```
   python -m unrender.eval.build_real_set --dir data/real_v0
   ```

   → writes `test.jsonl` (local paths) and `test.modal.jsonl` (/vol paths).

### Arm 1 — Gemini (local, ~$1–2)

```
python -m unrender.eval.run_baselines --provider gemini \
    --model gemini-3.1-pro-preview \
    --data data/real_v0/test.jsonl --out outputs/real_v0/gemini
python -m unrender.eval.score --predictions outputs/real_v0/gemini/predictions.jsonl
```
(Use the current flagship id; the default `gemini-3.1-pro` has 404'd before — the
`-preview` id is the real one. Add `--provider anthropic`/`openai` for more.)

### Arm 2 — base-4B + table-LoRA (Modal GPU, ~$1–2)

Upload images + the /vol-pathed jsonl (renamed to `test.jsonl` on the volume), then
eval each model with `--data real_v0` (eval_model routes `real_*` → `data/real_v0`):

```
modal volume put unrender-vol data/real_v0/images          /vol/data/real_v0/images
modal volume put unrender-vol data/real_v0/test.modal.jsonl /vol/data/real_v0/test.jsonl

# table-only LoRA (the strongest arm so far, 36.8% on synthetic common300)
modal run --detach modal_train.py::evaluate --model runs/qwen3vl4b-lora/merged --data real_v0
# pinned base control (same revision as the synthetic base run)
modal run --detach modal_train.py::evaluate \
    --model unsloth/Qwen3-VL-4B-Instruct \
    --revision 252d592b59b0233b226875a44ac135cfa1d3f755 --data real_v0
```

Pull + (re)score locally:
```
modal volume get unrender-vol outputs/eval_v1__qwen3vl4b-lora__real_v0 ./outputs/real_v0/lora
python -m unrender.eval.score --predictions outputs/real_v0/lora/predictions.jsonl
```

## Reading it

Compare cell@5_exact (and the labeled / label-free slices) across Gemini, base-4B,
and the LoRA on the SAME real charts:

- **Frontier weak + LoRA competitive** → the wedge is real → worth scaling.
- **Gemini strong / LoRA doesn't transfer** → "beats frontier" is retired; ship the
  benchmark + reliability story instead.

> Tracked as **R00c / R012** in `refine-logs/EXPERIMENT_TRACKER.md`.
