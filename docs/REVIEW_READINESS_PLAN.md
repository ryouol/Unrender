# Engineering review readiness: implementation plan

Scope: turn the controlled beta into a reproducible, demonstrably useful chart
extraction and inference engineering project. A strong backend alone does not
prove model usefulness, serving quality, or a frontier research contribution.

The implementation starts from main `c84b741`, on `codex/review-readiness`, with
an isolated checkout. The existing `codex/production-ready-unrender` checkout and
its uncommitted case-study clarification are preserved. Do not deploy a partially
verified provider or merge the older branch's product implementation over main.

## Work sequence and completion evidence

- [x] Scoring contract implemented: versioned identities and table correctness,
  missing/extra-cell precision/recall, raw/semantic/recovery separation, retained
  recorded failures, fixed comparison coverage and paired intervals. Verified by
  349 passing tests (one private-data integrity test skipped), focused evaluation
  checks and lint. See [contract](EVALUATION_CONTRACT.md),
  [tests](../tests/test_metric_contract.py), and
  [initial rescore](../release/evaluation-v2/RESULTS.md).
- [ ] Evidence packaging: clean-clone reproduction with permitted raw artifacts,
  hashes, train-overlap verification and a complete scheduled/in-flight attempt
  ledger for future runs, including generation stop reasons and the actual product
  validation outcome. The private saved model artifacts remain external.
- [x] Approval integrity for new operations: required revision on correction,
  restoration, approval and export; atomic checks; conflict UI preserving drafts;
  exact snapshot responses/audit; concurrent-connection and real two-tab checks.
  See [contract](API.md#browser-review-concurrency-contract) and
  [verification receipt](../release/review-integrity/README.md).
- [ ] Approval rollout: fresh review of historical approvals before asserting the
  new guarantee; old audit receipts cannot prove the version a person actually saw.
  Deploy the browser and server contract together and verify a controlled canary.
- [x] Safe parsing and provider completion checks: only complete-table formatting
  repair; no invented truncated numbers, changed labels, dropped points or unit
  coercion. The provider reports observed EOS/cap/unknown and the API independently
  parses raw output; token-cap failures publish no partial table and do not retry.
  See [parser contract and saved-output audit](../release/parser-v2/README.md).
- [ ] Durable extraction diagnostics: persist successful raw/repaired status,
  parser version, finish reason and generation/provenance receipt per result
  version; carry through correction/restore, API, UI and every export. Existing
  failure codes already reach the job's API/UI. Do not claim this full item done.
- [ ] Provider rollout: coordinate v3 provider and API release pins, validate
  completion metadata with a bounded real GPU canary, then run broad quality gates.
- [ ] Export correctness: preserve units/scales; source hash/page/crop; approved
  version/content hash; model/provider/prompt/schema identities; verify actual
  CSV/JSON/XLSX output and retain formula-injection defenses.
- [ ] Unify the serving experiment with current main: selectively port code and
  raw evidence; retain failed/missing-input ledgers; identify all experiment versus
  deployment boundaries and update stale review/claim documentation.
- [ ] Dataset: development pool plus at least 300 independent final charts;
  source/table-disjoint groups, multiple renderers, representative real charts,
  all supported families, density/resolution/scale/date slices and unsupported
  cases. Double-check truth/recoverability. Audit the old real_v0 metadata against
  images. Common300 is only a historical regression set.
- [ ] Current-provider evaluation: compare full image input with deployed 512-token
  vision budget on identical charts; freeze processor/prompt/model/precision;
  evaluate quality separately from runtime changes.
- [ ] Inference comparison: current Transformers, competent default vLLM, tuned
  vLLM at fixed preprocessing; complete both quality arms; same-GPU attribution,
  repeated warm/cold measurements, scheduled-arrival load, short successful GPU
  trace, per-stage timings, input/output tokens, queue/KV/GPU measurements, and
  billed dollars per attempted/valid/correct chart.
- [ ] Product capacity and operations: bounded concurrent dispatch preserving
  lease/credit invariants; queue/overload behavior; remote cancellation evidence;
  restart/disconnect/provider-failure drills; stage/error taxonomy; useful alerts;
  isolated health probes; daily/global GPU spend stop and operator kill switch.
- [ ] Recovery/security: measured restore against 24h RPO/4h RTO; rescan the exact
  image digest and record package dispositions; real browser auth/Google critical
  paths; keep paid-launch/legal/support gates separate from private code review.
- [ ] Conditional training: first reproduce the baseline with immutable recipe,
  data, base/processor and environment hashes; validate resume identity; select
  by generated task quality. Train synthetic_v2/realistic mixtures or one diagnosed
  error intervention only after evaluation identifies the need. Multiple seeds
  for a finalist; no automatic 8B/RL or repetition of unsuccessful geometry work.
- [ ] Demo and handoff: sharp owned source, source-aligned review order, clear
  units/warnings/version, correction and exact approval/export, one failure demo;
  five-minute walkthrough and ten-minute local reproduction without secrets;
  release manifest, architecture/failure states, measured limitations and rollback.

## Proposed gates to freeze before final runs

These are requirements to validate, not current achievements or industry standards.

- All scheduled IDs accounted for in every arm; invalid ground truth is an error.
- Zero stale overwrites, unseen-version approvals, invented numeric repairs,
  duplicate dispatch/charges or export unit loss in regression/failure tests.
- At least 99% raw semantic validity on the declared supported workload.
- Runtime/preprocessing quality: paired 95% lower bound at least −1 percentage
  point versus the frozen baseline; insufficient power is inconclusive.
- Initial usefulness target: at least 90% cell precision and recall within 5%
  tolerance, and 70% fully correct tables on the declared scope. Narrow supported
  scope explicitly if needed; do not replace usefulness with format validity.
- At least 30-chart human crossover pilot: median verified-table time at least
  50% lower than manual transcription, without increased final errors.
- Equal-quality serving improvement: at least 2× valid throughput or 30% lower
  p95 latency versus a competent baseline. Three repeats; at least 1,000 attempts
  for p99 claims; retain timeouts and intended send timestamps.
- Initial modest-density application target (at most 50 values/chart): warm
  submit-to-review p95 ≤15s at four concurrent jobs, cold p95 ≤90s, submission
  acknowledgement p95 <500ms. Calibrate on development data before final testing.
- <1% accepted-work technical failures at declared steady load; bounded overload.
  No GPU dispatch for queued cancellation; measure active remote release against
  a proposed 2s target where supported.
- Detect sustained actionable incidents within five minutes; measure restore
  against existing objectives and verify cost-stop behavior.
- Training promotion: at least +3 points on the selected real-chart metric with
  paired interval excluding zero, no major validity/unit regression, acceptable
  cost/latency, and an untouched final holdout.

## Compute discipline

No new paid inference or training is needed for scorer, parser, approval, export,
or saved-evidence work. Calibrate an inference experiment before allocating time;
start with a bounded diagnostic budget (the investigation proposed 2 H100 hours
and 4 L4 hours, excluding other resource costs). This is not a prediction that the
full matrix will fit. Estimate training from a short step-time calibration and
stop rules. Do not promote an incomplete quality comparison.
