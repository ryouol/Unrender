# Results

> **Historical scorer-v1 results.** These numbers were reproduced at source
> `c84b741c5358239bbb5d7290d4d9b2b98ea4b038`. The scorer credited fuzzy date matches,
> ignored extra predicted cells in recall, and repaired malformed output. These
> are not current `chart-table-v2` scores or exact-table guarantees. See the
> [current evaluation contract](../../EVALUATION_CONTRACT.md). The current scoreboard
> writes to `outputs/evaluation-v2/` and does not regenerate this historical table.
>
> Historical metric: cells recovered within 5% tolerance, excluding unlabeled-pie
> proportion proxies. Common300 is a reused synthetic regression set. A table-hash
> overlap check passed for the inspected train splits; this does not establish
> freedom from all leakage or real-world generalization.

## Fine-tuning ladder — common300 (hard synthetic)

| System | cell@5_exact | schema-valid | invalid | labeled / label-free |
|---|---:|---:|---:|---|
| base 4B (pinned) | **13.5%** | 91.3% | 26/300 | 14.3 / 13.0 |
| table-LoRA (fair) | **38.9%** | 100.0% | 0/300 | 44.6 / 35.1 |
| table-LoRA + numeric-loss lever | **37.7%** | 99.7% | 1/300 | 41.8 / 34.9 |

## Does fine-tuning help? (preregistered paired bootstrap, pooled cell@5)

**table-LoRA − base = +25.53 pp**, 95% CI [+22.70, +28.56], P(LoRA>base)=1.000 — **PASS** (N=300, 10000 resamples). Invalid 0.0% vs 8.7%; median rel-err 15.5% vs 52.4%.

The numeric-token-loss lever did **not** transfer to the table target: lever − fair = -1.13 pp, 95% CI [-2.81, +0.40], P(lever>fair)=0.077 → dropped.

## vs frontier — paired on shared answered charts (common300, cell@5_exact)

| Frontier model | N shared | frontier | table-LoRA | gap |
|---|---:|---:|---:|---:|
| claude-fable-5 | 86 | 44.2% | 38.4% | **-5.8pp** |
| gpt-5.5 | 63 | 38.0% | 39.2% | **+1.2pp** |
| gemini-3.1-pro | 64 | 64.9% | 36.6% | **-28.3pp** |

## Real-world transfer — real_v0 (8 OWID line charts, all label-free, GT from official CSVs)

| System | cell@5_exact | schema-valid |
|---|---:|---:|
| table-LoRA | 67.2% | 100.0% |
| base 4B | 31.2% | 100.0% |
| gemini-3.1-pro | 100.0% | 100.0% |

**Caveats (read these):**
- The eight-chart real set is too small to establish generalization. Familiar
  source series make contamination a hypothesis, not a demonstrated explanation.
  Its generated metadata also needs image-level verification for strict table scoring.
- Frontier intersections above were selected from successful answers and have
  different coverage. They establish neither frontier parity nor a complete
  matched comparison. Version 2 retains failures and withholds incomplete comparisons.
- **synthetic_v2** (magnitudes to 1e9, real axis formats, themes) is built and staged but
  **not yet trained** — these numbers are the v0+v1 fair LoRA. real_v0 was measured on the
  earlier `qwen3vl4b-lora`; the fair model was not re-run on real charts.
