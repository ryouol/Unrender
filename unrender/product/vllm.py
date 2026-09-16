"""Experimental vLLM adapter. Production promotion requires a real GPU canary."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable

from unrender.product.config import Settings
from unrender.product.extractors import ExtractionError, ExtractionOutput
from unrender.schema.chart_schema import ChartData


class VllmExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, image_bytes: bytes) -> ExtractionOutput:
        return self.extract_with_context(
            image_bytes, request_id=uuid.uuid4().hex, cancelled=lambda: False
        )

    def extract_with_context(
        self, image_bytes: bytes, *, request_id: str, cancelled: Callable[[], bool]
    ) -> ExtractionOutput:
        return asyncio.run(self._extract(image_bytes, request_id, cancelled))

    async def _extract(
        self, image_bytes: bytes, request_id: str, cancelled: Callable[[], bool]
    ) -> ExtractionOutput:
        import httpx

        from unrender.serving.client import generate, request_body

        settings = self.settings
        prepared = time.monotonic()
        body = request_body(image_bytes, settings.vllm_model, settings.vllm_constrained, 4096)
        remaining = settings.vllm_timeout_seconds - (time.monotonic() - prepared)
        if remaining <= 0:
            raise ExtractionError("provider_timeout", "Image preparation exceeded deadline")
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
            timeout=httpx.Timeout(remaining),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            result = await generate(
                client,
                url=settings.vllm_url,
                body=body,
                request_id=request_id,
                timeout=remaining,
                cancelled=cancelled,
                max_bytes=settings.max_result_json_bytes,
            )
        try:
            chart = ChartData.model_validate_json(result.raw)
        except ValueError as exc:
            raise ExtractionError("model_output_invalid", "Invalid chart structure") from exc
        return ExtractionOutput(chart, result.raw, "vllm-experimental", settings.vllm_model)
