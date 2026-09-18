"""Bounded, immutable evidence about an extraction, never an accuracy guarantee."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_RECEIPT_BYTES = 8192
ExtractionOrigin = Literal["model", "reference_fixture", "unavailable"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(max_length=500)]
TokenCount = Annotated[int, Field(gt=0, le=10_000_000)]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, allow_inf_nan=False, revalidate_instances="always"
    )


class ExtractionDiagnostics(EvidenceModel):
    parser_version: ShortText | None = None
    parse_status: Literal["raw_valid", "syntax_repaired", "unavailable"] = "unavailable"
    finish_reason: Literal["eos", "unavailable"] = "unavailable"
    output_tokens: TokenCount | None = None
    max_output_tokens: TokenCount | None = None
    provider_release: Digest | None = None
    model_repository: ShortText | None = None
    model_revision: ShortText | None = None
    model_digest: Digest | None = None
    prompt_sha256: Digest | None = None
    schema_sha256: Digest | None = None

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        if (self.parse_status == "unavailable") != (self.parser_version is None):
            raise ValueError("Parsing evidence requires a parser identity")
        if self.finish_reason == "eos":
            if not (
                self.output_tokens is not None
                and self.max_output_tokens is not None
                and self.output_tokens < self.max_output_tokens
            ):
                raise ValueError("Completion evidence requires observed token counts below the cap")
        elif self.output_tokens is not None or self.max_output_tokens is not None:
            raise ValueError("Unverified completion cannot claim token counts")
        return self


class Crop(EvidenceModel):
    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]
    width: Annotated[float, Field(gt=0, le=1)]
    height: Annotated[float, Field(gt=0, le=1)]


class ExtractionReceipt(EvidenceModel):
    contract: Literal["extraction-receipt-v1"] = "extraction-receipt-v1"
    capture: Literal["recorded", "historical_unavailable"] = "historical_unavailable"
    origin: ExtractionOrigin = "unavailable"
    attempt: Annotated[int, Field(ge=1)] | None = None
    execution_generation: Annotated[int, Field(ge=1)] | None = None
    provider_roundtrip_ms: Annotated[int, Field(ge=0)] | None = None
    captured_at: ShortText | None = None
    extractor: ShortText | None = None
    model_version: ShortText | None = None
    source_sha256: Digest | None = None
    provider_input_sha256: Digest | None = None
    page_index: Annotated[int, Field(ge=0)] | None = None
    crop: Crop | None = None
    raw_sha256: Digest | None = None
    raw_byte_count: Annotated[int, Field(ge=0)] | None = None
    stored_raw_sha256: Digest | None = None
    raw_truncated: bool | None = None
    diagnostics: ExtractionDiagnostics = Field(default_factory=ExtractionDiagnostics)

    @model_validator(mode="after")
    def check_capture(self) -> Self:
        evidence = (
            self.attempt,
            self.execution_generation,
            self.provider_roundtrip_ms,
            self.captured_at,
            self.extractor,
            self.model_version,
            self.source_sha256,
            self.provider_input_sha256,
            self.page_index,
            self.raw_sha256,
            self.raw_byte_count,
            self.stored_raw_sha256,
            self.raw_truncated,
        )
        if self.capture == "recorded":
            if any(value is None for value in evidence):
                raise ValueError("A recorded extraction requires complete capture evidence")
            if not self.raw_truncated and self.raw_sha256 != self.stored_raw_sha256:
                raise ValueError("An unshortened response must retain its full hash")
        elif (
            any(value is not None for value in evidence)
            or self.crop is not None
            or self.origin != "unavailable"
            or (self.diagnostics != ExtractionDiagnostics())
        ):
            raise ValueError("Missing historical evidence cannot claim recorded details")
        return self

    def encode(self) -> str:
        encoded = self.model_dump_json()
        if len(encoded.encode("utf-8")) > MAX_RECEIPT_BYTES:
            raise ValueError("Extraction receipt exceeds its storage limit")
        return encoded


def sha256(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def receipt_warnings(receipt: ExtractionReceipt) -> list[str]:
    if receipt.capture == "historical_unavailable":
        return ["Extraction details were not recorded for this historical result."]
    warnings = []
    if receipt.origin == "reference_fixture":
        warnings.append("This example uses saved reference data. No live model inference was run.")
        if receipt.raw_truncated:
            warnings.append("The retained raw response was shortened to fit the storage limit.")
        return warnings
    if receipt.diagnostics.parse_status == "syntax_repaired":
        warnings.append(
            "Model output needed formatting repair. No values were filled in or dropped."
        )
    elif receipt.diagnostics.parse_status == "unavailable":
        warnings.append("Original parsing details are unavailable for this saved result.")
    if receipt.diagnostics.finish_reason == "unavailable":
        warnings.append("The original model completion was not verified.")
    if receipt.raw_truncated:
        warnings.append("The retained raw response was shortened to fit the storage limit.")
    return warnings


UNAVAILABLE_RECEIPT_JSON = ExtractionReceipt().encode()
