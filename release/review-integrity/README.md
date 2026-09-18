# Review integrity verification

Local verification, September 17–18, 2026 (Toronto), based on main `c84b741` and
readiness checkpoint `f7713b2`. This records a local implementation check, not a
production rollout. No GPU inference was invoked.

## What changed

Corrections, approvals, restores and exports require the displayed review revision.
Writes compare it under the transaction that publishes the change; a save response
cannot accidentally return a later writer's version. Immutable version identity
prevents an A→B→A content change from reviving a stale revision. Status and attempt
changes also invalidate it. Exact-version audit references and workbook metadata
identify the captured result. See the [contract](../../docs/API.md#browser-review-concurrency-contract).

## Automated evidence

`tests/test_review_integrity.py` exercises stale save/approve/restore/export,
identical-content restoration, two concurrent database connections, a writer
intervening immediately after save commit, edits during export rendering, exact
approval/export receipts, mandatory HTTP preconditions, and inconsistent history.

`tests/browser_workflow.mjs` checks the actual frontend handlers, including revision
forwarding, stale responses, conflict preservation, failed/cancelled reloads, and
export rejection. Its browser surfaces are simulated. Real-browser checks below
are separate evidence.

The full Python suite passed **356 tests, one skipped**, with four existing warnings
in 125.53 seconds. The skip still requires the private train-table artifacts.
The frontend workflow harness passed **76 scenarios**. Product type checking passed
for 24 source files. After the conflict-focus refinement, the seven review-integrity tests and all
76 workflow scenarios passed again. Product lint and security lint passed.

## Actual two-tab check

A disposable replay service ran at `127.0.0.1:8017`, using a temporary directory,
with cloud integrations left unconfigured. Two Codex in-app browser tabs shared
one isolated demo account. No production account or data was used.

1. Both tabs displayed version 1, row 1 = **9.2**.
2. B saved **123456**, producing version 2.
3. A tried Save & approve with its old view: a conflict appeared; it still displayed
   the original result. No unseen result was approved.
4. A entered **9.3** and tried Save corrections: a conflict appeared; **9.3 stayed
   visible**. A read-only database check found current value **123456**, status
   `review`, **two versions**, and **zero approval events**.
5. A explicitly loaded the latest version, saw **123456 / version 2**, and approved
   it. B's old draft export was rejected because its review state was stale.
6. A's approved workbook download reached the browser's download-started state.
   Automated tests separately inspect workbook content and exact hash metadata.
7. A restored version 1. The page displayed **9.2 / version 3 / needs review**.
8. B tried to restore version 2 from its stale view and received a conflict.
9. After reloading the final frontend, another stale approval focused the conflict
   notice and brought its Load latest version action visibly into view.

The browser's reload click reported a transport timeout, but the next authoritative
page state showed version 2 loaded. It was not retried or treated as a failed mutation.
The explicit dirty-discard choice is covered deterministically in the frontend
harness; native dialog interaction was not separately attested in this browser.

## Remaining boundaries

- This does not validate historical approvals made before revision enforcement.
  Require fresh review before attaching the new guarantee to those records.
- Export unit/scale preservation, complete source/model provenance, safe parser
  diagnostics, and the remainder of the readiness plan are still open.
- Audit history remains bounded and can be rolled up; no immutable permanent audit
  service is claimed.
- No production deployment or GPU canary was part of these checks.
