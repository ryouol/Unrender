# Documentation

Start with the [engineering review guide](ENGINEERING_REVIEW.md) for a code review or the [local setup](../README.md#run-locally) for a demo.

| Task | Read |
|---|---|
| Understand the current release and open work | [Readiness](LAUNCH_READINESS.md), [deployment record](RENDER_MODAL_LAUNCH.md) |
| Review architecture and API behavior | [Architecture](ARCHITECTURE.md), [API](API.md), [chart library](CHART_LIBRARY.md) |
| Operate or recover the service | [Operations](OPERATIONS.md), [request limits](REQUEST_LIMITS.md) |
| Review accounts and security | [Account policy](PUBLIC_ACCOUNTS.md), [Google sign-in](GOOGLE_SIGNIN.md), [security model](SECURITY_MODEL.md), [container scan](CONTAINER_SCAN.md) |
| Assess model quality and benchmark requirements | [Evaluation contract](EVALUATION_CONTRACT.md), [remediation plan](AUDIT_REMEDIATION.md) |
| Reproduce training or generate data | [Training reproducibility](TRAINING_REPRODUCIBILITY.md), [synthetic data](SYNTHETIC_DATA.md) |
| Inspect visual work | [Screenshots](screenshots/README.md), [visual QA record](design/VISUAL_QA_RECORD.md) |
| Inspect licenses and release policy | [Legal review](LEGAL_REVIEW.md), [third-party notices](../THIRD_PARTY_NOTICES.md) |

## Evidence and history

Machine-readable evidence remains under [`release/`](../release/). The [September 18 receipts](../release/readiness-remediation-20260918/) record the deployed runtime, GPU canary, hosted workflow, restore and container scan. Frozen inputs and old predictions retain their original locations.

[Deployment history](archive/RENDER_MODAL_LAUNCH.md), [earlier readiness checks](archive/LAUNCH_READINESS.md) and [scan history](archive/CONTAINER_SCAN.md) preserve prior release records.

[Historical research](archive/research/README.md) contains earlier experiments and proposals. Their claims describe the methods and evidence available at the time; use the current evaluation contract for present claims. Earlier product design and audit documents elsewhere in this directory are dated records, not deployment instructions.

Some historical galleries under `outputs/` refer to generated images that are not included in a clone. The saved predictions remain available; those galleries cannot display the absent source files.
