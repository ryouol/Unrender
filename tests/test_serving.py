"""CPU contract evidence, never represented as GPU serving measurements."""

import asyncio
import io
import json
import threading
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from PIL import Image

from unrender.product.config import Settings
from unrender.product.extractors import ExtractionError
from unrender.serving.benchmark import check_split
from unrender.serving.client import Measurement, generate, request_body
from unrender.serving.release import inventory, model_name

MODEL = "unrender-" + "a" * 64
CHART = {
    "chart_type": "bar",
    "title": None,
    "x_axis": {},
    "y_axis": {},
    "series": [{"name": None, "points": [{"x": "A", "y": 1}]}],
}


def png():
    output = io.BytesIO()
    Image.new("RGB", (8, 8)).save(output, format="PNG")
    return output.getvalue()


def event(content="", finish=None, model=MODEL):
    return (
        "data: "
        + json.dumps(
            {
                "model": model,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}],
            }
        )
        + "\n\n"
    ).encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def run_stream(stream, **kwargs):
    calls = []

    async def run():
        def handler(request):
            calls.append(request)
            return httpx.Response(200, stream=stream)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate(
                client,
                url="http://test",
                body=request_body(png(), MODEL, False, 4096),
                request_id="job:1:2",
                timeout=kwargs.pop("timeout", 1),
                **kwargs,
            )

    return run, calls


def test_stream_fragmentation_release_and_usage():
    raw = json.dumps(CHART)
    wire = event(raw[:20]) + event(raw[20:], "stop") + b"data: [DONE]\n\n"
    stream = Stream([wire[i : i + 3] for i in range(0, len(wire), 3)])
    tokens = []
    run, calls = run_stream(stream, on_token=tokens.append)
    result = asyncio.run(run())
    assert result.raw == raw and "".join(tokens) == raw
    assert result.ttft_s is not None and len(calls) == 1 and stream.closed
    assert calls[0].headers["X-Request-Id"] == "job:1:2"


@pytest.mark.parametrize(
    "chunks,code",
    [
        ([event("{}", "stop", "wrong"), b"data: [DONE]\n\n"], "provider_release_mismatch"),
        ([event("{}", "length"), b"data: [DONE]\n\n"], "model_output_invalid"),
        ([event("{}", "stop")], "model_output_invalid"),
        ([b"data: broken\n\n"], "provider_unavailable"),
        ([b'data: {"error":{"message":"invalid schema"}}\n\n'], "provider_unavailable"),
    ],
)
def test_failures_never_retry(chunks, code):
    stream = Stream(chunks)
    run, calls = run_stream(stream)
    with pytest.raises(ExtractionError) as exc:
        asyncio.run(run())
    assert exc.value.code == code and len(calls) == 1 and stream.closed


def test_total_deadline_closes_stalled_stream():
    stream = Stream([event("{}")], delay=1)
    measurement = Measurement()
    run, calls = run_stream(stream, timeout=0.03, measurement=measurement)
    with pytest.raises(ExtractionError, match="deadline"):
        asyncio.run(run())
    assert len(calls) == 1 and stream.closed and measurement.elapsed_s < 0.5


def test_cancel_closes_stalled_stream():
    stream = Stream([event("{}")], delay=1)
    cancelled = threading.Event()
    run, calls = run_stream(stream, cancelled=cancelled.is_set)
    timer = threading.Timer(0.03, cancelled.set)
    timer.start()
    try:
        with pytest.raises(ExtractionError) as exc:
            asyncio.run(run())
        assert exc.value.code == "provider_cancelled"
        assert len(calls) == 1 and stream.closed
    finally:
        timer.join()


def test_oversized_unterminated_frame_is_bounded():
    run, calls = run_stream(Stream([b"x" * 100]), max_bytes=10)
    with pytest.raises(ExtractionError):
        asyncio.run(run())
    assert len(calls) == 1


def test_bad_image_and_schema_payload():
    with pytest.raises(ExtractionError, match="valid PNG"):
        request_body(b"bad image", MODEL, True, 4096)
    body = request_body(png(), MODEL, True, 4096)
    assert body["structured_outputs"]["json"]["title"] == "ChartData"
    assert "structured_outputs" not in request_body(png(), MODEL, False, 4096)


def test_manifest_changes_with_weights_processor_or_scheduler(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "processor.json").write_text("{}")
    before = inventory(tmp_path)
    first = model_name({"files": before, "max_num_seqs": 1})
    (tmp_path / "processor.json").write_text('{"changed":true}')
    assert first != model_name({"files": inventory(tmp_path), "max_num_seqs": 1})
    assert first != model_name({"files": before, "max_num_seqs": 2})


