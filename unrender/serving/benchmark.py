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
from dataclasses import asdict
from pathlib import Path

import httpx

from unrender.eval.dataset import load_eval_samples
from unrender.product.extractors import ExtractionError
from unrender.schema.chart_schema import ChartData
from unrender.serving.client import Measurement, generate, request_body
from unrender.serving.release import model_name


def percentile(values: list[float], p: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


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
    rows = []
    active = 0
    stop = asyncio.Event()
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
            if active >= args.concurrency:
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
                        request_id=f"bench-{index}",
                        timeout=args.timeout,
                        measurement=result,
                    )
                    before = time.perf_counter()
                    try:
                        ChartData.model_validate_json(result.raw)
                        row["strict_valid"] = True
                    except ValueError:
                        row["status"] = "model_invalid"
                    result.validation_s = time.perf_counter() - before
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
            row["response_s"] = time.perf_counter() - start - scheduled
            rows.append(row)
            with (args.out / "predictions.jsonl").open("a") as handle:
                handle.write(json.dumps(row) + "\n")
                handle.flush()

        poller = asyncio.create_task(metrics())
        try:
            if args.rate:
                # Open loop: do not hide saturation behind an unbounded semaphore queue.
                tasks = set()
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

                await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        finally:
            stop.set()
            await poller
    elapsed = max(
        row["started_s"] + row["elapsed_s"] + row["prepare_s"] + row["validation_s"] for row in rows
    )
    completed = [r for r in rows if r["status"] == "ok"]
    summary = {
        "requests": len(rows),
        "valid": len(completed),
        "elapsed_s": elapsed,
        "valid_requests_per_s": len(completed) / elapsed if elapsed else 0,
        "failures": len(rows) - len(completed),
        "p95_response_s": percentile([r["response_s"] for r in rows], 0.95),
        "p95_ttft_s": percentile([r["ttft_s"] for r in rows if r["ttft_s"] is not None], 0.95),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
    args = parser.parse_args()
    if (
        not math.isfinite(args.rate)
        or args.rate < 0
        or not 0 < args.timeout <= 1800
        or args.max_tokens <= 0
    ):
        parser.error("Invalid rate, deadline, or token limit")
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
