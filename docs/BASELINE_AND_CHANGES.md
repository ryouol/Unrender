# Baseline and change record

## Baseline at `9f13196`

The repository contained a substantial research pipeline: deterministic chart generation, a strict schema, training/evaluation code, saved benchmark receipts, and a Modal single-image inference function. The latest local baseline passed 67 tests with one optional Modal split-artifact test skipped after installing missing development dependencies.

There was no customer-facing product UI, account or tenant boundary, durable product job model, source-side review flow, API authentication, billing lifecycle, deployment container, operator runbook, or product decision. Because no UI existed, a truthful “before” screenshot is unavailable.

The README led with the aspiration to recover exact values and beat frontier systems, while the later research receipts correctly showed a mixed result: clear improvement over the base, parity with one saved comparison on a small overlap, and weaker results than two others. The real-chart set was only eight charts and had a contamination caveat.

## Product changes

- Repositioned from “exact model” to a review-first evidence workflow.
- Added a restrained responsive web product with explicit unverified/approved states.
- Added accounts, secure sessions, CSRF, origin enforcement, tenant checks, API keys, and request limits.
- Added validated upload/page/crop handling and private, generated storage paths.
- Added persistent jobs, result versions, audit events, credit ledger, restart recovery, cancellation, refunds, retention, and an embedded worker.
- Added saved-replay and Modal extractor implementations behind one typed boundary.
- Added CSV, JSON, and XLSX exports with approval/model metadata.
- Added Stripe test-mode checkout/webhook handling with signature and replay protection; live secrets are rejected.
- Added product regression tests, dependency lock, non-root container, CI, runbooks, legal/security inventories, and launch gates.

## Simplification choices

- One product service owns lifecycle and credit invariants; HTTP handlers stay thin.
- One chart schema is shared by research, inference, editing, and export.
- One stored job source survives prepared-upload expiry.
- One exact fixture powers the demo without pretending to be live inference.
- One single-node topology is documented honestly instead of shipping premature distributed infrastructure.
- Billing stays disabled unless every test-mode secret is present.
