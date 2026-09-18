# September 18 audit remediation

Implementation merged through PR #11 and deployed on September 18 as `2bc72d1`, schema 15. The separate serving checkout and its existing user changes are preserved. See [deployment evidence](RENDER_MODAL_LAUNCH.md); deployment success does not establish model promotion.

## Findings, implementation and acceptance

| Findings | Current implementation | Remaining acceptance evidence |
|---|---|---|
| F03, F04: incomplete output and approval drift | Complete-table parsing, observed completion and exact-version review/export | Passed on September 18: real provider/browser/schema-15 workflow; broader user pilot remains |
| F05: invalid comparison and promotion | Shared source/truth/review identity, source-group bootstrap, all generic comparisons explicitly descriptive; historical/tiny studies cannot promote | Independent frozen study and prespecified power analysis; promotion automation remains withheld |
| F06: destructive collection and publication | One local/cloud draft collector; exclusive attempt directories, full failure schedule, reviewed immutable portable publication with byte inventory | Cloud interruption/concurrent publication drill |
| F07: wrong accumulated numeric objective | One weighted-token objective normalized over the complete optimizer batch, including tail batches | Actual Qwen/CUDA integration and meaningful training comparison |
| F08: unsafe resume and mutable training recipe | Exact runtime locks, immutable model revision, actual processor/input/source identity, exclusive run ownership, sealed checkpoints before retention and Volume commit hooks | Modal container-loss/restart test with Qwen; generated-task checkpoint selection |
| F09: geometry targets drift from pixels | Removed seed-regeneration builder and Modal generation entrypoints; geometry training remains rejected | A future geometry arm requires image and geometry captured together, recorded spatial augmentation, pixel/coordinate tests; no such arm is approved now |
| F01, F02, F10: defective or unreviewed truth | Historical claims remain downgraded; 72 easy/hard/varied development charts packaged for independent review | User will arrange reviewer. Final holdout must be independently sourced and kept separate from this pilot |
| F11: implicit resize and truncation | Explicit Qwen collator, complete target/grid/padding checks, no truncation; actual pinned processor tested at full and 512 budgets | Same-input full/512 inference quality and readable-precision crossover |
| F12, F13: misleading serving evidence | Isolated serving harness uses strict JSON/schema/semantics AND completed stream; failures receive no throughput/quality credit; complete durable attempt schedule | Competent same-GPU baseline, three repeats, full workload/cost/trace evidence; runtime version must be explicitly selected and validated |
| F14: lost/duplicate cloud evaluation | Distributed output claim; schedule/dispatch/outcome persistence hooks; SDK retries disabled and observed API finish reason recorded; failure retains ownership | Real container-loss/Volume drill and transport request-count evidence; local mocks do not prove cloud behavior |
| F15: serial worker and slow monitoring | Bounded worker pool (1–4, default 1); concurrent claim/charge/shutdown tests; deployed two-minute monitor with bounded retries | Capacity/load measurement before increasing production slots; remote cancellation acknowledgement and durable global provider dollar cap are still open |
| F16: recovery/auth/container risk | Existing recovery, access controls and release checks retained | Timed production-like restore, external auth/security review and current container advisory disposition |
| F17: blurry demo | Sharp owned synthetic reference chart; readable values, explicit units, source order matches table | Local browser correction/versioned approval/download passed; independent 30-chart user workflow pilot remains |
| F18: unclear handoff | Current plan, training contract, CI contract tests and reviewer reading order | PR #11 merged, all hosted jobs passed, deployed revision manifest retained; independent engineer review remains |

## Execution order and stop conditions

1. Finish local regression checks and publish a reviewable code revision. Keep
   saved historical scores labeled as historical. Do not call CI green until
   hosted jobs, including the new Linux CPU training job, have run.
2. Have the independent reviewer return the **development** packet with readable
   precision and rejection reasons. Resolve disputed labels and regenerate
   defective images into a new dataset. Never retroactively approve old bytes.
