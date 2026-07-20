# Unrender Model Status Review

Date: 2026-06-14

Review method: ARIS `analyze-results` workflow plus two-round external review
with Claude Opus 4.8. Full review trace:
`.aris/traces/research-review/2026-06-14_run01/`.

## Verdict

The first full Qwen3-VL-4B LoRA run is a successful pipeline validation, but it
does not validate the central "small model beats frontier models" thesis.

Do not start the 8B fine-tune yet. First repair the 4B measurement and training
recipe so the next result can distinguish capacity, optimization, decoding,
and benchmark readability.

## Current State

- Full LoRA training completed: 2 epochs, 2,250 optimizer steps.
- Full hard-set evaluation completed: 1,000/1,000 charts.
- No Modal app is currently running.
- The merged model, adapter, checkpoints, predictions, and report remain on the
  `unrender-vol` Modal volume.
- The README status checklist is stale: Phase 3 has begun and the first full
  fine-tune/evaluation is complete.

## Full LoRA Result

| Metric | Qwen3-VL-4B LoRA |
| --- | ---: |
| Cell accuracy @5% | 34.8% |
| Cell accuracy @2% | 28.9% |
| Exact chart @5% | 8.0% |
| Label-free @5% | 33.4% |
| Labeled @5% | 37.5% |
| Schema valid | 97.2% |
| Chart type correct | 96.9% |
| Median relative value error | 18.6% |

The model learned the response contract, chart taxonomy, titles, and axis
labels. It did not learn sufficiently reliable numeric measurement.

## Fair Frontier Comparison

The strict four-model intersection contains only 74 charts because the frontier
runs have incomplete coverage and the LoRA has 28 invalid outputs.

| Model | Cell@5% | Cell@2% | Exact chart | Label-free |
| --- | ---: | ---: | ---: | ---: |
| Gemini 3.1 Pro | 63.5% | 57.2% | 27.0% | 57.2% |
| Claude Fable 5 | 42.2% | 38.0% | 13.5% | 39.0% |
| GPT-5.5 | 35.4% | 31.1% | 6.8% | 31.4% |
| Qwen3-VL-4B LoRA | 32.5% | 27.6% | 4.1% | 29.3% |

Chart-level bootstrap, LoRA minus competitor:

| Comparison | Mean difference | 95% confidence interval |
| --- | ---: | ---: |
| LoRA - GPT-5.5 | -2.85 pp | [-9.55, +3.83] |
| LoRA - Claude | -9.74 pp | [-16.77, -3.05] |
| LoRA - Gemini | -31.09 pp | [-39.90, -22.12] |

The LoRA/GPT difference is unresolved at this sample size. The model is clearly
behind Claude and Gemini.

## Failure Diagnosis

### 1. Numeric measurement

Seventeen percent of matched values are exactly correct, but median relative
error across matched values is about 21.9%. Errors are not a small calibration
miss; many values are badly wrong.

### 2. Output degeneration

Twenty-eight responses are invalid. Most enter a repetition loop, invent
hundreds of categories such as `Country 296`, and continue until the existing
4,096-token cap. Increasing the cap is not a fix.

Horizontal bars are especially unstable: 27.5% cell accuracy and 11.9% invalid
outputs.

### 3. Density and readability are confounded

| Ground-truth points | N | Cell@5% |
| --- | ---: | ---: |
| 20 or fewer | 260 | 60.3% |
| 21-35 | 428 | 36.2% |
| 36-50 | 268 | 28.2% |
| More than 50 | 44 | 22.7% |

Several dense charts are near-illegible to a human after being rendered around
400x280 and heavily degraded. Density failure cannot yet be assigned solely to
model capacity.

### 4. Hard visual features matter

| Slice | Cell@5% |
| --- | ---: |
| Unaugmented | 42.0% |
| Augmented | 34.4% |
| No truncated baseline | 37.3% |
| Truncated baseline | 31.2% |
| No K suffix | 36.2% |
| K suffix | 28.5% |