def test_tuning_cannot_touch_common300():
    common = json.loads(Path("unrender/eval/subsets/common300.json").read_text())["ids"]
    with pytest.raises(ValueError, match="overlaps"):
        check_split([common[0]], False)
    with pytest.raises(ValueError, match="full coverage"):
        check_split(common[:-1], True)
    check_split(common, True)
    check_split(["tuning-only"], False)


def test_product_configuration_is_opt_in_and_fails_closed(tmp_path):
    settings = Settings(
        data_dir=tmp_path, extractor_backend="vllm", vllm_model=MODEL, vllm_api_key="test-key"
    )
    settings.validate()
    for changed in (
        replace(settings, vllm_url="http://remote.example"),
        replace(settings, vllm_model="base-model"),
        replace(settings, environment="production"),
    ):
        with pytest.raises(ValueError):
            changed.validate()


@pytest.mark.parametrize("rate", [0, 1000])
def test_load_client_saves_attempts_and_bounds_open_loop(tmp_path, monkeypatch, rate):
    from argparse import Namespace

    from unrender.serving.benchmark import run

    manifest = {"test_only": "CPU mock, not engine measurements"}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    samples = []
    for index in range(3):
        source = tmp_path / f"tuning-{index}.png"
        source.write_bytes(png())
        samples.append(
            {
                "images": [str(source)],
                "messages": [
                    {"role": "user", "content": ""},
                    {"role": "assistant", "content": json.dumps(CHART)},
                ],
            }
        )
    data = tmp_path / "data.jsonl"
    data.write_text("\n".join(json.dumps(s) for s in samples))
    calls = []
    original_client = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/metrics":
            return httpx.Response(200, text="vllm:num_requests_running 0\n")
        calls.append(request)
        wire = event(json.dumps(CHART), "stop", model_name(manifest)) + b"data: [DONE]\n\n"
        return httpx.Response(200, stream=Stream([wire], delay=0.03))

    def client(**kwargs):
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setenv("UNRENDER_VLLM_API_KEY", "cpu-test")
    args = Namespace(
        data=data,
        manifest=manifest_path,
        out=tmp_path / "result",
        final=False,
        constrained=False,
        max_tokens=4096,
        timeout=1,
        concurrency=1,
        rate=rate,
        engine="vllm",
        url="http://test",
    )
    summary = asyncio.run(run(args))
    rows = [json.loads(line) for line in (args.out / "predictions.jsonl").read_text().splitlines()]
    assert summary["requests"] == len(rows) == 3
    assert len({r["id"] for r in rows}) == 3
    if rate:
        assert len(calls) == 1 and summary["failures"] == 2
        assert sum(r["error"] == "client_admission_rejected" for r in rows) == 2
    else:
        assert len(calls) == 3 and summary["valid"] == 3
    assert (args.out / "run.json").is_file() and (args.out / "metrics.jsonl").is_file()


def test_ttft_ignores_role_events_and_accepts_real_token_events():
    role = {"model": MODEL, "choices": [{"delta": {"role": "assistant"}}]}
    token = {"model": MODEL, "token_ids": [42], "choices": []}
    wire = [
        ("data: " + json.dumps(role) + "\n\n").encode(),
        ("data: " + json.dumps(token) + "\n\n").encode(),
        event(json.dumps(CHART), "stop"),
        b"data: [DONE]\n\n",
    ]
    run, _ = run_stream(Stream(wire, delay=0.01))
    result = asyncio.run(run())
    assert result.ttft_event == "token_ids"
    assert result.chunks[0]["token_ids"] == [42]
    assert result.ttft_s < result.chunks[1]["elapsed_s"]


def test_failure_inclusive_accuracy_and_unknown_token_throughput():
    from unrender.serving.report import summarize

    valid = {
        "status": "ok",
        "error": None,
        "gt": json.dumps(CHART),
        "raw": json.dumps(CHART),
        "meta": {},
        "usage": {},
        "ttft_s": 0.5,
        "response_s": 1.0,
        "strict_valid": True,
        "server_timings": {"queue_s": 0.2},
    }
    failed = dict(
        valid,
        status="infra_error",
        error="provider_timeout",
        strict_valid=False,
        raw="",
        response_s=2.0,
        ttft_s=None,
        server_timings={},
    )
    summary = summarize([valid, failed], 2)
    assert summary["failures"] == 1
    assert summary["valid_requests_per_s"] == 0.5
    assert summary["output_tokens_per_s"] is None
    assert summary["numeric_accuracy_failures_as_misses"]["cell_accuracy_exact"] == 0.5
    assert summary["p95_response_s"] == 1
    assert summary["p95_all_attempt_response_s"] == 2
    assert summary["json_parse_success"] == summary["strict_schema_success"] == 1
    valid["usage"] = {"completion_tokens": 10}
    assert summarize([valid, failed], 2)["output_tokens_per_s"] == 5
