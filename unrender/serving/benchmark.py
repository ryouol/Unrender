"""Bounded streaming load driver. Saves every attempt, including transport failures."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import httpx

from unrender.eval.dataset import load_eval_samples
from unrender.product.extractors import ExtractionError
from unrender.schema.chart_schema import ChartData
from unrender.serving.client import Measurement, generate, request_body
from unrender.serving.release import model_name
from unrender.serving.report import summarize


def check_split(ids: list[str], final: bool) -> None:
    frozen = json.loads((Path(__file__).parents[1] / "eval/subsets/common300.json").read_text())
    common = set(frozen["ids"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate sample IDs")
    if final and set(ids) != common:
        raise ValueError("Final evaluation requires exactly common300, with full coverage")
    if not final and common.intersection(ids):
        raise ValueError("Tuning workload overlaps reserved common300")


async def run(args: argparse.Namespace) -> dict:
    manifest = json.loads(args.manifest.read_text())
    samples = load_eval_samples(str(args.data))
    if args.final:
        common = json.loads((Path(__file__).parents[1] / "eval/subsets/common300.json").read_text())
        samples = [s for s in samples if s.id in set(common["ids"])]
    check_split([s.id for s in samples], args.final)
    limit = getattr(args, "limit", 0)
    if args.final and limit:
        raise ValueError("Final evaluation cannot be limited")
    if limit:
        samples = samples[:limit]
    if not samples:
        raise ValueError("Empty workload")
    # Validate/read before sending anything; include image bytes and GT in workload identity.
    images = [Path(s.image).read_bytes() for s in samples]
    for data in images:
        request_body(data, model_name(manifest), args.constrained, args.max_tokens)
    workload = hashlib.sha256()
    for sample, data in zip(samples, images, strict=True):
        workload.update(json.dumps([sample.id, sample.gt_json], separators=(",", ":")).encode())
        workload.update(hashlib.sha256(data).digest())
    args.out.mkdir(parents=True, exist_ok=False)
    metadata = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    metadata.update(
        manifest=manifest,
        workload_sha256=workload.hexdigest(),
        timing_note="Client TTFT includes transport, queue, processor and prefill; not GPU-only.",
        cold_start_note="No automatic warmup; warm the same workload separately and record it.",
    )
    (args.out / "run.json").write_text(json.dumps(metadata, indent=2))
    run_id = uuid.uuid4().hex
    rows = []
    active = 0
    stop = asyncio.Event()
    unsafe = asyncio.Event()
    start = time.perf_counter()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + os.environ["UNRENDER_VLLM_API_KEY"]},
        timeout=args.timeout,
        trust_env=False,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=args.concurrency + 2),
    ) as client:

        async def metrics() -> None:
            with (args.out / "metrics.jsonl").open("x") as handle:
                while not stop.is_set():
                    try:
                        response = await client.get(args.url.rstrip("/") + "/metrics", timeout=5)
                        response.raise_for_status()
                        record = {
                            "elapsed_s": time.perf_counter() - start,
                            "prometheus": response.text,
                        }
                    except httpx.HTTPError as exc:
                        record = {
                            "elapsed_s": time.perf_counter() - start,
                            "error": type(exc).__name__,
                        }
                    if getattr(args, "gpu_safety", False):
                        process = await asyncio.create_subprocess_exec(
                            "nvidia-smi",
                            "--query-gpu=memory.used,memory.free,utilization.gpu",
                            "--format=csv,noheader,nounits",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
                        record["gpu_csv"] = stdout.decode().strip()
                        try:
                            free = [
                                float(line.split(",")[1]) for line in stdout.decode().splitlines()
                            ]
                            if process.returncode or not free or min(free) < 2048:
                                unsafe.set()
                        except (ValueError, IndexError):
                            unsafe.set()
                    handle.write(json.dumps(record) + "\n")
                    handle.flush()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), timeout=1)

        async def one(index: int, scheduled: float) -> None:
            nonlocal active
            sample = samples[index]
            result = Measurement()
            row = {
                "id": sample.id,
                "gt": sample.gt_json,
                "meta": sample.meta,
                "scheduled_s": scheduled,
                "started_s": time.perf_counter() - start,
                "status": "ok",
                "error": None,
                "strict_valid": False,
            }
            interrupted = False
            if unsafe.is_set():
                row.update(status="infra_error", error="gpu_safety_stopped")
            elif active >= args.concurrency:
                row.update(status="infra_error", error="client_admission_rejected")
            else:
                active += 1
                try:
                    before = time.perf_counter()
                    body = request_body(
                        images[index], model_name(manifest), args.constrained, args.max_tokens
                    )
                    result.prepare_s = time.perf_counter() - before
                    await generate(
                        client,
                        url=args.url,
                        body=body,
                        request_id=f"{run_id}:{index}",
                        timeout=args.timeout,
                        measurement=result,
                        cancelled=unsafe.is_set,
                    )
                    before = time.perf_counter()
                    try:
                        ChartData.model_validate_json(result.raw)
                        row["strict_valid"] = True
                    except ValueError:
                        row["status"] = "model_invalid"
                    result.validation_s = time.perf_counter() - before
                except asyncio.CancelledError:
                    interrupted = True
                    row.update(status="infra_error", error="benchmark_cancelled")
                except ExtractionError as exc:
                    row.update(
                        status="model_invalid"
                        if exc.code == "model_output_invalid"
                        else "infra_error",
                        error=exc.code,
                    )
                finally:
                    active -= 1
            row.update(asdict(result))
            row["finished_s"] = time.perf_counter() - start
            row["response_s"] = row["finished_s"] - scheduled
            rows.append(row)
            with (args.out / "predictions.jsonl").open("a") as handle:
                handle.write(json.dumps(row) + "\n")
                handle.flush()
            if interrupted:
                raise asyncio.CancelledError

        poller = asyncio.create_task(metrics())
        tasks = set()
        completed = False
        try:
            if args.rate:
                # Open loop: do not hide saturation behind an unbounded semaphore queue.
                for i in range(len(samples)):
                    scheduled = i / args.rate
                    await asyncio.sleep(max(0, start + scheduled - time.perf_counter()))
                    task = asyncio.create_task(one(i, scheduled))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                    await asyncio.sleep(0)
                await asyncio.gather(*tasks)
            else:
                queue = asyncio.Queue()
                for i in range(len(samples)):
                    queue.put_nowait(i)

                async def worker() -> None:
                    while not queue.empty():
                        await one(queue.get_nowait(), time.perf_counter() - start)

                tasks = {asyncio.create_task(worker()) for _ in range(args.concurrency)}
                await asyncio.gather(*tasks)
            completed = True
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            stop.set()
            await poller
            if not completed:
                recorded = {row["id"] for row in rows}
                (args.out / "interrupted.json").write_text(
                    json.dumps(
                        {
                            "status": "interrupted",
                            "expected": len(samples),
                            "recorded": len(rows),
                            "unrecorded_ids": [
                                sample.id for sample in samples if sample.id not in recorded
                            ],
                            "note": "Unrecorded inputs are not successes or completed attempts.",
                        },
                        indent=2,
                    )
                )
    elapsed = max(row["finished_s"] for row in rows)
    summary = summarize(rows, elapsed)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-safety", action="store_true")
    parser.add_argument("--engine", choices=["vllm", "transformers"], required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4, 8, 16], default=1)
    parser.add_argument("--rate", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--constrained", action="store_true")
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Pilot size; tuning only")
    parser.add_argument("--phase", choices=["pilot", "warm", "cold-schema"], default="pilot")
    parser.add_argument("--repeat-id", type=int, default=1)
    args = parser.parse_args()
    if (
        not math.isfinite(args.rate)
        or args.rate < 0
        or not 0 < args.timeout <= 1800
        or args.max_tokens <= 0
        or args.limit < 0
        or args.repeat_id < 1
    ):
        parser.error("Invalid rate, deadline, or token limit")
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
