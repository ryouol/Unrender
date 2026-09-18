# Training recipe, loss and recovery

The canonical candidate runtime is `requirements-train.lock`, generated for
Python 3.11 / Linux x86-64. Modal installs it with required wheel hashes. A local
CUDA installation uses that same lock, followed by `pip install --no-deps -e .`.
The mutable `[train]` extra, Unsloth/TRL layer and metadata-version rewriting have been removed. Training uses the standard Transformers/PEFT APIs.
A successfully resolved lock is not proof that Qwen CUDA training works;
run the actual GPU integration canary before a longer experiment.

Every training call requires `base_revision`, a full Hub commit. The loader uses
that exact local snapshot, inventories its bytes before and after model loading,
and records the actual saved processor files. `training-recipe.json` is persisted
before training and checkpoint selection. It binds source-review receipts,
oversampled training/validation records, model/processor bytes, Trainer settings,
loss/collator policy, source files and installed environment. Recipe drift needs
a new output directory; existing unidentified runs cannot acquire a new identity.

## Loss and collator

Both weight-one and numeric-weighted runs use sum(weight * causal CE) divided by
sum(weight) over the entire accumulated optimizer batch. Shifted ignored labels
and padding contribute neither loss nor denominator. The last short optimizer
batch uses its actual denominator. Multiple processes and DeepSpeed are rejected
until independently implemented and tested.

The collator uses the actual Qwen processor without implicit resizing.
It disables truncation, checks the complete input against the declared sequence
limit, masks the prompt and padding, verifies the decoded assistant target, and
checks image tokens against the emitted grid. The training default uses the
full processor input; the 512-token option is separately CPU-tested and is not
an inference-quality parity claim. The sequence limit includes image tokens.

## Recovery

Each completed checkpoint includes a byte inventory and run identity. It must
contain model/adapter, optimizer, scheduler, RNG, Trainer state and arguments,
plus the fp16 scaler when applicable. Completion is sealed before checkpoint
retention can delete earlier saves. Missing, changed or partial artifacts stop
automatic resume; the code never silently rolls back to an older checkpoint.

The local writer lock spans the run. Modal additionally claims the output name
atomically in `unrender-training-owners`, recording the function-call ID. Recipe
and sealed checkpoints are committed to the Volume; a successful run releases
its claim only after persistence. A failure retains ownership. For explicit
recovery, first inspect the recorded Modal call and prove it is terminal, inspect
the saved recipe/checkpoint receipts, then release that specific claim. Never
remove an apparently stale claim based on elapsed time alone.

## Verification and remaining work

CPU tests exercise actual Transformers 5.17.0 optimizer gradients, unequal label
counts, short accumulation tails, weight-one CE, and real pinned Qwen processor
batches with both padding directions and full/512 budgets. A separate tiny random
GPT-2 fault experiment kills complete and partial checkpoint writes in separate
processes. Verified complete resume matches model, optimizer, scheduler, RNG,
loss history and step; changed learning rate and incomplete newer saves fail.

These checks do not establish Qwen CUDA parity, actual Modal container-
loss recovery, generated-task checkpoint selection, or model usefulness. Source
reviews remain mandatory. Never reuse the development review packet as the final
holdout, and do not launch a broad training sweep from a passing CPU test.


## Runtime advisory remediation

The initial compatibility candidate had 14 advisory records across torch,
Transformers, Accelerate and datasets. Upgrading Unsloth alone could not resolve
the conflict: its published constraints excluded several fixed versions. The
canonical training path now uses **Transformers 5.17.0, torch 2.14.0, Accelerate
1.15.0, datasets 5.0.1 and PEFT 0.21.0**, with hashes in the Linux lock. Production
inference's proposed direct pins use the same model-loading versions; that change
requires a new provider release and a coordinated canary before rollout.

The [current dependency audit](../release/readiness-remediation-20260918/training-dependency-audit.json)
reports no known advisories for the resolved training lock. The earlier findings
are preserved in the adjacent `training-dependency-audit-before.json`. A package
scan is not proof that arbitrary checkpoints or model code are safe. The loaders
require built-in architectures and safetensors, with remote code disabled;
training source and checkpoint identity gates still apply.

The LoRA recipe records actual adapted modules and uses standard gradient
checkpointing. Export reloads the **exact original higher-precision base** before
merging the saved adapter with `safe_merge=True`; it does not merge into a
4-bit approximation. An actual tiny-model PEFT test covers adapter checkpoint
sealing/retention and merged-output equivalence. Qwen CUDA memory/step time and
quality remain unmeasured.

Transformers 5.17 calls retention through a module function. The checkpoint mixin
disables deletion during the upstream save, restores the configured arguments,
seals/commits the complete checkpoint, then applies retention. A real process-kill
experiment verifies this order and exact resumed optimizer/model/RNG state on
the new runtime. The processor uses the new SizeDict interface; the actual
full/512 tests and the refreshed 72-chart v2 review packet use that interface.
Source review rejects packets from the previous processor runtime. Native image
and target bytes are unchanged; independent decisions remain pending.

Upstream references: [Unsloth constraints](https://pypi.org/pypi/unsloth/2026.9.6/json),
[Zoo constraints](https://pypi.org/pypi/unsloth_zoo/2026.9.5/json), and
[Modal Volume persistence semantics](https://modal.com/docs/guide/volumes).
