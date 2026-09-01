# Changelog

## 0.2.0 — 2026-09-01

- Added the review-first product workspace: account sessions, safe upload/page/crop selection, durable extraction jobs, source/result review, corrections, approval, audit history, and CSV/JSON/XLSX exports.
- Added a deterministic, zero-provider-cost sample tied to the saved `synthetic-v1-0002906` result and kept all model claims evidence-linked.
- Added tenant-scoped browser and token APIs, hashed/revocable API keys, credit reservation/refund accounting, test-only Stripe checkout/webhooks, retention cleanup, and interrupted-job recovery.
- Added strict request/origin/host controls, CSRF, security headers, safe file decoding limits, parameterized SQLite transactions, spreadsheet-formula neutralization, checkout allowlisting, and dependency/secret/security review evidence.
- Added a non-root container, hashed runtime dependency lock, pull-request CI, operations/security/legal/launch documentation, and desktop/mobile browser QA evidence.
- Preserved the research data-generation, evaluation, and training workflows; the product API calls them only through an explicit inference-provider boundary.

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

## 2026-07-01 — P0 measurement change (repairs + x-ruler) and synthetic_v2 generator

### Scoring/repair changes (affect EVERY model identically; free re-score of saved raw)

1. **Numeric-value coercion** (`validate.py`): point y-values like `"1,200"`,
   `"1.2B"`, `"12%"`, `"$3,400"` now coerce to numbers; a point whose y is
   unusable (null / prose / malformed dict) is DROPPED instead of invalidating
   the whole chart. The scorer already counts a dropped point as a miss, so
   this converts whole-chart zeros into partial credit — model-neutral.
2. **JSON repair extensions** (`validate.py`): truncated output (max-token
   cutoff) is brace-balanced; Python literals (`None/True/False`), fully
   single-quoted objects, and `{"chart": {...}}` wrappers are normalized.
3. **x-ruler normalization** (`metrics._norm`, symmetric on GT and prediction):
   thousands-commas collapse (`"1,200"=="1200"`) and month names abbreviate
   (`"January"=="Jan"`). A numerically-correct cell no longer dies on spelling.

Re-scored impact on common300 (cell@5_exact @5%): table-fair 38.18→38.86
(invalid 11→0), numloss 36.52→37.69 (16→1), base-4B 12.99→13.52 (66→26).
Frontier lanes re-scored with the same code: fable-5/gpt-5.5/gemini paired
numbers unchanged (44.2/38.0/64.9) — their ok-rows had nothing to recover, so
the repairs favor no one. All previously-published numbers remain quotable as
"pre-P0"; new comparisons must use the new scorer.

### synthetic_v2 generator (new `--v2` mode; v0/v1 recipes byte-frozen, regression-tested)

Closes the real-transfer gaps the 2026-07-01 sweep measured (model scored 0%
on 1e8–1e9 real charts it had never seen the like of):
- value magnitudes extended to 1e9 (was <1e6); big-magnitude charts integer-valued
- real-world value-axis formats: K/M/B tick suffixes with FRACTIONAL thresholds
  (B fires at vmax≥2.5e8 — the old `>=1e9` gate was unreachable since values are
  `rng.random()*scale < scale`; v1's "M" gate had the same dead-branch bug),
  comma-grouped ticks, forced-plain full digits, or mpl offset notation
- continuous numeric year x-axes with sparse auto ticks on line charts (the
  OWID/FRED look; was always one printed label per category)
- themes: owid / dark / news (spines, grid color, title placement; artists and
  GT untouched); `minor_ticks` knob finally wired
- density mixes easy+hard; ~55% label-free; heavier augmentation (0.95)

New: `EXTRACTION_PROMPT_V2` (plain-number + exact-label rules) exists but is
NOT default — numbers are only comparable within one prompt version, so it
ships with the v2 retrain when all arms re-run on it together.

## 2026-07-07 — v2 visual-audit fixes (dataset regenerated) + one-shot levers

Eyes-on audit of rendered v2 charts found two supervision bugs; v2 was
REGENERATED (same seed 9012 recipe, amended code) and re-uploaded:
1. **Dark theme x dark palettes**: #22223b-family marks on the #1c1e26 dark
   background are near-invisible (worse after augmentation) — training the
   model to "read" marks it cannot see. Dark-theme charts now draw from
   `_DARK_THEME_PALETTES` (bright sets + light ends of the mono ramps);
   regression test enforces palette luminance >= 0.15 on dark.
2. **Huge-magnitude labels x density**: 8-10-digit printed value labels on
   15-40-point charts collide into unreadable ink. Specs with vmax >= 1e7 AND
   (>12 categories or >24 total points) now flip to label-free; sparse
   big-number charts keep printed labels (that skill still gets taught).

New levers (default OFF, no behavior change unless used):
- `--type-weights "multi_line:1.5,stacked_bar:1.5"` — generic per-chart-type
  oversampling (the biggest per-type gaps vs Gemini).
- `unrender/eval/ensemble.py` — self-consistency merge of k sampled eval runs
  (per-cell majority + median vote; merged raw is canonical JSON so the
  standard scorer consumes it unchanged; never sees GT).
- Training runs now write `meta.json` provenance (full recipe) next to weights.
- Train->eval chaining (`--eval-after`), crash resume from latest checkpoint,
  and a parallelized data preflight (`modal_train.py::check`).

## 2026-07-15 — ship: docs refresh, LICENSE, reproducible scoreboard

- `analysis/scoreboard.py` recomputes the headline numbers from saved predictions
  with the current scorer and writes `RESULTS.md` (+ `outputs/scoreboard.json`) —
  every stat in the README/RESULTS.md is a regenerable receipt, not prose.
  Headline (common300, `cell@5_exact`): base 13.5% → table-LoRA 38.9% (+25.5pp,
  95% CI [+22.7,+28.6], PASS); parity with GPT-5.5 (+1.2pp), behind Claude/Gemini;
  real_v0 67% vs base 31% (Gemini 100% = contamination, flagged).
- README overhauled: Phase-3 marked done, a Results section, and a "Use the model"
  section (`modal run modal_train.py::infer --image chart.png` → JSON+CSV).
- `infer`/`infer_one`/`evaluate` now default to the best model
  (`runs/qwen3vl4b-table-fair/merged`) instead of the older `qwen3vl4b-lora`.
- `modal_train.py::publish` — optional Hugging Face Hub push of the merged model
  from the Volume (needs an `hf-token` secret); not run by default.
- Added the `LICENSE` file (Apache-2.0, already declared in the README); removed
  the stray stock-Modal `get_started.py`.
