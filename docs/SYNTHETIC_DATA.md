# Current synthetic data contract

New data uses `chart-visible-v1`. Historical synthetic_v0/v1/v2 and Common300
remain frozen diagnostic evidence. Current code deliberately produces different
targets and does not promise historical regeneration from the same seed.

The contract fixes three confirmed source defects: single-series charts without
a legend have a null series name; units remain printed when the axis name is
absent; and stacked bounds contain cumulative values, starting at zero. Invalid
dimensions, invisible series names, nonfinite values, negative stacked segments
and clipping bounds are rejected. Negative bars and lines remain supported.

This is **not a complete visual-recoverability certificate**. Legends can obscure
marks, labels can collide, rasterization can hide small differences, and blur,
rotation or model resizing can remove evidence. Every generated row explicitly
says `visual_review: not_reviewed`. Unlabeled pies still provide proportions,
not an identifiable absolute total. Review and freeze eligible workloads before
using new data to claim quality or deciding to train.

## Create and verify a new bundle

With the locked CPU environment, from the repository root:

```sh
python -m unrender.data_gen.generate --n 100 --out data/synthetic_visible_dev_a --seed 47000 --v2 --workers 2
python -m unrender.data_gen.split_dataset --out data/synthetic_visible_dev_a --val-size 10 --test-size 20
python -c 'from unrender.eval.dataset import load_eval_samples; print(len(load_eval_samples("data/synthetic_visible_dev_a/test.jsonl")))'
```

Use a fresh directory for every generation. `--hard` and `--v2` select separate
sampling profiles and cannot be combined. `--start-index` selects the first ID
of a new dataset; it does not append. Worker count changes execution only, not
the recorded recipe or ordered manifest.

Generation records the seed/profile/augmentation parameters, complete per-chart
specification, source hashes, Python/library/FreeType versions, selected font
hashes, original/final dimensions and image/target hashes. Rendering uses the
versioned library defaults plus per-spec styles, isolated from ambient caller
styles. `generation.json`
starts incomplete and records the final manifest hash only after success. A
failed run must use another directory; it is not silently resumed or appended.

Splitting verifies the complete generated bundle before writing, assigns stable
ID-sorted seeded membership, and preserves provenance in every row. `split.json`
records the generation identity, splitter hash, prompt hash, seed, output hashes
and counts. Existing or partial splits cannot be overwritten. No `READY.json`
sentinel is removed from historical directories.

Both evaluation and training revalidate current synthetic image/target bytes,
split hashes, prompt/target binding, manifest coverage, and disjoint membership
before consumption. Altered or missing receipts fail even when requesting only
a prefix of the evaluation split. Hashes establish consistency with the saved
bundle; they are not independent attestations that a render or annotation is
correct. Independent source/table-overlap checks across different bundles remain
required before training/evaluation comparisons.

## Paths and movement

Relative image paths belong to the JSONL file's directory. Absolute paths remain
absolute. There is no working-directory search or guessed root fallback. Copy the
**whole bundle**—images, labels, manifest, generation receipt, all three splits,
and split receipt—to relocate current synthetic data. A JSONL file by itself is
insufficient. Training `--data-root` anchors relative split-file arguments.

Real-chart builders also emit split-relative local images. Externally sourced
charts retain their independent annotation-review requirements. Historical raw
prediction rescoring does not load new inference inputs and remains supported
by its frozen evidence bundle.

## Cloud boundary

The Modal generation commands accept only new names beginning
`synthetic_visible_`. Defaults create `synthetic_visible_v1_easy`,
`synthetic_visible_v1_hard`, or `synthetic_visible_v1_varied`; a second invocation
must choose fresh names. Cloud preflight uses the same reader and path convention.

These functions are CPU jobs but incur cloud costs. No cloud generation was run
for this change. Completion receipts become remote evidence after `VOL.commit`;
local file synchronization is not a claim of distributed ownership or durable
intermediate cloud checkpoints. Research training recipes and provider release
pins still require their separate validation before any GPU run or deployment.

The historical geometry conversion path remains unsuitable for a new experiment:
it regenerates specs from seeds and can skip mismatches. Its redesign and
augmentation-coordinate validation are separate work; do not use it to convert
these bundles or regenerate historical targets.

## Checks

```sh
python -m pytest -q tests/test_generation_contract.py tests/test_v2_gen.py tests/test_integrity.py
```

[Native-image verification and remaining layout failures](../release/synthetic-contract-v1/README.md)
record the development smoke run and its limits.

These checks cover counterfactual unit/stack visibility, negative ranges,
single-series identities, 3,000 sampled specifications, serial/parallel byte
identity, relocation, input tampering, interrupted generation, immutable splits
and downstream training/evaluation readers. They replace the old assertion that
current sampling must preserve a known-defective historical RNG sequence.
Historical artifacts retain their own exact-hash reproduction tests.
