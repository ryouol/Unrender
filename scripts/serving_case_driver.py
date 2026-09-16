"""Bounded GPU experiment driver. Every phase commits evidence before continuing."""

import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from argparse import Namespace
from pathlib import Path

import httpx
import modal

from unrender.serving.benchmark import check_split, run
from unrender.serving.release import command, model_name

OUT = Path(sys.argv[1])
SNAPSHOT = Path("/models/releases/3954f3395a9db64fcbd3b9dc94508ab0cf9af2f5f2156643504881ee712e8c7e")
START = time.monotonic()
LIMIT = 2700
MANIFEST = OUT / "manifest.json"
PORT = "http://127.0.0.1:8001"
PROGRESS = {"status": "running", "phases": [], "failures": []}
SERVER = None


def save():
    (OUT / "progress.json").write_text(json.dumps(PROGRESS, indent=2))
    modal.Volume.from_name("unrender-serving-results").commit()


def shell(args, name, timeout=120):
    with (OUT / name).open("w") as handle:
        result = subprocess.run(args, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{name}: exit {result.returncode}")


def stop_server():
    global SERVER
    if SERVER is not None:
        os.killpg(SERVER.pid, signal.SIGTERM)
        try:
            SERVER.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(SERVER.pid, signal.SIGKILL)
            SERVER.wait(timeout=10)
        SERVER = None


def start_server(argv, label):
    global SERVER
    started = time.monotonic()
    SERVER = subprocess.Popen(
        argv,
        stdout=(OUT / f"{label}-server.log").open("w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    while time.monotonic() - started < 420:
        if SERVER.poll() is not None:
            raise RuntimeError(f"{label} failed; inspect server log")
        try:
            response = httpx.get(PORT + "/openapi.json", timeout=2)
            if response.status_code in (200, 404):
                break
        except httpx.HTTPError:
            pass
        time.sleep(2)
    else:
        raise RuntimeError(f"{label} readiness timeout")
    PROGRESS["phases"].append(
        {"phase": label + "-startup", "cold_startup_s": time.monotonic() - started}
    )
    save()


def budget():
    return LIMIT - (time.monotonic() - START)


def bench(label, engine, data, concurrency=1, rate=0, constrained=False, limit=0, final=False):
    if budget() < 120:
        raise TimeoutError("Experiment wall-time budget exhausted")
    args = Namespace(
        engine=engine,
        data=data,
        manifest=MANIFEST,
        out=OUT / label,
        url=PORT,
        concurrency=concurrency,
        rate=rate,
        timeout=min(int(os.getenv("UNRENDER_CASE_REQUEST_TIMEOUT", "180")), budget()),
        max_tokens=4096,
        constrained=constrained,
        final=final,
        gpu_safety=True,
        phase="pilot" if limit else "warm",
        repeat_id=1,
        limit=limit,
    )
    summary = asyncio.run(asyncio.wait_for(run(args), timeout=max(1, budget() - 30)))
    PROGRESS["phases"].append({"phase": label, "summary": summary})
    save()
    return summary


def prepare():
    rows = [
        json.loads(line)
        for line in Path("/research/data/synthetic_v1/val.jsonl").read_text().splitlines()
    ]
    common = set(json.loads(Path("/root/unrender/eval/subsets/common300.json").read_text())["ids"])
    # Deterministic small-chart pilot, stratified by chart family. Never inspect final labels.
    buckets = {}
    for row in rows:
        gt = json.loads(row["messages"][1]["content"])
        count = sum(len(s["points"]) for s in gt["series"])
        source = Path(row["images"][0])
        if source.stem in common or not 3 <= count <= 16:
            continue
        buckets.setdefault(gt["chart_type"], []).append(row)
    selected = [row for key in sorted(buckets) for row in buckets[key][:4]][:28]
    if len(selected) < 12:
        raise ValueError("Insufficient separate tuning charts")
    for row in selected:
        source = Path(row["images"][0])
        row["images"] = [str(Path("/research/data/synthetic_v1/images") / source.name)]
    check_split([Path(r["images"][0]).stem for r in selected], False)
    path = OUT / "tuning.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in selected))
    repeated = []
    images_dir = OUT / "load-images"
    images_dir.mkdir()
    for i in range(210):
        row = json.loads(json.dumps(selected[i % len(selected)]))
        source = Path(row["images"][0])
        dest = images_dir / f"tuning-repeat-{i:04d}-{source.stem}.png"
        dest.write_bytes(source.read_bytes())
        row.setdefault("meta", {})["original_tuning_id"] = source.stem
        row["images"] = [str(dest)]
        repeated.append(row)
    load = OUT / "load.jsonl"
    load.write_text("\n".join(json.dumps(row) for row in repeated))
    return path, load


def failure_drills(tuning, manifest):
    from unrender.serving.client import generate, request_body

    sample = json.loads(tuning.read_text().splitlines()[0])
    body = request_body(Path(sample["images"][0]).read_bytes(), model_name(manifest), False, 4096)

    async def drills():
        evidence = {}
        headers = {"Authorization": "Bearer " + os.environ["UNRENDER_VLLM_API_KEY"]}
        async with httpx.AsyncClient(
            headers=headers, timeout=30, limits=httpx.Limits(max_connections=64)
        ) as client:
            evidence["before_metrics"] = (await client.get(PORT + "/metrics")).text
            tasks = [
                asyncio.create_task(
                    generate(client, url=PORT, body=body, request_id=f"cancel-{i}", timeout=30)
                )
                for i in range(32)
            ]
            await asyncio.sleep(1)
            evidence["during_metrics"] = (await client.get(PORT + "/metrics")).text
            evidence["unfinished_before_cancel"] = sum(not task.done() for task in tasks)
            started = time.monotonic()
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            evidence["client_cancel_s"] = time.monotonic() - started
            evidence["results"] = [type(result).__name__ for result in results]
            evidence["recovery_samples"] = []
            for _ in range(10):
                await asyncio.sleep(1)
                evidence["recovery_samples"].append(
                    {
                        "elapsed_s": time.monotonic() - started,
                        "metrics": (await client.get(PORT + "/metrics")).text,
                    }
                )
            try:
                await generate(client, url=PORT, body=body, request_id="timeout", timeout=0.05)
                evidence["timeout"] = "unexpected_completion"
            except Exception as exc:
                evidence["timeout"] = {
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                }
            for label, malformed in [
                ("invalid_schema", dict(body, structured_outputs={"json": {"type": "not-a-type"}})),
                (
                    "malformed_image",
                    dict(
                        body,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": "data:image/png;base64,YmFk"},
                                    },
                                    {"type": "text", "text": "Extract this chart"},
                                ],
                            }
                        ],
                    ),
                ),
            ]:
                response = await client.post(PORT + "/v1/chat/completions", json=malformed)
                evidence[label] = {
                    "http_status": response.status_code,
                    "body": response.text[:2000],
                }
        return evidence

    evidence = asyncio.run(drills())
    (OUT / "failure-drills.json").write_text(json.dumps(evidence, indent=2))
    PROGRESS["phases"].append({"phase": "failure-drills", "evidence": "failure-drills.json"})
    save()


