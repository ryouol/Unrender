# Changelog

## eval-v1 (scorer fixes + hard generator)

`eval-v0` (git tag `eval-v0`) stays **frozen as the historical record** — the
first baseline ran against it. `eval-v1` is a re-measurement after fixing four
measurement bugs in the scorer/harness, plus a harder generator. **Every scorer
change below is model-neutral or favors the baselines** (none favor our future
fine-tune) — stated per change so the comparison stays unimpeachable.

### Scorer / harness fixes (also applied retroactively to a re-scored eval-v0)

1. **Three-way status — errors are never predictions** (`classify_status`).
   Each row is `ok` / `model_invalid` / `infra_error`. Rate-limit / quota /
   network failures are `infra_error`, retried with exponential backoff at run
   time, and **excluded from N** when scoring. `model_invalid` (the model
   answered but the output was unusable) still counts as a miss.
   *Neutral → slightly favors whoever we rate-limited (Gemini): it stops
   counting our infrastructure failures as their misses.*

2. **Repair maps key synonyms, equally for all providers** (`_normalize_keys`).
   Before schema validation: `data`/`values` → `points`; `category`/`label`/
   `name` → `x`; `value`/`amount` → `y` (`name`→`x` only inside a point, so a
   series' own name is preserved). One repair pass, same leniency for everyone.
   *Favors the baselines — recovers valid-intent outputs (lifted OpenAI from
   92.6% → 100% schema-valid on eval-v0).*

3. **Label-free pies scored on proportions** (`score_sample`). When a pie's
   values aren't printed (`labels_shown=False`), absolute slice values are
   information-theoretically unrecoverable from geometry — only proportions are.
   GT and prediction are normalized to shares-of-total before the tolerance
   check. *Strongly favors the baselines — they were scored ~0% on an impossible
   task; now scored fairly on the proportions they actually read.*

4. **Re-scoring re-parses the saved raw** with the current repair, instead of
   trusting the stored parse — so scorer/repair improvements re-measure for free.
   *Neutral — same code path for every provider.*

### Reporting

5. **Two tolerance tracks**: 5% (headline) and 2% (strict), with
   `exact_chart_rate` surfaced prominently. The strict track exposes precision
   gaps the 5% tolerance masks (e.g. label-free precision).
6. **Headline computed on the ok-intersection**: cell-accuracy tables use only
   charts where *every* provider produced an `ok` prediction, so N is identical
   across rows (apples-to-apples). Reliability (schema-valid / model_invalid /
   infra-excluded) is reported separately on each provider's full attempt set.

### Generator escalation (eval-v1 hard set)

Toward realism, not absurdity: 15–60 points per chart; non-zero y-baselines;
unrounded axis maxima; gridlines off ~50%; minor ticks off; 4–6 series with
similar palettes; K/M/B tick suffixes; smaller figure sizes; heavier
augmentation on the hard split.

### Known issue surfaced (not yet fixed — would require a prompt change)

Gemini transposes x/y on **horizontal bars** (reads the visual x-axis = values
as `x`), clashing with the schema convention (`x`=category regardless of
orientation). Causes most of Gemini's horizontal_bar `model_invalid` + low cell
accuracy on eval-v0. A prompt clarification is deferred.
