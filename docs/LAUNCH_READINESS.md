# Launch readiness

**Controlled beta, as verified September 22, 2026.** Runtime `a7673d9`, schema 15, is deployed on Render with the pinned Modal provider. Google and password signup grant three testing credits. Email delivery and billing are off.

| Area | Verified evidence | Remaining work |
|---|---|---|
| Product workflow | Hosted extraction, corrections, stale-approval rejection, exact-version approval, CSV/JSON/XLSX and browser download | Independent 30-chart workflow pilot |
| Deployment and recovery | Coordinated backup, schema upgrade, restore drill, matching source/package inventory, original account/chart data preserved | Production-scale recovery timing and ongoing restore practice |
| Model execution | Existing weights ran on L4; September 22 checked four visible values and labels, following the September 18 cold/warm canaries | Independent labels, representative accuracy and actual cost measurements |
| Training | Pinned recipe, processor and loss contracts; CPU process-kill/resume checks | Real Qwen/CUDA interrupted-training check and generated-task checkpoint selection |
| Serving | Durable attempts and bounded worker pool; production concurrency remains one | Same-GPU comparison, repeated load tests, remote cancellation acknowledgement and global spend cap |
| Monitoring | Two-minute scheduled checks passed after rollout | New alert-delivery latency not measured |
| Security | Zero critical and zero Python findings in the recorded scan; access/accounting regression coverage | 44 high Debian findings, external security/accessibility review and complete live Google acceptance matrix |
| Data and legal | Frozen evidence and explicit source-review gates | Independent development-packet review and model/data legal approval |

The 72-chart packet is development material awaiting the reviewer arranged by the owner. It must stay separate from the final holdout. No new model was trained in this release, and the reference canary does not establish representative accuracy or a general speedup.

## Next steps

1. Complete independent source/label review and resolve rejected or disputed charts.
2. Run one bounded Qwen/CUDA training and interrupted-resume canary on approved development data.
3. Use a development inference/workflow pilot to set sample size, cost limits and timing targets.
4. Freeze the prospective quality/performance study before collecting final outcomes.
5. Complete the remaining security, legal and account-recovery reviews before broadening access.

The [remediation plan](AUDIT_REMEDIATION.md) defines the benchmark thresholds and stop conditions. The [deployment record](RENDER_MODAL_LAUNCH.md), [container scan](CONTAINER_SCAN.md) and [engineering guide](ENGINEERING_REVIEW.md) link the supporting evidence. The [historical scorecard](archive/LAUNCH_READINESS.md) preserves earlier checks and their dates.
