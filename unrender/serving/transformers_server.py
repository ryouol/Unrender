"""Serial Transformers reference server for the same streaming benchmark workload.

Use the same GPU environment/snapshot/dtype as vLLM, one engine at a time.
This intentionally does not implement batching or a custom runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import cProfile
import io
import json
import os
import queue
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from PIL import Image

from unrender.serving.release import inventory, model_name


def create_app(snapshot: Path, manifest: dict, profile_dir: Path | None) -> FastAPI:
    import torch
    from transformers import (
        AutoModelForImageTextToText,
        AutoProcessor,
        StoppingCriteria,
        StoppingCriteriaList,
        TextIteratorStreamer,
    )

    if inventory(snapshot) != manifest["files"]:
        raise ValueError("Snapshot identity mismatch")
    key = os.environ["UNRENDER_VLLM_API_KEY"]
    processor = AutoProcessor.from_pretrained(snapshot, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        snapshot,
        torch_dtype=getattr(torch, manifest["dtype"]),
        device_map="cuda:0",
        local_files_only=True,
    ).eval()
    gpu_lock = threading.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        import hmac

        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + key):
            raise HTTPException(401)
        body = await request.json()
        if (
            body.get("model") != model_name(manifest)
            or body.get("temperature") != 0
            or not body.get("stream")
            or body.get("structured_outputs")
        ):
            raise HTTPException(
                400, "Reference baseline requires matching, greedy, unconstrained streaming"
            )
        try:
            content = body["messages"][0]["content"]
            url = content[0]["image_url"]["url"]
            prompt = content[1]["text"]
            if not url.startswith("data:image/png;base64,"):
                raise ValueError("PNG required")
            data = base64.b64decode(url.split(",", 1)[1], validate=True)
            image = Image.open(io.BytesIO(data)).convert("RGB")
            cap = int(body["max_tokens"])
            if not 0 < cap <= 4096:
                raise ValueError("Invalid token cap")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(400, "Malformed request") from exc
        stop = threading.Event()
        done = threading.Event()
        errors = []
        timings = {}
        finish_reason = ["length"]
        streamer = TextIteratorStreamer(
            processor.tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=0.1
        )

        class Cancel(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return stop.is_set()

        def produce():
            acquired = False
            started = time.perf_counter()
            try:
                while not stop.is_set():
                    acquired = gpu_lock.acquire(timeout=0.1)
                    if acquired:
                        break
                if not acquired or stop.is_set():
                    return
                timings["queue_s"] = time.perf_counter() - started
                profile = cProfile.Profile()
                before = time.perf_counter()
                if profile_dir is not None:
                    profile.enable()
                messages = [
                    {
                        "role": "user",
                        "content": [{"type": "image"}, {"type": "text", "text": prompt}],
                    }
                ]
                text = processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                inputs = processor(text=[text], images=[image], return_tensors="pt").to(
                    model.device
                )
                torch.cuda.synchronize()
                if profile_dir is not None:
                    profile.disable()
                    profile.dump_stats(str(profile_dir / f"prepare-{time.time_ns()}.prof"))
                timings["prepare_and_transfer_s"] = time.perf_counter() - before
                if inputs["input_ids"].shape[1] + cap > manifest["max_model_len"]:
                    raise ValueError("Request exceeds shared context limit")
                before = time.perf_counter()
                with torch.inference_mode():
                    output = model.generate(
                        **inputs,
                        max_new_tokens=cap,
                        do_sample=False,
                        streamer=streamer,
                        stopping_criteria=StoppingCriteriaList([Cancel()]),
                    )
                eos = model.generation_config.eos_token_id
                eos_ids = eos if isinstance(eos, list) else [eos]
                if int(output[0, -1]) in eos_ids:
                    finish_reason[0] = "stop"
                torch.cuda.synchronize()
                timings["inference_s"] = time.perf_counter() - before
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                if acquired:
                    gpu_lock.release()
                done.set()

        thread = threading.Thread(target=produce, daemon=True)
        thread.start()

        async def stream():
            def frame(content="", finish=None):
                return (
                    "data: "
                    + json.dumps(
                        {
                            "model": model_name(manifest),
                            "choices": [
                                {"index": 0, "delta": {"content": content}, "finish_reason": finish}
                            ],
                            "unrender_timings": timings if finish else {},
                        }
                    )
                    + "\n\n"
                )

            # Read the streamer's queue directly so its sentinel never escapes a Future.
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        chunk = await asyncio.to_thread(streamer.text_queue.get, True, 0.1)
                    except queue.Empty:
                        if done.is_set():
                            break
                        continue
                    if chunk == streamer.stop_signal:
                        break
                    yield frame(chunk)
                while not done.is_set():
                    await asyncio.sleep(0.01)
                if errors:
                    yield "data: " + json.dumps({"error": {"type": errors[0]}}) + "\n\n"
                else:
                    # Final ChartData validity is measured by the shared client.
                    yield frame(finish=finish_reason[0])
                    yield "data: [DONE]\n\n"
            finally:
                stop.set()
                # Keep GPU lock until generation actually stops, even on disconnect.

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profiles", type=Path)
    args = parser.parse_args()
    app = create_app(args.snapshot, json.loads(args.manifest.read_text()), args.profiles)
    uvicorn.run(app, host="127.0.0.1", port=8001, workers=1)


if __name__ == "__main__":
    main()
