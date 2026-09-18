# real_v0 — rejected historical evaluation labels

The eight saved OWID charts are **not a valid model-comparison benchmark**.
The [image-level audit](../../release/real-v0-audit/README.md) confirms mismatched
series names and titles, plus axis labels invented by the fetcher, in all eight
annotations. The original JSONL is retained unchanged so historical mistakes can
be reproduced. Do not run new paid inference or training against these targets.

All eight charts are United States annual line charts, 2000–2023. They cannot
establish generalization across chart families or a frontier-model advantage.
The original source CSV snapshots and historical inference image hashes were not
retained. Fixing visible labels after inspecting historical outputs does not turn
this set into an untouched final holdout.

## New real-chart datasets

Use a **new dataset directory and version**. The local fetcher now produces draft
labels marked `needs_visual_review` and saves the downloaded source CSV bytes:

```sh
python -m unrender.eval.fetch_real_set --dir data/real_dev_v1
```

This is source collection, not benchmark validation. Review every actual image:

1. Transcribe the visible title, series names and axis labels; use null for absent
   labels. Do not substitute a source-series identifier or an invented title.
2. Match the image's entities, dates, aggregation, series and values to the saved
   source data. A parallel CSV URL alone does not prove the chart uses that table.
3. Check scales, units, multipliers, percent conventions, logarithms and precision.
   Define numeric units and any permissible aliases before model comparison.
4. Check recoverability at the model's actual input resolution. Preserve reference
   source values, but do not demand precision invisible in the raster. Include
   axis-span error and simple constant/trend baselines when relative error can
   hide a missing trend. Mark ambiguous or unsupported charts separately.
5. Record the reviewer, timezone-aware review time and the hashes below. A final
   research holdout requires a second independent review, source/table-disjoint
   groups, and no tuning on its outcomes; the receipt alone cannot prove those.

Each label needs `source_data_file` (relative to the dataset directory), a source
citation, a boolean `labels_shown`, and a `ground_truth_review` object:

```json
{
  "contract": "real-ground-truth-review-v1",
  "status": "verified",
  "reviewer": "identified reviewer",
  "reviewed_at": "2026-09-18T12:00:00Z",
  "image_sha256": "<SHA-256 of reviewed image bytes>",
  "annotation_sha256": "<hash of target, visibility and citation>",
  "source_data_sha256": "<SHA-256 of saved source data bytes>",
  "visible_metadata_checked": true,
  "source_values_checked": true,
  "scale_units_checked": true,
  "recoverability_checked": true
}
```

The annotation hash is computed by
`unrender.eval.dataset.annotation_sha256(canonical_json(chart), label)` after
`label_to_chartdata(label, filename)`. It binds the complete chart target,
`labels_shown` and source citation. Image/source hashes use ordinary SHA-256 of
file bytes. Fill the checks only after doing the review; software can validate a
receipt and detect drift, but cannot prove the review was competent.

Then build the reviewed dataset:

```sh
python -m unrender.eval.build_real_set --dir data/real_dev_v1 --out data/real_eval_v1
```

The builder rejects missing/incomplete review, changed images/annotations/source
bytes before writing output. The evaluation loader rechecks the receipt and image
when present, so old unreviewed rows cannot start a new evaluation. Missing images
remain input errors in the scheduled-attempt ledger and never reach a provider.
A missing image does not invalidate offline inspection of a review receipt.
Local and Modal collection use the same draft collector. A new directory is
required for every attempt. `collection.json` retains every scheduled source,
including failed and interrupted downloads; partial collections cannot silently
publish only their successful rows. Collection never writes an evaluation split.

Publication copies reviewed source artifacts into a staged snapshot and atomically
publishes one portable `test.jsonl`. Existing versions cannot be replaced. The
loader verifies the published inventory, including the source CSV bytes. Upload
the whole `data/real_eval_v1` bundle to Modal; separate absolute-path splits are
no longer needed. A changed draft does not change its published snapshot.

Saved historical outputs can still be rescored for diagnostics. Scores expose
`ground_truth_review.review_gate_passed`; unreviewed external charts block paired
bootstrap and comparison reports. This does not authenticate claims for rows that
omit source provenance, or turn synthetic data into a real-world holdout.
