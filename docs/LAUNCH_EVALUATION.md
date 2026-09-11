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
