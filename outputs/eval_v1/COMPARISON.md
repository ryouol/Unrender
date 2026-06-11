# Unrender eval-v1 (hard) — final (openai truncated at n=218: quota)

Headline cell-accuracy tables are on the **intersection of charts where all 3 providers produced an ok prediction: N = 155** (identical across rows). Cell = data point within tolerance; label-free pies scored on proportions. Reliability (schema-valid / invalid / rate-limit-excluded) is on each provider's full set.

## Cell accuracy @ 5% tolerance (headline, N=155)

| Model | Cell (all) | Labeled | Label-free | Gap (lab−free) | Exact-chart |
| --- | --- | --- | --- | --- | --- |
| gemini:gemini-3.1-pro-preview | 61.2% | 68.3% | 57.5% | +10.8 pts | 25.8% |
| anthropic:claude-fable-5 | 45.3% | 50.5% | 42.6% | +7.9 pts | 11.0% |
| openai:gpt-5.5 | 38.4% | 44.0% | 35.4% | +8.5 pts | 11.0% |

## Cell accuracy @ 2% tolerance (strict, N=155)

| Model | Cell (all) | Labeled | Label-free | Gap (lab−free) | Exact-chart |
| --- | --- | --- | --- | --- | --- |
| gemini:gemini-3.1-pro-preview | 54.2% | 65.1% | 48.5% | +16.6 pts | 18.7% |
| anthropic:claude-fable-5 | 39.7% | 48.6% | 35.0% | +13.6 pts | 9.7% |
| openai:gpt-5.5 | 33.8% | 42.1% | 29.5% | +12.5 pts | 11.0% |

## Reliability (full attempt set)

| Model | Schema-valid | model_invalid | infra-excluded | N (full attempts) |
| --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 99.0% | 3 | 0 | 300 |
| gemini:gemini-3.1-pro-preview | 84.5% | 41 | 8 | 272 |
| openai:gpt-5.5 | 100.0% | 0 | 35 | 253 |

## Label-free cell accuracy by chart type (5%, intersection)

| Model (label-free cell, 5%) | bar | grouped_bar | horizontal_bar | line | multi_line | pie | stacked_bar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 39.3% (n=21) | 46.0% (n=14) | 93.8% (n=3) | 37.6% (n=26) | 46.9% (n=19) | 34.8% (n=11) | 34.1% (n=8) |
| gemini:gemini-3.1-pro-preview | 47.4% (n=21) | 70.5% (n=14) | 33.3% (n=3) | 48.2% (n=26) | 75.1% (n=19) | 71.2% (n=11) | 45.7% (n=8) |
| openai:gpt-5.5 | 30.3% (n=21) | 34.8% (n=14) | 69.1% (n=3) | 35.4% (n=26) | 41.1% (n=19) | 45.5% (n=11) | 22.1% (n=8) |
