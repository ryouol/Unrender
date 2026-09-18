# Generated-source review boundary

Training previously verified generated file hashes but did not enforce the
documented source-review requirement. Cloud training also defaulted to the
historical datasets whose target defects are preserved in earlier audits.

New source packets retain every generated chart, exact target, actual full/capped
processor raster, protocol and decision. All decisions start pending. Actual
training rejects a requested train/validation split containing any noneligible
row, before oversampling or validation subsampling. It never filters those rows
away. Source images are checked again against their recorded hashes when a batch
reads them.

Normal Modal train/smoke entrypoints require explicit current visible_* dataset
tags, run the source gate on CPU before GPU dispatch and bind those receipts to
the worker. Changed or missing preflight evidence fails. Local training checks
before CUDA imports. Historical tags and the unverified geometry conversion are
not accepted for new training. Direct calls to a decorated GPU function can still
allocate a container before its body executes; use the normal entrypoint.

## Observed evidence

- The three existing 24-chart development bundles received pending packets.
  All 72 rows remain present; **zero approvals** were created.
- All six requested train/validation gate checks failed on pending rows: 16
  training and 4 validation rows per profile. No chart was silently excluded.
- Browser inspection confirmed source/full/capped images, original-size links,
  readable target tables and complete target JSON. The known blurred grouped
  chart remains in the packet with all 24 values.
- **573 tests passed, zero skipped**, with four existing warnings. The 31 source
  review tests passed after the final table-presentation and step-cap changes. Lint and
  product type checks passed. A clean Git source archive passed all recorded
  source, packet, protocol and processor-report binding checks.
- Tests cover missing/duplicate IDs, incomplete or malformed attestations,
  missing reviewer/time/notes, altered protocol/configuration/rasters, pending
  validation rows, image mutation at batch read, review changes between CPU and
  worker, historical/escaped dataset names, and no GPU dispatch after a failed
  source gate. Approval-shaped test fixtures are explicitly test doubles.

[Verification](verification.json) records source hashes and the observed pending
gate results. The three `*.packet.json` and `*.review.json` pairs preserve the
pending receipts; they are not complete runnable datasets by themselves. Their
processor audit is the exact report retained in
[`chart-layout-v1`](../chart-layout-v1/README.md). Full local packets are generated
under `outputs/source-review-dev/final/{easy,hard,varied}/review/index.html` and
are not committed as a second copy of the development data.

Follow [the documented workflow](../../docs/SYNTHETIC_DATA.md#review-sources-before-training)
to generate a fresh bundle, inspect its actual processor inputs and create a
packet. The protocol requires source/metadata/scale checks and recoverability at
the current cell tolerance, `max(5% * abs(target), 1e-6)`, at both image budgets.
It does not demand recovery of unprinted trailing digits. Unsuitable charts stay
pending, stress or unreadable, with their IDs and images retained.

## Limits and next work

Hashes establish consistency, not reviewer identity, independence or correctness.
An attestation can be false; this is an accountable record, not cryptographic
proof of a human review. The page is a static inspection packet; decisions are
recorded in review.json, and the page does not imply live approval status.

This source gate does not verify the actual training collator's transformations,
token lengths, base-model revision, runtime environment, optimizer/resume identity
or generated task-quality checkpoint selection. The former preflight used a
historical model's tokenizer and fixed old GPU cost estimates; those claims were
removed. The current CPU output explicitly states the remaining limits.

Reviewed external training integration and cross-bundle source/table overlap
checks remain open. Frozen historical predictions can still be rescored, and
diagnostic loaders can inspect pending data. A useful independently reviewed
benchmark and a justified training decision are still required. No paid compute,
remote training call, push or deployment occurred for this checkpoint.
