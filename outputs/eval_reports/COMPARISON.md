# Unrender eval-v0 (corrected scorer)

Headline cell-accuracy tables are on the **intersection of charts where all 3 providers produced an ok prediction: N = 200** (identical across rows). Cell = data point within tolerance; label-free pies scored on proportions. Reliability (schema-valid / invalid / rate-limit-excluded) is on each provider's full set.

## Cell accuracy @ 5% tolerance (headline, N=200)

| Model | Cell (all) | Labeled | Label-free | Gap (lab−free) | Exact-chart |
| --- | --- | --- | --- | --- | --- |
| gemini:gemini-3.1-pro-preview | 93.1% | 95.1% | 91.4% | +3.7 pts | 69.0% |
| anthropic:claude-fable-5 | 91.3% | 95.6% | 87.5% | +8.1 pts | 66.0% |
| openai:gpt-5.5 | 87.8% | 91.5% | 84.5% | +7.0 pts | 60.5% |

## Cell accuracy @ 2% tolerance (strict, N=200)

| Model | Cell (all) | Labeled | Label-free | Gap (lab−free) | Exact-chart |
| --- | --- | --- | --- | --- | --- |
| gemini:gemini-3.1-pro-preview | 88.8% | 94.2% | 84.1% | +10.1 pts | 63.0% |
| anthropic:claude-fable-5 | 85.6% | 94.1% | 78.1% | +16.0 pts | 56.5% |
| openai:gpt-5.5 | 81.9% | 89.3% | 75.4% | +13.9 pts | 48.5% |

## Reliability (full attempt set)

| Model | Schema-valid | model_invalid | infra-excluded | N (full attempts) |
| --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 100.0% | 0 | 0 | 300 |
| gemini:gemini-3.1-pro-preview | 84.8% | 39 | 44 | 300 |
| openai:gpt-5.5 | 100.0% | 0 | 1 | 300 |

## Label-free cell accuracy by chart type (5%, intersection)

| Model (label-free cell, 5%) | bar | grouped_bar | horizontal_bar | line | multi_line | pie | stacked_bar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 82.6% (n=29) | 86.9% (n=20) | 100.0% (n=1) | 89.6% (n=17) | 97.9% (n=12) | 83.3% (n=4) | 84.8% (n=24) |
| gemini:gemini-3.1-pro-preview | 86.0% (n=29) | 90.5% (n=20) | 100.0% (n=1) | 91.2% (n=17) | 98.3% (n=12) | 55.6% (n=4) | 92.2% (n=24) |
| openai:gpt-5.5 | 72.5% (n=29) | 83.5% (n=20) | 100.0% (n=1) | 89.6% (n=17) | 95.8% (n=12) | 94.4% (n=4) | 83.1% (n=24) |