These are targeted data/training problems, not evidence that 4B capacity is
exhausted.

### 5. Training selection is missing

Training loss continued declining:

| Step range | Mean loss |
| --- | ---: |
| 251-500 | 0.2059 |
| 501-1000 | 0.1939 |
| 1001-1500 | 0.1811 |
| 1501-2000 | 0.1807 |
| 2001-2250 | 0.1765 |

There was no validation generation, task metric, early stopping, or
best-checkpoint selection. Training longer may help, hurt, or do nothing; the
current evidence cannot decide.

## Next Experiment Queue

### 1. Base-model controls

Evaluate stock Qwen3-VL-4B and Qwen3-VL-8B on a fixed, stratified 300-chart
subset using the same prompt and decoder.

Decision value:

- LoRA versus base 4B measures whether fine-tuning helped.
- Base 8B versus base 4B is a cheap capacity probe before an 8B fine-tune.

### 2. Decoder sweep without retraining

Use the 28 invalid charts plus 200 randomly selected valid charts:

- Current greedy decoding as control.
- `repetition_penalty=1.1`.
- `repetition_penalty=1.3`.
- JSON grammar/constrained decoding with bounded series and point counts.
- Low-temperature sampling only if greedy decoding still loops.

Adopt a decoder only if invalid output falls below 1% without reducing cell
accuracy on previously valid charts by more than one point. Avoid small
`no_repeat_ngram_size` values because legitimate JSON repeats keys and syntax.

### 3. Readability control

Blindly label approximately 100 stratified eval charts:

- Can a careful human recover values within 5%?
- Record readable/unreadable before seeing model predictions.

Have a human digitize roughly 30 difficult but readable charts to estimate the
achievable ceiling.

### 4. Repair 4B training

Every new run should:

- Use a training-derived validation set, never `eval-v1`.
- Generate predictions on a fixed 128-chart validation subset periodically.
- Select checkpoints by validation cell@5%, not training or validation loss.
- Use the winning decoder from the decoder sweep.

Minimum three runs:

| Run | Target | Learning rate | Purpose |
| --- | --- | ---: | --- |
| A | Current canonical JSON | 2e-4 | Repaired anchor |
| B | Compact deterministic target | 2e-4 | Test sequence/number supervision |
| C | Compact deterministic target | 1e-4 | Test LR sensitivity |

A compact target should have a deterministic converter back to `ChartData`.
Because it changes the output contract, model comparisons must either prompt
all models with the same compact contract or clearly label this as a
specialized-model interface experiment.

Numeric-token loss weighting is second-line. Test it only if compact targets
reduce repetition but numeric accuracy remains flat.

## 8B Gate

Unlock an 8B fine-tune only when all are true:

1. Invalid output is below 1%.
2. Evaluation is reported on a human-readable stratum.
3. The best 4B checkpoint is selected by validation cell accuracy and its
   validation curve has plateaued.
4. Remaining failures are distributed rather than concentrated in suffixes,
   truncated axes, horizontal bars, or another targetable slice.
5. Base Qwen3-VL-8B materially beats base 4B on the same readable subset.

If those conditions hold and the repaired 4B remains at least ten points below
the human ceiling, capacity becomes a defensible hypothesis.

## Claim Boundaries

Supported now:

- The full synthetic training/evaluation pipeline works.
- The 4B LoRA reliably learns structured output.
- The first LoRA does not beat frontier models on `eval-v1`.
- It is statistically unresolved against GPT-5.5 on the small four-way
  intersection and clearly behind Claude/Gemini.

Unsupported now:

- Training longer will solve precision.
- 8B will beat frontier models.
- Synthetic performance transfers to real charts.
- The hard-set aggregate represents product usefulness.

Product launch should additionally require a real-world set of approximately
100-200 charts and either higher accuracy than the best affordable frontier
API, or comparable accuracy with a material cost, latency, privacy, or
deployment advantage.
