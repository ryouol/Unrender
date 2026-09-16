# Serving experiment runbook

The authorized H100 experiment ran on 2026-09-16. See the measured
[serving case study](SERVING_CASE_STUDY.md) for results, raw evidence, quality
gates and limitations. The earlier Mac-only preflight remains historical evidence.
The existing Modal path remains the production provider; the vLLM path is an
isolated experimental integration and production configuration rejects it.

## Compatibility finding

Candidate runtime: **vLLM 0.11.0**, a deliberately pinned experimental release,
not a recommendation to expose an old runtime publicly. Its
[Qwen3-VL implementation](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/model_executor/models/qwen3_vl.py)
exists, but architecture support does not prove this checkpoint combination.
The [multimodal support documentation](https://docs.vllm.ai/en/v0.11.0/models/supported_models.html)
limits multimodal LoRA support to the language backbone. Unrender's training
configuration enables **vision and language** adaptation (`sft_lora.py`). Inspect
the actual adapter configuration and tensor names on the GPU host; do not drop
vision targets to make loading succeed.

The measured production release is frozen at
`unrender-inference-cache:/releases/3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e`.
The research checkpoint originated at `runs/qwen3vl4b-table-fair/merged`. The repository does not contain that weight snapshot. The research
base control is the Unsloth mirror at
`252d592b59b0233b226875a44ac135cfa1d3f755`; it is not a substitute for the LoRA.
Use the existing merged 16-bit checkpoint and its saved processor first. Export
and hash its entire materialized snapshot. Compare the existing Transformers
path against that same merged checkpoint before describing a runtime comparison.
An adapter-versus-merged comparison is a separate model-conversion gate.

Timebox GPU compatibility work to 2–4 hours. Save adapter loading output,
processor/config identities, GPU UUID, driver/CUDA versions, package freeze,
engine startup logs, resolved launch command, and canary raw responses. Verify
unconstrained generation first, then the complete ChartData schema. If blocked,
record the exact exception/configuration and keep any supported-model experiment
in a separate output directory, explicitly labeled as not deployed Unrender.

## Local checks and integration

```bash
python -m pip install -e '.[serving]'
python -m unrender.serving.release preflight
pytest -q tests/test_serving.py tests/test_product.py
```

`VllmExtractor` sits behind the existing worker boundary. The worker supplies
`job:attempt:lease-generation` as an opaque request identifier and a cancellation
callback. This header provides correlation, **not engine idempotency**. The
existing durable dispatch record, no transport retries, and lease fencing prevent
automatic redispatch after uncertain outcomes. An explicit user reprocess remains
a new charged attempt. The product publishes only a fully validated chart; the
benchmark consumes the same transport's incremental content.

The provider enforces one total streaming deadline (including silent streams),
bounds response bytes, requires a matching manifest-derived model name on every
SSE event, and rejects missing completion markers or token-limit truncation.
Cancellation/lease loss closes the stream even before the first token. Closing a
connection is **not proof of GPU abortion**: verify that engine running-request
metrics return to baseline after cancellation. Shutdown continues to use the
existing worker drain/heartbeat behavior.

Tests cover stream fragmentation, malformed input, schema error responses,
release mismatch, timeout, stalled-stream cancellation, truncation, oversized
frames, common300 exclusion, and worker cancellation/no-redispatch accounting.
These are CPU transport/worker tests; they do not prove that vLLM accepts every
feature or that a disconnected CUDA request has stopped.

## Reproduce the GPU setup

Use a dedicated NVIDIA environment with `vllm==0.11.0`; do not install CUDA
packages on the Mac or change the product's dependency locks. Resolve and save a
full environment lock/container digest on that host before measurements. Run
both engines in the same environment on the same GPU, one at a time. The launcher
checks the exact vLLM package version and every snapshot file hash. Mount the
snapshot read-only; the file hashes and served model name detect accidental drift,
not a malicious endpoint or files modified after verification.

```bash
python -m unrender.serving.release manifest \
  --snapshot /models/unrender-merged --manifest /results/baseline.json \
  --dtype bfloat16 --max-model-len 8192 --max-num-seqs 1 \
  --max-num-batched-tokens 8192 --gpu-memory-utilization 0.8
# Save the printed unrender-<digest> as UNRENDER_VLLM_MODEL.
# Set VLLM_API_KEY and UNRENDER_VLLM_API_KEY to the same secret out of band.
python -m unrender.serving.release launch \
  --snapshot /models/unrender-merged --manifest /results/baseline.json
```

The baseline launcher intentionally rejects adapter-only and quantized snapshots.
It binds to loopback; use an authenticated tunnel for another machine. Do not
expose this experimental server directly. For the product set
`UNRENDER_EXTRACTOR=vllm`, `UNRENDER_VLLM_URL=http://127.0.0.1:8001`, the printed
`UNRENDER_VLLM_MODEL`, `UNRENDER_VLLM_API_KEY`, and optionally
`UNRENDER_VLLM_CONSTRAINED=true`. Default deadline is 120 seconds.

Stop vLLM before starting the Transformers reference:

```bash
python -m unrender.serving.transformers_server \
  --snapshot /models/unrender-merged --manifest /results/baseline.json
# Add --profiles /results/transformers-profiles only for a separate investigation.
```

This reference serializes model generation, preserving the existing single-call
Transformers behavior under concurrent arrival. It uses the same saved processor,
explicit precision, greedy decoding, prompt, context limit and image bytes.
It reports queue, preparation/transfer, and inference durations; the benchmark
reports application validation separately. Its optional CPU profile files are
Python deterministic profiles, **not sampling profiles or CUDA traces**. Run
profiled investigations separately from unprofiled latency baselines. Transformers
text streaming buffers decoded words, so client TTFT is **time to first nonempty
text chunk**, not a kernel-level first-token timestamp; compare engine token
metrics separately. The reference has no vLLM metrics endpoint.

## Measurements and workload isolation

Use a PNG-only tuning JSONL in the existing evaluation dataset format, with IDs
disjoint from common300. The client refuses overlap, duplicates, absent images,
and empty workloads before dispatch. Normalize images once and use the same
bytes for both engines. The run records a hash of ordered IDs, ground truth and
image contents. Keep the same token cap, prompt, precision and warmup policy.

```bash
python -m unrender.serving.benchmark --engine vllm \
  --data /results/tuning.jsonl --manifest /results/baseline.json \
  --out /results/vllm-c1 --concurrency 1
# Run the same command with --engine transformers against the reference server.
# --engine labels the run; it does not start or authenticate an engine binary.
# Then repeat with --concurrency 2, 4, 8, 16 after inspecting each result.
# Fixed arrival example, using the same workload:
python -m unrender.serving.benchmark --engine vllm \
  --data /results/tuning.jsonl --manifest /results/baseline.json \
  --out /results/vllm-rate1 --concurrency 8 --rate 1
```

Each new directory contains run metadata, raw `predictions.jsonl` with every
attempt, first-text latency, chunk timings, usage when reported, explicit
failures, `summary.json`, and one-second raw Prometheus snapshots. Open-loop
runs bound in-flight work and count admission rejection instead of hiding an
unbounded client queue. p95 response includes arrival scheduling delay. Client
preparation measures PNG verification/serialization, **not the engine's image
processor**. Run enough requests/seconds for stable percentiles, repeat three
times, and report dispersion. Do not infer GPU execution time from HTTP duration.

Sweep fixed arrival at roughly 0.5/0.75/0.9/1.0/1.1 times measured saturation.
Inspect GPU free memory, failures, running/waiting requests, preemptions, and KV
usage between every run. **No unattended sweep or automatic memory-pressure stop
is implemented**; stop manually on OOM, increasing preemption, >90% KV occupancy,
or less than 2 GiB free device memory. Never advance blindly to concurrency 16.
Use fresh manifests changing only sequence limit, then only scheduler token limit.
The within-vLLM max-sequences=1 comparison helps separate batching from changing
runtimes; document remaining scheduling differences.

For the final quality run, `--final` selects exactly common300 and requires full
coverage. The existing scorer is unchanged:

```bash
python -m unrender.serving.benchmark --engine vllm \
  --data data/synthetic_v1/test.jsonl --manifest /results/baseline.json \
  --out /results/final-vllm --final
python -m unrender.eval.score --predictions /results/final-vllm/predictions.jsonl
```

Missing local images must be restored before this command can run. Final
comparisons require **zero infrastructure failures and all 300 IDs**, because
the historical scorer excludes infrastructure errors. Report strict validity
from the client separately from the scorer's existing deterministic repairs.
Do not compare a repaired score against another run's strict validity.

## Preregistered decisions and remaining experiments

Before any final run, the promotion criterion is: at most **1.0 percentage point
absolute regression in common300 cell@5_exact**, no missing/infra-error samples,
and no decrease in strict chart validity versus the newly rerun higher-precision
baseline. Preserve per-chart paired results and report sampling uncertainty; the
historical 38.9% number is context, not the new baseline. Any criterion change
requires a dated preregistration revision before opening final results.

- Structured output: compare `--constrained` on/off using the identical tuning
  workload, then the reserved final set. Keep semantic application validation.
  Test a malformed image, invalid schema, token cap, timeout, and disconnect
  against the actual engine. The
  [pinned structured-output API](https://docs.vllm.ai/en/v0.11.0/features/structured_outputs.html)
  uses `structured_outputs.json`; local schema acceptance is not proof of model
  accuracy or engine compatibility.
- KV cache: generate separately labeled workloads with short/long prompts and
  explicitly shared versus unrelated prefixes. Keep the image/prompt ordering
  and precision controlled. Restart with prefix caching off/on using separate
  manifests; record cache hits, occupied blocks, capacity and preemptions. This
  client currently uses the canonical prompt only; prefix/context workload
  generation remains to be implemented. Weight VRAM, cache capacity, and cache
  occupancy are distinct quantities.
- Quantization: after the GPU gate, select one supported lower-precision method
  for the **same fine-tuned model**, record calibration/conversion provenance,
  and extend the manifest launcher deliberately. Compare VRAM/capacity, quality,
  latency and throughput against the established higher-precision baseline.
  Quantized serving is not implemented or verified in this commit.
- Tracing: add OpenTelemetry propagation across API, durable job, worker and
  provider; save and interpret a real trace. The current correlation header is
  not OpenTelemetry. For preprocessing investigation, enable the reference CPU
  profile and inspect it with `python -m pstats`. Escalate to PyTorch profiler or
  Nsight only if evidence points to GPU execution/transfer stalls.
- Speculative decoding and SGLang are deferred until the vLLM baseline passes.
  A supported text-only experiment must be labeled separately. Record draft
  acceptance/memory and low/high-load on/off comparisons, not just throughput.

There are no measured load curves, quality-preserving runtime decision, cache or
quantization findings, interpreted GPU trace, or GPU cancellation evidence yet.
The investigated local limitation is the worker's intentionally serial SQLite
execution: product throughput will remain at one active inference even if vLLM
can batch benchmark requests. Changing that requires separate queue/worker
capacity work; the direct-provider benchmark must not be presented as end-to-end
product throughput. Keep saved raw GPU results outside Git if large or sensitive,
with a durable artifact location and content hashes in the final report.
