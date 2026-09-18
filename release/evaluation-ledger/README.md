# Local evaluation attempt accounting

Status: local implementation only. No GPU, training job or paid model API was
called. This does not close the evidence-packaging or cloud-evaluation gates.

## Defect and correction

Previously the runner appended a row only after a provider returned. A killed
process could leave a paid invocation absent from the evidence, call it again on
resume, and omit all not-yet-returned inputs from a provisional denominator.
The local model fingerprint also used file sizes/mtimes despite claiming content
identity, so changed weights with unchanged metadata could pass the resume guard.

The new `scheduled-evaluation-v1` contract records the entire selected schedule
in `run.sqlite3` before any provider invocation. Each input has one state:

| State | Meaning | Resume behavior |
|---|---|---|
| pending | Dispatch was never committed | Eligible to run |
| dispatched | Dispatch committed; completion not durable | Convert to interrupted; never retry |
| completed | Provider outcome saved, including failures | Preserve |
| input_error | Image missing/changed before invocation | Preserve; no provider call |
| interrupted | Outcome uncertain after a prior dispatch | Preserve as failure |

A committed dispatch can precede the actual provider call by a small interval.
Thus an interrupted entry is an **uncertain attempt**, not proof that a request
reached the provider or incurred cost. Conservatively skipping it prevents an
automatic second purchase; a fresh, explicitly separate experiment can retry it.
This is an at-most-one provider-function invocation policy, not exactly-once
remote inference and not an attestation of SDK-internal retry behavior.

SQLite commits use synchronous FULL; a host-local exclusive file lock fences a
second writer. The OS releases the lock after process death. One process cannot
run concurrent evaluations sharing the provider module's global decoder/cache
state. Never treat either mechanism as a distributed lock.

The schedule binds every ID, image path/content hash, ground-truth text and slice
metadata. Resume binds dataset bytes, model/revision, prompt, decoder, evaluator
source and seed policy. Local model files are content-hashed recursively; directory
symlinks are rejected rather than silently leaving linked subtrees untracked.
HF Hub revisions must be 40-character commit SHAs. Input hashes are captured at
startup and checked before a real provider call; this is not an attestation of
provider-internal vision preprocessing or protection against hostile mutation
inside the call. Keep benchmark input/model directories immutable.

## Scoring and artifact contract

`predictions.jsonl` is a portable snapshot, initially containing all scheduled
inputs and updated on exit, including orderly interruption. Per-call durability
comes from SQLite rather than repeatedly rewriting every raw response. SIGKILL
may leave that JSONL stale. Official `score`, `report` and `paired_bootstrap`
readers use the live ledger when present, even if given the JSONL filename. Both
live ledgers and new standalone snapshots validate their schedule count/hash.
Live model labels come from immutable ledger metadata, not a stale exported copy.

Missing/pending/uncertain outcomes remain in the primary denominator. Provisional
scores expose attempt-state counts. Comparison and promotion reject any pending
or dispatched records. Terminal failures stay in paired comparisons. Historical
standalone JSONL remains scoreable, with original attempt state explicitly
unrecorded; it is not eligible as a new durable resume log.

HF generation telemetry now survives the runner's call boundary: observed finish
reason, token counts and timing fields are recorded when the adapter supplies
them. Other provider completion evidence remains **unrecorded** until adapter
instrumentation is implemented. Perfect/noisy reference providers are explicitly
`not_applicable_reference`. These are test oracles, not model baselines.

Raw table quality remains `chart-table-v2`; it does not become an end-to-end
production acceptance score. A complete-looking table emitted at the token cap
can have a good raw quality score and still be rejected by the production API.
Keep both measurements when evaluating the current serving contract.

## Verification

Final full suite: **451 passed, one skipped**, four existing warnings, 131.23
seconds. The skipped test requires private train-table overlap data. Evaluation
formatting/lint checks passed. No real provider or GPU was used by these tests.
The dedicated acceptance tests include:

- Actual SIGKILL during the second provider invocation: the first result survives;
  the second stays uncertain; the third alone executes on resume. All three remain
  in scoring, and partial comparison cannot overwrite a prior report.
- Another OS process holding the run lock blocks all provider invocation.
- Missing real-provider images become terminal input errors without a model call.
- Image content drift and altered weights with identical size/mtime are detected.
- Duplicate IDs and invalid truth fail before inference.
- A copied snapshot or ledger with a removed scheduled input fails coverage checks.
- HF cap telemetry is retained; reference data never receives a claimed EOS.
- Noisy reference output for untouched inputs is identical after resume.

Reproduce from the exact locked development environment without network/model
credentials:

```sh
python -m pytest -q tests/test_eval_ledger.py tests/test_metric_contract.py tests/test_integrity.py tests/test_eval.py
```

Inspect a live or interrupted local run offline:

```sh
python -m unrender.eval.score --predictions outputs/MY-RUN/run.sqlite3
```

## Unfinished cloud requirements

[Modal's Volume documentation](https://modal.com/docs/guide/volumes) distinguishes
container-local writes from committed Volume state and states that Volumes do not
provide distributed file locking. Current evaluation wrappers call `VOL.commit()`
after `run()` returns. A local SIGKILL test cannot prove preservation across loss
of a Modal container or concurrent containers sharing an output directory.

Before new cloud quality runs: add durable checkpoints around dispatch/outcome,
ensure one externally coordinated owner per run, test container loss against the
actual storage service, disable or account for SDK retries, capture remote finish
reasons and real product validation, then enforce compute budgets. Distributing
licensed raw model artifacts and independent real-chart holdouts also remains
open in the [full readiness plan](../../docs/REVIEW_READINESS_PLAN.md).
