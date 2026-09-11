# Pilot evaluation

`release/launch-eval-v1/manifest.json` freezes three owned synthetic inputs and
their exact source data: labelled bars, an unlabelled line, and unlabelled grouped
bars. There are 15 numeric values. All PNGs are 1120 × 800, below the deployed
4 MP limit. Three independent review passes checked the images, source values,
dimensions and hashes. The generator reuses the research renderer; this set does
not establish generalization to customer reports or renderer-independent inputs.

Run `.venv/bin/python scripts/build_launch_eval.py` to verify reproducibility in
the pinned development environment. An existing version must match byte for byte;
changed rendering requires a new version. This command does not invoke inference.

The production evaluation uses one upload and one model attempt per input, no
automatic retries, and preserves each uncorrected result in review state. Record
all failures as well as successful predictions. Processing time is wall-clock
upload-to-terminal time observed by the client, including three-second polling
resolution; it is not a measured GPU runtime or cold/warm classification. Account
credits consumed are not a dollar-cost measurement.

Numerical scores use the existing `unrender.eval.metrics.score_sample` at 5%
relative tolerance. Report predicted and expected point counts alongside accuracy
because the scorer's ground-truth recall does not penalize every extra prediction.
MAE covers aligned points and must be read with missing-point counts. Single-series
names in this manifest are conceptual names without a printed legend, so their
name-F1 is not an appropriate success criterion. The operational checks use point
labels/values, title, axes, units, and the printed multi-series legend.

## September 10 production run

Runtime `e497a18` on Render used the pinned Modal model recorded in
`release/launch-eval-results/pilot-v1/meta.json`. All three attempts reached review
without retry. The stored, uncorrected provider receipts match the application
results and can be rescored offline. Three extraction credits were consumed;
actual dollar cost was not measured. A later read-only inspection of Modal's call
table established the container cold/warm classifications below.

| Fixture | Exact values recovered | Observed upload-to-result time |
|---|---:|---:|
| Labelled bar | 4 / 4 | 92.10 s |
| Unlabelled line | 5 / 5 | 67.72 s |
| Unlabelled grouped bar | 6 / 6 | 193.21 s |

All 15 values matched exactly, with no missing or extra points and zero numerical
MAE. The existing scorer agrees at both 5% and 2% tolerance. Printed titles, axes,
units and the grouped-bar legend also match. The grouped-bar case took over three
minutes, a material usability concern. This result covers only three crisp,
positive-value synthetic charts and must not become a customer accuracy claim.

`server-receipts.json` records the three jobs' timestamps and single-attempt state.
These corroborate server execution, but do not reconstruct the client-side upload
and polling intervals. The latency table is the run observer's measurement.
“Chart exact” in the research scorer means type and numeric cells; it does not
mean full JSON equality (the two single-series names were returned as null).

Re-score without inference (create the output directory first):

```sh
mkdir -p outputs/local-verification/launch-eval
.venv/bin/python -m unrender.eval.score \
  --predictions release/launch-eval-results/pilot-v1/predictions.jsonl \
  --out outputs/local-verification/launch-eval/offline-scores.json
```

The three jobs remain unapproved in the production account, identified by their
filenames. No human correction timing has been recorded.

## Provider latency investigation

On September 11 at 00:19 UTC, the Modal `unrender-production / infer_one` call
table was inspected without submitting new inference. Its EDT enqueue timestamps
match the three server dispatch timestamps to displayed-second precision. The
manually transcribed fields are saved in
`release/launch-eval-results/pilot-v1/modal-timings.json`.

| Fixture | Enqueued → started (approximately) | Modal startup | Modal execution | Container |
|---|---:|---:|---:|---|
| Labelled bar | 5 s | 3.755 s | 84.566 s | Cold |
| Unlabelled line | 0 s | 0 s | 64.375 s | Warm |
| Unlabelled grouped bar | 108 s | 3.468 s | 82.897 s | Cold |

The enqueue-to-start interval uses second-resolution UI timestamps. Do not add
the startup column to that interval: the fields have different boundaries, and
this table is not an additive breakdown of the client timer. Modal labels zero
startup as a warm container; that does not establish model-cache or file-cache
warmth. Execution includes work inside the function, not only GPU generation.

The function log also reported L4 scheduling pressure and suggested relaxing its
memory requirement, displayed literally as `memory=32.8GiB`. The configured SDK
value is 32768 MiB (32 GiB). This is function-level evidence, not a log correlated
to one fixture. Checkpoint-shard progress for the two cold containers covered
about 2.5–2.7 seconds; it excludes imports, integrity verification, processor
loading and generation. The production snapshot path re-verifies materialized
files on every call, but its duration has not yet been measured.

The next diagnostic is per-stage timing before changing resources or decoding:
measure snapshot verification, model/processor loading, preprocessing and
generation separately. A warm call still took 64 seconds, so reserving an always
warm GPU is not justified by these observations alone. No resource, model,
decoding, integrity-check or scaling setting changed during this inspection.

## Human correction-time protocol

Human correction time is not measured by the automated run. Do not substitute an
API edit loop, model-processing time, or an agent's tool latency for human effort.

1. Sign in to the production account and select the fixture by its filename.
2. Start a timer when the source and uncorrected table are visible. Inspect the
   chart itself, including labels, units and series, without first reading the
   ground-truth JSON.
3. Correct the table and approve it. Stop the correction timer at approval.
4. Export XLSX and open it; separately record time through verifying the workbook
   and audit sheet. Compare the final exported values with the frozen ground truth.
5. Record reviewer, fixture ID, first/repeated exposure, correction seconds,
   export-verification seconds, number of edits, and remaining numerical errors.
   Retain failures and cases the reviewer cannot complete.

This is a small rehearsal protocol. Selecting intended customer inputs, obtaining
permission to use them, and measuring first-use correction effort on those inputs
remain required before making a customer performance claim.