def main():
    global MANIFEST
    (OUT / "executed_driver.py").write_text(Path(__file__).read_text())
    os.environ["UNRENDER_VLLM_API_KEY"] = uuid.uuid4().hex
    os.environ["VLLM_API_KEY"] = os.environ["UNRENDER_VLLM_API_KEY"]
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["VLLM_USAGE_STATS_DISABLED"] = "1"
    shell(["nvidia-smi", "-q"], "gpu.txt")
    shell(["python", "-m", "pip", "freeze"], "packages.txt")
    shell(
        [
            "python",
            "-m",
            "unrender.serving.release",
            "manifest",
            "--snapshot",
            str(SNAPSHOT),
            "--manifest",
            str(OUT / "manifest.json"),
            "--dtype",
            "bfloat16",
            "--max-num-seqs",
            "1",
            "--gpu-memory-utilization",
            "0.70",
        ],
        "manifest-name.txt",
        180,
    )
    tuning, load = prepare()
    PROGRESS["checkpoint"] = str(SNAPSHOT)
    PROGRESS["tuning_sha256"] = hashlib.sha256(tuning.read_bytes()).hexdigest()
    save()
    # Execute the current production inference function on this same host/environment.
    original_script = r"""import json, time
from pathlib import Path
import production_providers as provider
from unrender.prompts import EXTRACTION_PROMPT
rows = [json.loads(line) for line in Path(DATA).read_text().splitlines()]
with Path(DEST).open("w") as handle:
    for row in rows:
        started = time.perf_counter()
        stages = {}
        raw = provider.hf_vlm_provider(row["images"][0], EXTRACTION_PROMPT, SNAP, timings=stages)
        handle.write(json.dumps({"id": Path(row["images"][0]).stem, "raw": raw,
                                "elapsed_s": time.perf_counter()-started, "stages": stages})+"\n")
        handle.flush()
"""
    original_script = (
        "DATA="
        + repr(str(tuning))
        + "\nDEST="
        + repr(str(OUT / "existing-path.jsonl"))
        + "\nSNAP="
        + repr(str(SNAPSHOT))
        + "\n"
        + original_script
    )
    shell(["python", "-c", original_script], "existing-path.log", min(720, budget()))
    PROGRESS["phases"].append({"phase": "existing-path", "status": "completed"})
    save()
    start_server(
        [
            "python",
            "-m",
            "unrender.serving.transformers_server",
            "--snapshot",
            str(SNAPSHOT),
            "--manifest",
            str(OUT / "manifest.json"),
        ],
        "transformers",
    )
    bench("tf-cold", "transformers", tuning, limit=1)
    baseline = bench("tf-baseline", "transformers", tuning)
    stop_server()
    manifest = json.loads((OUT / "manifest.json").read_text())
    argv = command(manifest, SNAPSHOT)
    start_server(argv, "vllm")
    bench("vllm-cold", "vllm", tuning, limit=1)
    vllm_baseline = bench("vllm-baseline", "vllm", tuning)
    # Pilot saturation first; max_num_seqs=1 intentionally isolates scheduler serialization.
    sweeps = []
    for concurrency in [1, 2, 4, 8, 16]:
        summary = bench(
            f"saturation-c{concurrency}", "vllm", load, concurrency=concurrency, limit=16
        )
        sweeps.append(summary)
        shell(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu", "--format=csv"],
            f"memory-c{concurrency}.csv",
        )
        if summary["failures"]:
            break
    saturation = max(item["valid_requests_per_s"] or 0 for item in sweeps)
    for factor in [0.75, 1.0, 1.25]:
        bench(f"arrival-{factor}", "vllm", load, concurrency=16, rate=saturation * factor, limit=32)
    bench("schema-cold", "vllm", tuning, constrained=True, limit=1)
    bench("schema-warm", "vllm", tuning, concurrency=1, constrained=True)
    # Select the one-factor intervention before looking at reserved final outputs.
    PROGRESS["intervention"] = {
        "parameter": "max_num_seqs",
        "before": 1,
        "after": 16,
        "reason": "Measure whether increased client concurrency is blocked by one running sequence",
        "quality_rule": "At most 1 percentage point absolute cell@5_exact loss; no infra failures",
        "evidence": sweeps,
    }
    save()
    bench("intervention-before", "vllm", load, concurrency=16)
    # Reserve enough time for after-runs and failure drills. Final quality compares the
    # established vLLM baseline to this one scheduler change, with identical model bytes.
    common_path = OUT / "common300-source.jsonl"
    final_rows = [
        json.loads(line)
        for line in Path("/research/data/synthetic_v1/test.jsonl").read_text().splitlines()
    ]
    for row in final_rows:
        row["images"] = [
            str(Path("/research/data/synthetic_v1/images") / Path(row["images"][0]).name)
        ]
    common_path.write_text("\n".join(json.dumps(row) for row in final_rows))
    final_started = False
    # common300 is denser than this pilot. Do not spend the rest of the hour
    # on half of a final comparison at the expense of the intervention evidence.
    projected_final = 4 * vllm_baseline["elapsed_s"] / vllm_baseline["requests"] * 300
    PROGRESS["final_budget_estimate_s"] = projected_final
    if budget() > projected_final + 600:
        bench("final-before", "vllm", common_path, concurrency=16, final=True)
        final_started = True
    stop_server()
    manifest["max_num_seqs"] = 16
    after_manifest = OUT / "manifest-after.json"
    after_manifest.write_text(json.dumps(manifest, indent=2))
    MANIFEST = after_manifest
    start_server(command(manifest, SNAPSHOT), "vllm-after")
    bench("after-warmup", "vllm", tuning, concurrency=16)
    for repeat in [1, 2, 3]:
        if budget() < 180:
            break
        bench(f"intervention-after-{repeat}", "vllm", load, concurrency=16)
    if final_started and budget() > 240:
        bench("final-after", "vllm", common_path, concurrency=16, final=True)
    failure_drills(tuning, manifest)
    PROGRESS["status"] = "pilot_complete"
    PROGRESS["transformers_baseline_s"] = baseline["elapsed_s"]
    save()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        PROGRESS["status"] = "failed"
        PROGRESS["failures"].append({"type": type(exc).__name__, "message": str(exc)})
        save()
        raise
    finally:
        stop_server()
