# Public account release review

Reviewed September 11, 2026, against the approved UI base `4ebdcaa`. Scope:
schema 10 activation/mailbox ownership, production password signup with email
deferred, zero-credit account flows, public support contact, tests and runbooks.
The operator explicitly approved public signup and supplied the support address;
SMTP, billing and automatic extraction credits remain disabled.

## Review findings and disposition

Every actionable finding from the independent review passes is recorded below.

1. **P1 — Legacy activation was mistaken for mailbox proof; fixed.**
   `unrender/product/database.py:414`: schema 9 also set `email_verified` after
   operator activation and during legacy migrations. Schema 10 now copies that
   state into `account_active` and clears the old mailbox flag. Existing access,
   sessions, data and credits survive; future email recovery requires fresh
   password-confirmed verification. A regression migrates the prior operator
   account shape and rejects email reset until real verification completes.
2. **P2 — Existing zero-credit users could not find access guidance; fixed.**
   `unrender/product/static/index.html:83`: the notice and contact action now sit
   outside the empty-state view, so they remain visible while reviewing an
   existing chart. The example remains available in the empty workspace.
3. **P2 — Post-export upload ignored the zero-credit state; fixed.**
   `unrender/product/static/app.js:708`: the export follow-up button shares the
   upload credit gate, and `startUpload` rejects unavailable account capability
   before discarding edits or changing views. The existing-chart/export journey
   verifies that downloads work and another upload cannot open at zero credits.
4. **P2 — Rollback instructions described the old schema; fixed.**
   `docs/OPERATIONS.md:161`: current guidance now describes schema 10, migrations
   from 1–9, legacy ownership semantics, and restoration of the coordinated
   pre-v10 recovery set before reverting to schema-9 code. Dated hosted schema-9
   receipts are retained as historical evidence.
5. **P3 — Signup's success message offered an unavailable upload; fixed.**
   `unrender/product/static/app.js:902`: zero-credit signup now directs the person
   to the example or an extraction-access request. The browser scenario checks
   that message, the disabled upload actions and the available support path.
6. **Reviewability — Account scope exceeded complex-change size guidance;
   addressed through staged commits.** `unrender/product/config.py:167` and
   `tests/test_accounts.py:172`: the combined change includes substantial
   migration/race/negative coverage plus release documentation. It is not a
   mechanical change, and documentation does not exempt the aggregate size.
   Commit `af9667c` separates account state and its tests (396 changed lines);
   `f9b06cd` supplies the UI/API-field consumers and flow tests (139 lines);
   the final policy commit opens registration only with the guarded settings,
   production-mode/no-spend tests and deployment instructions. Deploy the fully
   reviewed release, not an arbitrary intermediate commit.

The parent also corrected an existing configuration test that expected the old
registration-policy error message; it now checks the retained zero-credit
invariant. The first complete run exposed this stale assertion. The final run
passed after the correction.

Breaking-change and reuse review found no additional actionable issues. The
activation-based login error and operator-grant eligibility are deliberate
policy changes; public account/config fields are additive. No inference-context
fragments or prompts changed. Repeated reset checks protect separate pre-hash
and transaction-time race boundaries and were retained intentionally.

## Verification

- Full repository pytest: **268 passed, 1 skipped** in 99.59 seconds.
- Browser workflow harness: **45 scenarios passed**, including signup, credit
  refresh, retained chart access, export and the last-credit follow-up.
- Account recovery configuration harness passed; focused migration/future-email
  follow-up independently passed nine tests.
- Ruff formatting/lint/security and mypy on all 19 product sources passed.
- Local browser signup, sign-out and sign-in passed. Light/dark mobile signup,
  workspace and help screens were inspected at 390 px without horizontal
  overflow. Screenshots are in ignored `outputs/public-signup/`.
- The existing Starlette/httpx deprecation warning and intentional local Modal
  test warnings remain; tests did not invoke hosted inference or send email.

Three parallel simplify passes covered reuse, quality and efficiency. Separate
code-review passes covered breaking changes, context, testing and change size;
the final four specialized passes used xhigh reasoning. Follow-up reviews found
the reported fixes complete and no remaining actionable source issues in this
delta. Hosted rollout evidence belongs in [RENDER_MODAL_LAUNCH.md](RENDER_MODAL_LAUNCH.md).

This review does not close the existing native-advisory assessment, cloud access
attestation, customer-quality/correction-time evidence, or missing legal operator
and reviewed terms/privacy inputs. Support email is supplied; automated email,
customer billing and analytics are still deferred.
