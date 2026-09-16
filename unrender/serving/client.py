"""One-dispatch streaming transport shared by the product and load client."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image

from unrender.product.extractors import ExtractionError
from unrender.prompts import EXTRACTION_PROMPT
from unrender.schema.chart_schema import ChartData


@dataclass
class Measurement:
    raw: str = ""
    ttft_s: float | None = None
    ttft_event: str | None = None
    elapsed_s: float = 0
    prepare_s: float = 0
    validation_s: float = 0
    usage: dict[str, Any] = field(default_factory=dict)
    server_timings: dict[str, float] = field(default_factory=dict)
    chunks: list[dict[str, Any]] = field(default_factory=list)


def request_body(image: bytes, model: str, constrained: bool, max_tokens: int) -> dict:
    try:
        with Image.open(io.BytesIO(image)) as opened:
            if opened.format != "PNG":
                raise ValueError("Provider input must be normalized PNG")
            opened.verify()
    except Exception as exc:
        raise ExtractionError("source_invalid", "Provider input is not a valid PNG") from exc
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image).decode("ascii")
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
        "temperature": 0,
        "seed": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if constrained:
        body["structured_outputs"] = {"json": ChartData.model_json_schema()}
    return body


async def generate(
    client: httpx.AsyncClient,
    *,
    url: str,
    body: dict,
    request_id: str,
    timeout: float,
    cancelled: Callable[[], bool] = lambda: False,
    max_bytes: int = 1_000_000,
    on_token: Callable[[str], None] | None = None,
    measurement: Measurement | None = None,
) -> Measurement:
    """Never retry, including ambiguous connection loss after dispatch.

    Closing the stream requests engine cancellation; engine-side abort must be
    verified from running-request metrics on the target release, not assumed.
    """
    result = measurement if measurement is not None else Measurement()
    start = time.perf_counter()

    async def receive() -> None:
        raw_size = 0
        wire_size = 0
        finish = None
        done = False
        async with client.stream(
            "POST",
            url.rstrip("/") + "/v1/chat/completions",
            json=body,
            headers={"X-Request-Id": request_id},
        ) as response:
            response.raise_for_status()
            # Parse bounded byte frames: aiter_lines alone can buffer an unbounded line.
            buffer = b""
            async for chunk in response.aiter_bytes():
                wire_size += len(chunk)
                if wire_size > max_bytes * 8:
                    raise ExtractionError("provider_protocol", "Provider stream exceeds limit")
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        done = True
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        raise ExtractionError("provider_unavailable", "Provider stream failed")
                    if event.get("model") != body["model"]:
                        raise ExtractionError(
                            "provider_release_mismatch", "Unexpected served model"
                        )
                    ids = event.get("token_ids", [])
                    if ids:
                        if not isinstance(ids, list) or any(
                            type(i) is not int or i < 0 for i in ids
                        ):
                            raise ValueError("Invalid token event")
                        elapsed = time.perf_counter() - start
                        if result.ttft_s is None:
                            result.ttft_s = elapsed
                            result.ttft_event = "token_ids"
                        result.chunks.append({"elapsed_s": elapsed, "token_ids": ids, "bytes": 0})
                    if event.get("unrender_timings"):
                        result.server_timings = event["unrender_timings"]
                    if event.get("usage"):
                        result.usage = event["usage"]
                    for choice in event.get("choices", []):
                        if choice.get("index", 0) != 0:
                            raise ValueError("Unexpected choice")
                        finish = choice.get("finish_reason") or finish
                        token = choice.get("delta", {}).get("content") or ""
                        if token:
                            raw_size += len(token.encode("utf-8"))
                            if raw_size > max_bytes:
                                raise ExtractionError(
                                    "model_output_invalid", "Output exceeds limit"
                                )
                            elapsed = time.perf_counter() - start
                            if result.ttft_s is None:
                                result.ttft_s = elapsed
                                result.ttft_event = "content_delta"
                            result.raw += token
                            result.chunks.append(
                                {"elapsed_s": elapsed, "bytes": len(token.encode())}
                            )
                            if on_token:
                                on_token(token)
                if done:
                    break
                if len(buffer) > max_bytes:
                    raise ValueError("Oversized SSE frame")
            if not done or finish != "stop":
                raise ExtractionError("model_output_invalid", "Incomplete or truncated generation")

    task = None
    try:
        if cancelled():
            raise ExtractionError("provider_cancelled", "Extraction was cancelled")
        async with asyncio.timeout(timeout):
            task = asyncio.create_task(receive())
            while not task.done():
                if cancelled():
                    raise ExtractionError("provider_cancelled", "Extraction was cancelled")
                await asyncio.wait({task}, timeout=0.1)
            await task
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ExtractionError(
            "provider_timeout", "Extraction deadline exceeded; not retried"
        ) from exc
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ExtractionError(
            "provider_unavailable", "Provider request failed; not retried"
        ) from exc
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        result.elapsed_s = time.perf_counter() - start
    return result
