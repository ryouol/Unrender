# Unrender eval-v1 (hard, PARTIAL — billing-truncated runs)

Headline cell-accuracy tables are on the **intersection of charts where all 3 providers produced an ok prediction: N = 32** (identical across rows). Cell = data point within tolerance; label-free pies scored on proportions. Reliability (schema-valid / invalid / rate-limit-excluded) is on each provider's full set.

## Cell accuracy @ 5% tolerance (headline, N=32)

| Model | Cell (all) | Labeled | Label-free | Gap (lab−free) | Exact-chart |
| --- | --- | --- | --- | --- | --- |
| gemini:gemini-3.1-pro-preview | 72.9% | 91.1% | 60.8% | +30.3 pts | 37.5% |
| anthropic:claude-fable-5 | 60.1% | 74.3% | 50.7% | +23.6 pts | 18.8% |
| openai:gpt-5.5 | 50.4% | 70.3% | 37.2% | +33.2 pts | 9.4% |

## Cell accuracy @ 2% tolerance (strict, N=32)

| Model | Cell (all) | Labeled | Label-free | Gap (lab−free) | Exact-chart |
| --- | --- | --- | --- | --- | --- |
| gemini:gemini-3.1-pro-preview | 67.0% | 90.8% | 51.3% | +39.5 pts | 31.2% |
| anthropic:claude-fable-5 | 54.0% | 72.8% | 41.6% | +31.2 pts | 15.6% |
| openai:gpt-5.5 | 46.0% | 68.5% | 31.1% | +37.4 pts | 9.4% |

## Reliability (full attempt set)

| Model | Schema-valid | model_invalid | infra-excluded | N (full attempts) |
| --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 98.7% | 2 | 142 | 300 |
| gemini:gemini-3.1-pro-preview | 84.7% | 39 | 45 | 300 |
| openai:gpt-5.5 | 100.0% | 0 | 217 | 300 |

## Label-free cell accuracy by chart type (5%, intersection)

| Model (label-free cell, 5%) | bar | grouped_bar | horizontal_bar | line | multi_line | pie | stacked_bar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic:claude-fable-5 | 38.7% (n=3) | 44.6% (n=4) | 94.4% (n=1) | 43.3% (n=4) | 83.3% (n=2) | 56.0% (n=4) | 46.7% (n=1) |
| gemini:gemini-3.1-pro-preview | 81.3% (n=3) | 64.9% (n=4) | 0.0% (n=1) | 37.5% (n=4) | 88.3% (n=2) | 68.0% (n=4) | 48.9% (n=1) |
| openai:gpt-5.5 | 30.7% (n=3) | 35.7% (n=4) | 94.4% (n=1) | 27.9% (n=4) | 31.7% (n=2) | 56.0% (n=4) | 48.9% (n=1) |
