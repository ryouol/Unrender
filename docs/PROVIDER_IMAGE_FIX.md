# Large-image extraction incident — September 16, 2026

The provider was reachable. Its saved training tokenizer implicitly truncated an
expanded image sequence: 2,044 image tokens survived out of 2,100, and Qwen3-VL
raised an image-token mismatch. The worker's generic provider-unavailable error
obscured this processor failure. Explicit `truncation=False` fixes that failure.

The same 1920 × 1120 demo chart then exposed a separate prefill bottleneck. On L4,
full-resolution warm inference took 90.58 seconds. Generating only 16 output
tokens still took 78.50 seconds, versus about 90 seconds for the complete 188-token
answer. Changing CPU threads from four to one, forcing the Flash SDPA backend,
or shortening the output cap did not solve it. H100 reduced warm time to 59.82
seconds, insufficient to justify its higher per-second cost here.

Production now passes a 524,288-pixel maximum through the processor's explicit
per-request `images_kwargs.size`. This limits vision input to 512 image tokens;
the demo uses 493 image tokens plus 229 prompt tokens. The saved processor and
original uploaded image stay unchanged. An `AutoProcessor.from_pretrained`
`max_pixels` override alone was ignored by this pinned processor, which is why
the regression and canary check effective token counts and immutable settings.
The general evaluation provider retains its original preprocessing unless its
caller explicitly selects a pixel budget. This is a **preprocessing change**,
not a runtime-only comparison, quantization change or vLLM rollout.

The final release canary took 30.14 seconds warm, versus 90.58 seconds for the
full-resolution control: approximately 3× faster on this chart. Both final cold
and warm outputs exactly match the control's complete chart, including all 12
reference values, title, chart type, series and units. These are single-chart
operational measurements, not p95 estimates or a general accuracy result.
Common300 was not used for this incident investigation.

Cold snapshot verification still takes about 30 seconds. The final canary's
first provider call took 67.01 seconds, but diagnostic imports and container
scheduling occur outside that measurement; it is not complete client cold-start
latency. Exact loaded model objects can now reuse their verified release, and
the single L4 worker remains warm for 120 seconds before scaling to zero. New
containers, replacement/eviction of model objects, or different release keys
require full byte verification again. Minimum containers remain zero, maximum
one, function deadline 240 seconds and automatic retries zero. Worker fencing,
dispatch accounting and application validation are unchanged.

Model digest remains
`3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e`.
The canaried provider release is
`21e1622ed2e8dc4ba5151a966e65cf5b6e004f9f3ce1c1be13cbce29561c1b61`.
Use the matching Render pin when deploying `modal_train.py::production_app`.
Close ingress and drain work before changing both sides of that contract.

Raw output and stage measurements are in
`release/launch-eval-results/provider-image-fix/`. A full-resolution CPU/CUDA
profiler attempt exceeded its isolated 300-second diagnostic deadline and was
stopped; it is not a successful trace or a serving failure measurement. Short
output diagnostics are not quality evaluations. The focused regressions cover
token integrity, per-request processor settings, exact-object warm reuse,
re-verification and privacy-safe token counts. The full suite and image build
are checked in CI before rollout.
