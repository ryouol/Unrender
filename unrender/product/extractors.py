"""Inference provider boundary.

Replay is a zero-cost, evidence-backed demo. Modal is the production provider
and calls the existing, evaluated ``infer_one`` function.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps

from unrender.product.config import Settings
from unrender.schema.chart_schema import ChartData


class ExtractionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExtractionOutput:
    chart: ChartData
    raw: str
    extractor: str
    model_version: str


class Extractor(Protocol):
    def extract(self, image_bytes: bytes) -> ExtractionOutput: ...


class ReplayExtractor:
    """Serve one saved model result only when the bundled source matches exactly."""

    def __init__(self, static_dir: Path):
        self.source_path = static_dir / "demo" / "budget-quarter.webp"
        self.result_path = static_dir / "demo" / "budget-quarter-result.json"

    def _expected_image(self) -> bytes:
        with Image.open(self.source_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
        image.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def extract(self, image_bytes: bytes) -> ExtractionOutput:
        if not self.source_path.exists() or not self.result_path.exists():
            raise ExtractionError("demo_fixture_missing", "The sample fixture is unavailable")
        expected = hashlib.sha256(self._expected_image()).digest()
        actual = hashlib.sha256(image_bytes).digest()
        if actual != expected:
            raise ExtractionError(
                "provider_not_configured",
                "Live extraction is not configured. Run the saved sample or configure Modal.",
            )
        payload = json.loads(self.result_path.read_text(encoding="utf-8"))
        return ExtractionOutput(
            chart=ChartData.model_validate(payload["result"]),
            raw=payload["raw"],
            extractor="saved-replay",
            model_version=payload["model_version"],
        )


class ModalExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _invoke(self, image_bytes: bytes | None = None) -> Any:
        import modal

        # Includes lazy function lookup, upload, scheduling, and result retrieval.
        async with asyncio.timeout(self.settings.provider_timeout_seconds):
            function = modal.Function.from_name(
                self.settings.modal_app_name,
                self.settings.modal_function_name,
            )
            if image_bytes is None:
                await function.hydrate.aio()
                return callable(getattr(function.remote, "aio", None))
            return await function.remote.aio(
                image_bytes,
                self.settings.modal_model_path,
                self.settings.modal_model_revision,
                self.settings.modal_model_digest,
            )

    def canary_contract(self) -> bool:
        """Resolve the deployed function without invoking billable inference."""
        try:
            valid = asyncio.run(self._invoke())
        except Exception as exc:
            raise ExtractionError(
                "provider_contract_unavailable",
                "The configured Modal application/function contract could not be resolved.",
            ) from exc
        if not valid:
            raise ExtractionError(
                "provider_contract_invalid",
                "The inference provider does not expose the expected async remote contract.",
            )
        return True

    def extract(self, image_bytes: bytes) -> ExtractionOutput:
        try:
            payload = asyncio.run(self._invoke(image_bytes))
        except TimeoutError as exc:
            # A cancelled local await does not prove remote execution was cancelled.
            # The durable worker keeps this dispatched attempt spent and terminal.
            raise ExtractionError(
                "provider_timeout",
                "Extraction exceeded its time limit. The attempt may have used GPU time.",
            ) from exc
        except Exception as exc:
            raise ExtractionError(
                "provider_unavailable",
                "The extraction worker could not reach the configured inference provider.",
            ) from exc
        if not isinstance(payload, dict):
            raise ExtractionError("model_output_invalid", "The model returned an invalid response.")
        expected_release = self.settings.modal_provider_release
        actual_release = str(payload.get("provider_release", "")).casefold()
        if expected_release and not hmac.compare_digest(
            actual_release, expected_release.casefold()
        ):
            raise ExtractionError(
                "provider_release_mismatch",
                "The inference provider release did not match the approved deployment.",
            )
        if not payload.get("json"):
            raise ExtractionError(
                "model_output_invalid",
                "The model response could not be parsed. Review the source and try again.",
            )
        try:
            chart = ChartData.model_validate(payload["json"])
        except ValueError as exc:
            raise ExtractionError(
                "model_output_invalid", "The model returned an unsupported chart structure."
            ) from exc
        model_version = (
            f"{self.settings.modal_model_path}@{self.settings.modal_model_revision}"
            if self.settings.modal_model_revision
            else self.settings.modal_model_path
        )
        if actual_release:
            model_version += f"+provider:{actual_release[:12]}"
        return ExtractionOutput(
            chart=chart,
            raw=str(payload.get("raw", "")),
            extractor="modal",
            model_version=model_version,
        )


def build_extractor(settings: Settings, static_dir: Path) -> Extractor:
    if settings.extractor_backend == "modal":
        return ModalExtractor(settings)
    return ReplayExtractor(static_dir)
