# Versioned model evaluation

Scorer `chart-table-v2`; semantic cell F1 at 5% tolerance.
All recorded failures remain in the denominator. Historical scores are not comparable.
Common300 is a reused synthetic regression set, not a fresh real-world holdout.
Exact-chart percentages exclude unlabeled pies; denominators are in the JSON report.

## Common300

| Model | N | Precision | Recall | F1 | Raw semantic validity | Exact charts |
|---|---:|---:|---:|---:|---:|---:|
| base 4B (pinned) | 300 | 6.74% | 6.44% | 6.59% | 71.67% | 0.00% |
| table-LoRA (fair) | 300 | 29.51% | 28.31% | 28.90% | 95.33% | 4.64% |
| table-LoRA + numeric-loss | 300 | 27.58% | 25.82% | 26.67% | 93.67% | 3.93% |

Fair minus base: **+22.31 points**; paired 95% interval [+18.98, +25.71].

Numeric loss minus fair: **-2.23 points**; paired 95% interval [-3.97, -0.61].

## Frontier coverage

| Model | Recorded / expected | Comparison |
|---|---:|---|
| claude-fable-5 | 88 / 300 | INCOMPLETE — no paired quality claim |
| gpt-5.5 | 77 / 300 | INCOMPLETE — no paired quality claim |
| gemini-3.1-pro | 81 / 300 | INCOMPLETE — no paired quality claim |

Real_v0 semantic quality claims are WITHHELD pending a visual metadata audit.
Its fetcher synthesizes titles, axis labels and series names; source CSV values alone
do not verify those fields against the image. Strict diagnostic scores remain in JSON.
The set contains only eight public line charts and evaluates the earlier LoRA.
It cannot establish generalization or frontier parity. Contamination is a hypothesis,
not a demonstrated cause. Raw/repaired validity, all outcomes, family slices,
conditional metrics, bootstrap settings and artifact hashes are in the full local scoreboard.json.
