# Unrender Model Status Review Brief

Date: 2026-06-14

## Review request

Act as a skeptical senior ML reviewer. Assess the current status of Unrender,
identify what the first LoRA run actually proves, and design the smallest next
experiment package with the highest information gain per GPU dollar.

Please answer:

1. Is an 8B run justified now, or should the 4B training/evaluation recipe be
   repaired first?
2. Which observed failures are primarily model capacity, optimization,
   decoding, or benchmark/image-quality problems?
3. What ablations are required before making a narrow-model-vs-frontier claim?
4. What is the minimum real-world evaluation needed before product launch?
5. Give a prioritized experiment queue with expected decision value, compute
   cost, and explicit go/no-go criteria.

## Project thesis

Unrender converts chart images to strict JSON/CSV. The research bet is that a
small Qwen3-VL model fine-tuned on unlimited synthetic chart/ground-truth pairs
can beat frontier VLMs on exact chart digitization, especially when values are
not printed and must be inferred from geometry.

The frozen hard evaluation set, `eval-v1`, contains 1,000 synthetic charts:

- Seven chart types.
- 15-60 points for most non-pie charts.
- 4-6 visually similar series for multi-series charts.
- 622 label-free and 378 labeled charts.
- 945/1,000 augmented.
- Small figures, non-zero value-axis baselines, unrounded maxima, K/M/B ticks,
  missing gridlines, blur/JPEG/noise/rescaling.

Cell accuracy is the pooled fraction of ground-truth points recovered within
5% relative error. A 2% strict track and exact-chart rate are also reported.
Label-free pies are scored by normalized proportions because absolute values
are not identifiable from geometry.

## First fine-tune

- Base: Qwen3-VL-4B-Instruct, Unsloth 4-bit.
- LoRA rank/alpha: 16/16.
- Vision and language layers both targeted.
- Training data: synthetic v1 + v0 training splits.
- Label-free examples oversampled 1.5x.
- Effective batch size: 8.
- Learning rate: 2e-4, linear decay, 10 warmup steps.
- Epochs: 2, 2,250 optimizer steps.
- No validation dataset, validation metric, early stopping, or best-checkpoint
  selection.
- Final merged model evaluated deterministically with `do_sample=False`.
- Generation cap: 4,096 new tokens.

Training loss:

| Step range | Mean train loss |
| --- | ---: |
| 251-500 | 0.2059 |
| 501-1000 | 0.1939 |
| 1001-1500 | 0.1811 |
| 1501-2000 | 0.1807 |
| 2001-2250 | 0.1765 |

The curve still declines slightly, but there is no held-out validation curve.

## Full LoRA result on all 1,000 hard charts

| Metric | Result |
| --- | ---: |
| Cell accuracy @5% | 34.8% |
| Cell accuracy @2% | 28.9% |
| Exact-chart @5% | 8.0% |
| Label-free @5% | 33.4% |
| Labeled @5% | 37.5% |
| Schema-valid | 97.2% |
| Chart-type accuracy | 96.9% |
| Median relative value error | 18.6% |

The model learned the schema, chart type, titles, and axis labels well, but
numeric precision remains poor.

## Fair four-model comparison

The current saved frontier runs have incomplete and different coverage. The
strict common intersection where all four models produced an `ok` response is
only N=74:

| Model | Cell@5% | Cell@2% | Exact-chart | Label-free | Labeled |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3-VL-4B LoRA | 32.5% | 27.6% | 4.1% | 29.3% | 38.2% |
| GPT-5.5 | 35.4% | 31.1% | 6.8% | 31.4% | 42.6% |
| Claude Fable 5 | 42.2% | 38.0% | 13.5% | 39.0% | 48.0% |
| Gemini 3.1 Pro | 63.5% | 57.2% | 27.0% | 57.2% | 74.9% |

Chart-level bootstrap differences at cell@5%:

- LoRA minus GPT: -2.85 percentage points, 95% CI [-9.55, +3.83].
- LoRA minus Claude: -9.74 points, 95% CI [-16.77, -3.05].
- LoRA minus Gemini: -31.09 points, 95% CI [-39.90, -22.12].

Therefore LoRA is statistically unresolved versus GPT on this small
intersection, but clearly behind Claude and Gemini.

## LoRA failure slices on all 1,000 charts

| Slice | N | Cell@5% |
| --- | ---: | ---: |
| <=20 points | 260 | 60.3% |
| 21-35 points | 428 | 36.2% |
| 36-50 points | 268 | 28.2% |
| >50 points | 44 | 22.7% |
| Not augmented | 50 | 42.0% |
| Augmented | 950 | 34.4% |
| No truncated baseline | 634 | 37.3% |
| Truncated baseline | 366 | 31.2% |
| No K suffix | 833 | 36.2% |
| K suffix | 167 | 28.5% |

By chart type:

| Type | Cell@5% | Invalid-output rate |
| --- | ---: | ---: |
| Pie | 59.6% | 0.0% |
| Grouped bar | 44.6% | 1.3% |
| Multi-line | 37.8% | 0.6% |
| Bar | 32.6% | 4.4% |
| Line | 31.6% | 2.0% |
| Horizontal bar | 27.5% | 11.9% |
| Stacked bar | 25.8% | 0.0% |

## Decoding failure

Twenty-eight outputs are invalid JSON. Most are not ordinary JSON formatting
errors: the model enters a repetition loop, invents hundreds of categories
such as `Country 296`, and runs until the 4,096-token generation cap. One short
output contains a malformed number. Raising the token cap alone would worsen
the looping cases. Structured/constrained decoding, repetition controls, or
training changes may be needed.

## Benchmark readability concern

Manual inspection found examples that are severely degraded and arguably
unreadable even by a careful human:

- 36-category horizontal bars rendered at 400x280 with overlapping labels.
- Dense stacked bars with similar shades at roughly 430x409.
- Labeled 24-point horizontal bars at 374x244 after blur/noise, with text and
  labels overlapping.

This does not erase the frontier comparison because all models see the same
images, and Gemini still reaches 61.2% on the larger three-provider N=155
intersection. It does mean the benchmark mixes chart-reading ability with
information loss, output length, and OCR crowding.

## Current interpretation

Supported:

- The end-to-end data, training, inference, and evaluation pipeline works.
- The 4B LoRA learns output structure reliably.
- It does not beat frontier models on the first hard-set run.
- Numeric measurement, density, horizontal bars, stacked bars, suffixes, and
  decoding stability are the main failure modes.

Not yet supported:

- That simply training longer will fix numeric precision.
- That the 8B model will beat frontier systems.
- That the synthetic benchmark transfers to real-world charts.
- That the hard-set aggregate alone represents product usefulness.

## Available compute

Modal L4 and A100 are available. The project aims to keep the next round under
roughly $15-25. The desired output is a short experiment queue, not a broad
research program.
