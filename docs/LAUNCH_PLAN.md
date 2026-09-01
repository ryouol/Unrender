# 30-day design-partner launch plan

## Goal

Validate whether review-first digitization saves meaningful analyst time and supports a positive per-chart margin. Do not optimize signups or announce benchmark superiority.

## Week 1 — prepare evidence

- Complete visual, accessibility, security, and independent code-review gates.
- Run a real Modal canary on non-sensitive charts and measure latency/cost.
- Finalize owner identity, privacy, terms, support, and deletion process.
- Recruit five design partners from research, consulting, data journalism, or market intelligence.
- Record each partner's existing chart-digitization workflow and baseline time.

## Week 2 — concierge pilot

- Give partners controlled accounts; keep registration closed.
- Ask each to process five representative charts.
- Observe review/correction friction rather than coaching around it.
- Tag failures by chart family, source quality, labels, and PDF/image path.
- Respond manually within one business day and record support time.

## Week 3 — repeat use and API

- Ask successful partners to complete a second independent batch.
- Offer API keys only to teams with a repeat workflow.
- Measure approved exports, second-session return, correction rate, failed/refunded jobs, and actual cost.
- Show a non-chargeable test checkout to users who express purchasing intent; do not accept live payment.

## Week 4 — decision

- Compare median time-to-approved-table against each partner's baseline.
- Review reliability and unit economics by chart type.
- Conduct willingness-to-pay interviews around the 100-credit hypothesis.
- Decide: paid beta, narrower chart-family scope, workflow-only product with a different extractor, or stop.

## Instrumentation events

The audit model records account, upload, queued, started, completed/failed/cancelled, correction, approval, and export events. Structured provider logs expose safe success/failure codes and latency. Before the pilot, connect platform aggregates for queue age, result versions, export format, credit/refund reconciliation, storage, and alert delivery. Never send chart content, titles, labels, filenames, tenant identity, cookies, or raw model output to analytics.

## Launch copy guardrails

Use: “Extract a first pass, review it beside the source, and export an auditable table.”

Avoid: “exact,” “automatic truth,” “beats GPT/Claude/Gemini,” “enterprise-ready,” “secure/compliant” without qualification, or any accuracy percentage not tied to a named frozen evaluation and caveats.
