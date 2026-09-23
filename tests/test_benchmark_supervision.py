"""Fault injection for benchmark admission and durable outcome publication."""

import asyncio
import json
from argparse import Namespace

import httpx
import pytest
from test_serving import CHART, Stream, event, png

from unrender.eval.ledger import load_predictions
from unrender.serving import benchmark
from unrender.serving.release import model_name


@pytest.fixture
def workload(tmp_path, monkeypatch):
    manifest = {"test_only": "CPU fault injection"}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    samples = []
    for index in range(3):
        source = tmp_path / f"chart-{index}.png"
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
    data.write_text("\n".join(json.dumps(row) for row in samples))
    calls = []
    original = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/metrics":
            return httpx.Response(200, text="test 0\n")
        calls.append(request)
        wire = event(json.dumps(CHART), "stop", model_name(manifest)) + b"data: [DONE]\n\n"
        return httpx.Response(200, stream=Stream([wire]))

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setenv("UNRENDER_VLLM_API_KEY", "cpu-test")
    args = Namespace(
        data=data,
        manifest=manifest_path,
        out=tmp_path / "result",
        final=False,
        constrained=False,
        max_tokens=4096,
        timeout=2,
        concurrency=1,
        rate=50,
        engine="vllm",
        url="http://test",
    )
    return args, calls


@pytest.mark.parametrize("failure", ["generation", "persistence"])
def test_finished_task_failure_stops_admission_and_never_publishes_success(
    workload, monkeypatch, failure
):
    args, calls = workload
    if failure == "generation":

        async def fail(*args, **kwargs):
            raise RuntimeError("injected generation failure")

        monkeypatch.setattr(benchmark, "generate", fail)
    else:

        def fail(*args, **kwargs):
            raise OSError("injected persistence failure")

        monkeypatch.setattr(benchmark.RunLedger, "complete", fail)
    with pytest.raises(ExceptionGroup):
        asyncio.run(benchmark.run(args))
    assert len(calls) <= 1
    rows = load_predictions(args.out / "predictions.jsonl")
    assert [row["attempt"]["state"] for row in rows] == ["dispatched", "pending", "pending"]
    assert not (args.out / "summary.json").exists()
    assert len(json.loads((args.out / "interrupted.json").read_text())["nonterminal_ids"]) == 3


@pytest.mark.parametrize("failure", ["launch", "timeout", "nonfinite", "empty", "exit"])
def test_gpu_probe_failure_prevents_dispatch_and_reaps_child(workload, monkeypatch, failure):
    args, calls = workload
    args.gpu_safety = True

    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            if failure == "timeout":
                raise TimeoutError
            self.returncode = 1 if failure == "exit" else 0
            return ({"nonfinite": b"10,nan,2", "empty": b""}.get(failure, b"10,4096,2"), b"")

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    process = Process()

    async def launch(*args, **kwargs):
        if failure == "launch":
            raise FileNotFoundError("nvidia-smi")
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    with pytest.raises(ExceptionGroup):
        asyncio.run(benchmark.run(args))
    assert not calls and not (args.out / "summary.json").exists()
    assert all(
        row["attempt"]["state"] == "pending"
        for row in load_predictions(args.out / "predictions.jsonl")
    )
    assert "gpu_error" in (args.out / "metrics.jsonl").read_text()
    if failure != "launch":
        assert process.waited
    if failure == "timeout":
        assert process.killed


def test_ledger_snapshots_are_outside_per_request_work(workload, monkeypatch):
    args, calls = workload
    original = benchmark.RunLedger.export
    snapshots = []

    def export(self):
        snapshots.append(len(calls))
        return original(self)

    monkeypatch.setattr(benchmark.RunLedger, "export", export)
    summary = asyncio.run(benchmark.run(args))
    assert summary["valid"] == 3
    assert snapshots == [0, 3]


def test_recursive_output_is_invalid_without_aborting_scoring():
    from unrender.eval.score import score_prediction
    from unrender.serving.validity import assess

    raw = "[" * 1500 + "0" + "]" * 1500
    assert not assess(raw, "stop", True)[0]["accepted"]
    score, _ = score_prediction({"id": "deep", "gt": json.dumps(CHART), "raw": raw}, 0.05)
    assert score["n_correct_points"] == 0