3. Run one bounded Qwen CUDA integration canary on the [updated standard training runtime](TRAINING_REPRODUCIBILITY.md#runtime-advisory-remediation) on approved development
   data. Check model/processor identity, grid/labels, finite gradients, optimizer
   updates, checkpoint seal/commit and interrupted-versus-continuous resume.
   Stop at the first mismatch; do not start a training sweep.
4. Run a development inference pilot comparing pinned base/current LoRA, full
   versus 512 preprocessing, and a competent batching runtime on the same GPU.
   Record every request, observed completion, memory, timings and actual billed
   cost. Use this pilot to set a dollar/time cap, sample size and intervention.
5. Freeze the prospective study below, collect the independent holdout, then run
   the frozen arms once. Any tuning on its outcomes makes it development data
   and requires a new final holdout.
6. Deploy the coordinated application/provider release only after its canary,
   restore drill and rollout checks. Verify hosted revision, schema, provider
   identity, monitoring cadence and notifications. Local passing tests do not
   update the live beta.

## Prospective benchmark requirements

Freeze a signed/digested manifest **before final inference**: owner/reviewer,
source groups, image and target hashes, annotations and precision, eligibility
and exclusion rules, task/population, split disjointness, model/processor/code
identities, runtime/GPU, prompt, token limits, seeds, decoding, arms, primary
metric, quality margin, timing definitions, repeats and spend/time stop rules.
Never use Common300, real_v0 or the 72-chart development packet as the final test.

Use source/table groups as the unit of independence. Deduplicate source tables
and rendered variants across training, development and final splits. Collect at
least 300 independent charts as an initial planning floor; this is **not** a
power calculation. Estimate paired variance and clustering on development data,
then select final sample size for 90% power at a one-sided 5% error rate for the
chosen quality margin. Report confidence bounds and exclusions; do not move a
threshold after seeing final outcomes.

Initial usefulness requirements: at least 90% cell precision and recall, 70%
tables within the source-specific tolerance, and 99% observed semantic validity.
Report exact string/category errors, units, chart families, dense cases and
unreadable cases separately. Include all scheduled failures as misses; never
compute quality only over successful JSON. Confidence bounds must accompany the
point estimates. Independent human approval establishes annotation review, not
that the model meets these requirements.

A runtime candidate must have a paired quality lower bound of at least -1
percentage point, then show either 2x valid throughput or 30% lower p95 versus a
competent tuned baseline on identical hardware and workload. Use three separate
warm runs plus a separately labeled cold-start measurement; sweep concurrency
1/2/4/8 and mixed image/output lengths. Retain open-loop offered/admitted/completed
rates, queue/TTFT/inter-token/end-to-end times, timeouts, memory peak, GPU trace,
correct tables/second and billed dollars/correct table. Four configured worker
slots or a mocked fast stream is not evidence of four-user capacity.

For the human workflow pilot, independently review 30 representative charts.
Measure time to a correct approved table/export, corrections per chart and
failure recovery. Require no clipped labels, incorrect units, stale-version
approval/export, cross-account data, or charged duplicate dispatch. Retain both
successful and failed tasks. Final numerical time targets must be agreed from
this development pilot before the final comparison.

## Local evidence and boundaries

Regression tests cover comparison identity, partial collection/publication,
actual Transformers gradients, actual Qwen processor inputs, checkpoint byte
integrity, process-kill recovery, interrupted serving streams, cloud-hook order,
provider retry configuration and concurrent job accounting. CI now includes the
training/serving lint surface and a separately locked Linux CPU job.

The checkpoint experiment uses a tiny random GPT-2 on CPU. It demonstrates exact
model/optimizer/scheduler/RNG/loss/step equality after a verified complete resume
and rejection of recipe drift/partial checkpoints. It is not a Qwen/CUDA/Modal
result. Cloud tests use test doubles. No new model quality, speedup, GPU cost,
independent review, production cancellation or recovery claim follows from them.

Local validation counts and boundaries are recorded in [the dated validation receipt](../release/readiness-remediation-20260918/local-validation.json). The updated training lock has no known advisories in the recorded scan; the production inference CUDA/runtime rollout passed a one-chart canary. Qwen training and Modal recovery remain unverified.
