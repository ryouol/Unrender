# Model error audit: repair the benchmark before attributing every error to the model

**109/300 Common300 charts have at least one confirmed generator visibility
defect under the reconstructed historical specifications.** The reproducible
28.90% fair-LoRA cell F1 is a score against those frozen targets, not a clean
measurement of recoverable chart data. This audit preserves every target and the
chart-table-v2 ruler. It does not promote a higher score by repairing or excluding
examples after seeing model outputs.

The training data has the same metadata problem: 1,210/3,500 recovered v0 training
rows and 1,155/3,500 v1 rows require an unprinted series name or unit. These
recovered files do not prove the exact historical optimization inputs. Those counts
do not include a training-image clipping or legibility audit.

## Three confirmed defects

| Defect | Common300 charts | Evidence |
|---|---:|---|
| Single-series name is randomized but no series legend is drawn | 78 | Changing the required name from `Budget` to null produces identical pixels |
| Unit is omitted whenever its axis label is absent | 24 | Changing the required unit from `USD` to `EUR` produces identical pixels |
| Unlabeled stacked values extend above an explicitly fixed plot limit | 14 | Changing a fully hidden value from 3 to 7 produces identical pixels |

The first two sets overlap in seven charts, giving 95 metadata-defective charts.
The 14 clipping cases add 281 clipped value endpoints and bring the union to 109.
There may be additional defects: this is not a complete occlusion, augmentation,
label-crowding or model-resolution recoverability audit.

The historical renderer only draws multi-series legends. The target generator
independently chooses a metric name or null for single-series charts. A metric
word may appear elsewhere, but the named-vs-null answer is not determined by the
pixels. `_axis_text` similarly returns an empty string when `label` is absent,
regardless of the unit. The stacked-chart upper limit is sampled from the largest
**individual** value instead of the largest cumulative stack.

The [proof record](observability-proofs.json) records exact-pixel equality for
three pairs of distinct targets, the renderer/generator source hashes and Git
revision. Each pair has one common PNG and both targets:

- [Series-name proof image](proofs/0004056.png) · [two targets](proofs/0004056.json)
- [Unit proof image](proofs/0003073.png) · [two targets](proofs/0003073.json)
- [Clipped-value proof image](proofs/0000950.png) · [two targets](proofs/0000950.json)

The renders are new, unaugmented counterfactuals using the historical source, not
claimed byte-identical reconstructions of the original inference inputs. All
300 reconstructed specifications exactly match their saved chart targets at the
recorded source revision and seed (5678 + numeric chart ID, hard mode). Their
complete specifications are retained in `reconstructed-specs.jsonl.gz` with
content hashes. The original run lacked image hashes and renderer environment
attestation, so historical inference-image byte identity remains unproven.
Two actual volume images, [0001155](recovered/0001155.png) and
[0003073](recovered/0003073.png), were also recovered and visually inspected; they show no series legend and no printed unit. They support the
source diagnosis but do not resolve historical byte identity.

## Where the frozen score loses credit

The fair arm's 8,431 exact-numeric target cells partition as follows. Unlabeled
pie proportions remain separate (20 charts); the primary denominator spans 280
charts. This assigns the **first blocking condition** in the displayed order,
so it is an accounting breakdown, not causal attribution or a forecast of gains.

| First blocking condition | Target cells |
|---|---:|
| Raw output cannot be parsed directly into the schema | 350 |
| Series identity does not match uniquely | 1,708 |
| Point/category identity does not match uniquely | 289 |
| Chart family differs | 35 |
| Units differ | 464 |
| Numeric value outside 5% tolerance | 3,198 |
| Correct under the frozen rule | 2,387 |
| **Total** | **8,431** |

There are no recorded infrastructure errors in these saved files; that does not
prove there were no earlier retries or discarded attempts. The fair arm emits
8,088 primary-track cells, including 2,004 without a unique target identity.
The 121 predicted unlabeled-pie cells are excluded from that primary denominator.

Metadata-defective charts account for 1,684 of the 1,708 series-identity misses
and 386 of the 464 unit misses. Training the model to guess those hidden fields
would teach the dataset artifact, not improve faithful extraction.

Even among the 191 charts without these three *known* visibility defects, 2,830
of 5,704 target values fall outside tolerance after matching identity, type and
units. Numeric recovery still needs investigation. This post-hoc subset is not a
new holdout, and unknown clipping/legibility/preprocessing defects may remain.
The conditional metrics in the JSON are diagnostic and cannot be used as a new
headline accuracy claim or to promote a model.

## Reproduce the accounting

With the repository's locked CPU dependencies installed:

```sh
python -m analysis.error_audit
```

The command verifies the committed raw evidence and reconstructed-spec hashes,
requires complete coverage, and checks that every per-chart partition agrees
with the existing scorer's correct-cell count and denominator. It writes
`outputs/model-error-audit.json`, including all 900 per-chart records, family
slices and predicted/truth identities and units. [Summary](summary.json) and
`per-chart-audit.json.gz` retain this run's output. The rules describing hidden
fields and clipping are explicitly scoped to the historical renderer; they are
not an eligibility certificate for newly generated images.

## Corrective sequence and acceptance checks

1. Create one new canonical generator/target contract. An absent single-series
   label must produce null; required units must be visibly printed even without
   an axis name; stacked limits must contain cumulative endpoints. Reject
   incoherent specifications instead of silently hiding required data.
2. Version the new dataset, record the complete specification, seed, source and
   rendering environment, and bind image/target bytes. Refuse mixing old and new
   generation contracts or overwriting frozen evidence. Keep historical outputs
   available only as explicitly qualified regressions.
3. Test visibility invariants with counterfactual pairs: distinct supported
   required answers must not arise solely from invisible fields. Test cumulative
   stack bounds and both positive/negative ranges. Inspect rendered images and
   detect label overlap/clipping at native and deployed 512-token vision input.
4. Build the separate real/multirenderer development and final datasets, with
   independent annotation/recoverability review and source/table-disjoint groups.
   Include axis-span errors and simple constant/trend baselines alongside semantic
   precision/recall. Freeze eligibility and tolerances before final evaluation.
5. Evaluate pinned base, current fair LoRA and selected controls at full and
   deployed image budgets before deciding whether to train. Use the resulting
   error slices to choose a targeted intervention; then compare identical
   reviewed inputs with complete attempt ledgers and paired confidence intervals.

The new generator and datasets are **not implemented by this audit**. No new
inference, training, preprocessing-quality or serving-performance result is
claimed. All images here are generated by this project from synthetic data.

## Verification

**486 tests passed, zero skipped**; the 10 focused audit tests and lint/format
checks passed. A clean Git source archive reproduced the full per-chart report
byte-for-byte. The three counterfactual pairs were rendered and compared at the
pixel level; all five retained PNGs were inspected. See the
[verification record](verification.json). No inference, training or deployment
was performed.
