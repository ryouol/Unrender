# Product decision

## Decision

Build Unrender as a **review-first chart digitization workspace and API** for research and consulting teams. The commercial unit is a reviewed, exportable evidence record—not an unsupported promise that a model reads every chart exactly.

This direction uses the repository's genuine assets: a strict chart schema, deterministic data generation, a reproducible evaluation harness, saved model evidence, and an existing single-image inference boundary. It removes the riskiest original assumption: that narrow-model benchmark performance alone is a product.

## Buyer and job

Initial buyer: a research lead, consultant, analyst, or data-journalism team that repeatedly encounters charts without downloadable tables.

Their job is: “Turn values trapped in a source chart into reusable data, while preserving enough evidence for another person to check my work.”

The painful parts are not only extraction. They are page/crop selection, catching errors, reconciling labels, preserving the source, documenting corrections, and producing a defensible handoff. Unrender owns that full loop.

## Market alternatives and wedge

- [WebPlotDigitizer](https://www.automeris.io/) offers mature manual calibration, point capture, and CSV export. Its own [digitization documentation](https://www.automeris.io/docs/digitize/) shows why calibration and human inspection remain central.
- [PlotDigitizer](https://plotdigitizer.com/app) offers manual chart calibration and multiple export formats.
- General document-extraction products such as [Reducto](https://docs.reducto.ai/extract/overview) extract broader PDF content and emphasize citations, rather than a chart-specific editable data contract.

Unrender's wedge is narrower: automated first-pass extraction plus mandatory source-side review, value-level editing, explicit approval, versions, and API/export provenance. It should win on time-to-defensible-table, not on a broad “AI document platform” pitch.

## Offer and pricing hypothesis

- Free: the saved verification fixture, always zero provider cost.
- Initial paid hypothesis: **US$99 for 100 chart credits**, one credit per real extraction attempt. A cancellation or failure refunds only when durable provider dispatch has not occurred; after dispatch, the credit is consumed because provider spend may already have happened. A recent-failure circuit stops later attempts before dispatch and refunds those unspent reservations.
- No subscription at validation stage. A credit pack maps cleanly to variable inference cost and avoids inventing recurring value before retention is known.

This is a planning hypothesis, not a live offer. The code only accepts Stripe test-mode secrets. The owner must create a test Price, validate willingness to pay, and approve final copy before enabling checkout.

## Unit economics hypothesis

Illustrative assumptions per 100-credit pack:

| Item | Assumption |
|---|---:|
| Revenue | $99.00 |
| GPU, storage, and delivery | $6.00 |
| Payment processing (2.9% + $0.30 assumption) | $3.17 |
| Contribution before support and payroll | $89.83 |

At 12 packs per month, gross revenue would be $1,188. These are decision-model inputs only. Provider cost must be measured from real jobs, and processor terms must be confirmed for the owner's account and customer geography.

## Validation plan

Run a 30-day design-partner program with 5–10 research teams.

Measure:

- median minutes from upload to approved export;
- correction rate by chart family;
- job failure/refund rate;
- percentage of users who approve a second chart within seven days;
- percentage who export or use the API;
- support minutes per 100 charts;
- actual inference and storage cost per completed chart;
- willingness to buy a 100-credit test pack.

Advance to paid beta only if at least three independent teams complete 20+ real charts, at least 60% return for a second session, median review time beats their existing workflow, and gross contribution remains positive after measured support.

Kill or reposition if users require so much correction that the workflow is slower than manual calibration, if chart-family reliability is too uneven to set expectations, or if support/privacy requirements make the $99 pack uneconomic.

## Scope boundaries

In v0.2:

- supported input: PNG, JPEG, WebP, or a selected PDF page;
- supported output schema: bar, horizontal bar, grouped bar, stacked bar, line, multi-line, and pie;
- one selected chart per job;
- explicit human approval;
- single-node SQLite deployment.

Not promised:

- exact automatic extraction;
- OCR or table extraction for arbitrary documents;
- multi-chart page segmentation;
- collaborative editing, SSO, or enterprise compliance;
- horizontal scaling;
- a public uptime SLA;
- public availability of private fine-tuned weights.
