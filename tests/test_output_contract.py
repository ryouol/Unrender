"""Provider claims cannot turn incomplete or rewritten data into a product table."""

import copy
import json

import pytest
from test_product import _paid_job, customer_id, service_for, settings_for

from unrender.eval.providers import generation_finish_reason
from unrender.product.extractors import ExtractionError, ModalExtractor
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import PARSER_VERSION, parse_chart_json


def response(**changes):
    raw = ChartData.model_validate(
        {"chart_type": "bar", "series": [{"points": [{"x": "A", "y": 5}]}]}
    ).model_dump_json()
    return {
        "raw": raw,
        "json": json.loads(raw),
        "parse_errors": [],
        "parser_version": PARSER_VERSION,
        "finish_reason": "eos",
        "output_tokens": 100,
        "max_output_tokens": 4096,
        **changes,
    }


def install(extractor, monkeypatch, payload):
    async def invoke(*args):
        return copy.deepcopy(payload)

    monkeypatch.setattr(extractor, "_invoke", invoke)


@pytest.mark.parametrize(
    "tokens,eos,cap,expected",
    [
        ([1, 7], 7, 10, "eos"),
        ([1, 8], [7, 8], 10, "eos"),
        ([1, 2], 7, 2, "length"),
        ([1, 7], 7, 2, "length"),
        ([1, 2], 7, 10, "unknown"),
        ([], 7, 10, "unknown"),
        ([1], None, 10, "unknown"),
    ],
)
def test_generation_stop_is_observed_not_guessed(tokens, eos, cap, expected):
    assert generation_finish_reason(tokens, eos, cap) == expected


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"finish_reason": "length"}, "model_output_truncated"),
        ({"finish_reason": "unknown"}, "model_completion_unverified"),
        ({"finish_reason": None}, "model_completion_unverified"),
        ({"output_tokens": 4096}, "model_completion_unverified"),
        ({"output_tokens": True}, "model_completion_unverified"),
        ({"output_tokens": 0}, "model_completion_unverified"),
        ({"parser_version": "old"}, "provider_contract_mismatch"),
        ({"max_output_tokens": 10_000_001}, "provider_contract_mismatch"),
        ({"provider_release": "invalid"}, "provider_contract_mismatch"),
        (
            {"raw": '{"chart_type":"bar","series":[{"points":[{"x":"A","y":1e'},
            "model_output_invalid",
        ),
        ({"raw": None}, "model_output_invalid"),
        ({"parse_errors": ["arbitrary remote diagnostic"]}, "provider_contract_mismatch"),
    ],
)
def test_provider_does_not_trust_a_valid_json_claim(tmp_path, monkeypatch, changes, code):
    extractor = ModalExtractor(settings_for(tmp_path))
    install(extractor, monkeypatch, response(**changes))
    with pytest.raises(ExtractionError) as caught:
        extractor.extract(b"image")
    assert caught.value.code == code


def test_provider_rejects_a_rewritten_raw_value(tmp_path, monkeypatch):
    extractor = ModalExtractor(settings_for(tmp_path))
    payload = response()
    payload["json"]["series"][0]["points"][0]["y"] = 123456
    install(extractor, monkeypatch, payload)
    with pytest.raises(ExtractionError) as caught:
        extractor.extract(b"image")
    assert caught.value.code == "provider_contract_mismatch"


def test_safe_syntax_recovery_requires_matching_remote_diagnostics(tmp_path, monkeypatch):
    extractor = ModalExtractor(settings_for(tmp_path))
    payload = response()
    payload["raw"] = "```json\n" + payload["raw"] + "\n```"
    install(extractor, monkeypatch, payload)
    with pytest.raises(ExtractionError) as caught:
        extractor.extract(b"image")
    assert caught.value.code == "provider_contract_mismatch"
    payload["parse_errors"] = parse_chart_json(payload["raw"])[1]
    install(extractor, monkeypatch, payload)
    assert extractor.extract(b"image").chart.model_dump() == payload["json"]


def test_token_cap_failure_is_persisted_without_a_partial_result_or_retry(tmp_path, monkeypatch):
    service = service_for(tmp_path)
    uid = customer_id(service)
    job = _paid_job(service, uid)
    extractor = ModalExtractor(service.settings)
    calls = []

    async def invoke(*args):
        calls.append(args)
        return response(finish_reason="length", output_tokens=4096)

    monkeypatch.setattr(extractor, "_invoke", invoke)
    service.extractor = extractor
    assert service.process_one()
    result = service.get_job(user_id=uid, job_id=job["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "model_output_truncated"
    assert "No partial table" in result["error"]["message"]
    assert result["result"] is None
    assert result["result_version"] is None
    assert service.job_versions(user_id=uid, job_id=job["id"])["items"] == []
    assert not service.process_one()
    assert len(calls) == 1
    assert service.account(uid)["credits"] == 2  # A dispatched attempt was consumed.
