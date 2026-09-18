"""Diagnostics belong to the reviewed version, not the last worker or audit event."""

from __future__ import annotations

import copy
import csv
import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from test_output_contract import install, response
from test_product import _paid_job, customer_id, service_for
from test_review_integrity import sample, save

from unrender.product.extractors import ExtractionOutput, ModalExtractor
from unrender.product.provenance import (
    MAX_RECEIPT_BYTES,
    ExtractionDiagnostics,
    ExtractionReceipt,
    sha256,
)
from unrender.product.service import ProductError
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import PARSER_VERSION, parse_chart_json


def recorded_job(tmp_path, monkeypatch, *, repaired=True):
    service = service_for(tmp_path, seed_demo_account=False, initial_credits=4)
    uid = customer_id(service, "evidence@example.com")
    queued = _paid_job(service, uid, color="blue")
    payload = response(provider_release="a" * 64)
    if repaired:
        payload["raw"] = "```json\n" + payload["raw"] + "\n```"
        payload["parse_errors"] = parse_chart_json(payload["raw"])[1]
    service.extractor = ModalExtractor(service.settings)
    install(service.extractor, monkeypatch, payload)
    assert service.process_one()
    return service, uid, service.get_job(user_id=uid, job_id=queued["id"]), payload


def test_recorded_evidence_matches_input_raw_response_and_parser(tmp_path, monkeypatch):
    service, uid, job, payload = recorded_job(tmp_path, monkeypatch)
    receipt = job["extraction_receipt"]
    assert job["status"] == "review"
    assert receipt["capture"] == "recorded"
    assert receipt["attempt"] == 1
    assert receipt["execution_generation"] == 1
    assert receipt["provider_roundtrip_ms"] >= 0
    assert receipt["captured_at"].endswith("Z")
    assert receipt["raw_sha256"] == sha256(payload["raw"])
    assert receipt["stored_raw_sha256"] == receipt["raw_sha256"]
    assert receipt["raw_byte_count"] == len(payload["raw"].encode())
    assert receipt["raw_truncated"] is False
    assert receipt["provider_input_sha256"] == sha256(
        service.job_source(user_id=uid, job_id=job["id"])
    )
    assert receipt["diagnostics"]["parse_status"] == "syntax_repaired"
    assert receipt["diagnostics"]["parser_version"] == PARSER_VERSION
    assert receipt["diagnostics"]["finish_reason"] == "eos"
    assert receipt["diagnostics"]["output_tokens"] == 100
    assert receipt["diagnostics"]["provider_release"] == "a" * 64
    assert len(receipt["diagnostics"]["prompt_sha256"]) == 64
    assert "formatting repair" in " ".join(job["extraction_warnings"])
    saved = service.job_version(user_id=uid, job_id=job["id"], version=1)
    assert saved["extraction_receipt"] == receipt
    with service.database.connect() as conn:
        stored = conn.execute("SELECT extraction_receipt_json FROM result_versions").fetchone()[0]
        assert sha256(stored) == job["extraction_receipt_sha256"]
        source = conn.execute("SELECT source_sha256 FROM jobs").fetchone()[0]
        assert receipt["source_sha256"] == source


def test_correction_restore_and_failed_reprocess_keep_the_right_evidence(tmp_path, monkeypatch):
    service, uid, original, _ = recorded_job(tmp_path, monkeypatch)
    corrected = save(service, uid, original, 12)
    assert corrected["extraction_receipt"] == original["extraction_receipt"]
    assert corrected["extraction_warnings"] == original["extraction_warnings"]
    service.reprocess(user_id=uid, job_id=original["id"])
    install(service.extractor, monkeypatch, response(provider_release="b" * 64))
    assert service.process_one()
    regenerated = service.get_job(user_id=uid, job_id=original["id"])
    assert regenerated["extraction_receipt"]["diagnostics"]["provider_release"] == "b" * 64
    assert regenerated["extraction_warnings"] == []
    restored = service.restore_version(
        user_id=uid,
        job_id=original["id"],
        version=1,
        expected_revision=regenerated["review_revision"],
    )
    assert restored["result_version"] == 4
    assert restored["extraction_receipt"] == original["extraction_receipt"]
    assert restored["model_version"] == original["model_version"]
    assert restored["model_version"] != regenerated["model_version"]
    approved = service.approve(
        user_id=uid,
        job_id=original["id"],
        expected_revision=restored["review_revision"],
    )
    service.reprocess(user_id=uid, job_id=original["id"])
    install(service.extractor, monkeypatch, response(finish_reason="length"))
    assert service.process_one()
    failed = service.get_job(user_id=uid, job_id=original["id"])
    assert failed["status"] == "approved"
    assert failed["extraction_receipt"] == original["extraction_receipt"]
    assert failed["approved_at"] == approved["approved_at"]
    assert failed["error"]["code"] == "model_output_truncated"


def export_manifest(service, uid, job, format):
    payload, _ = service.export(
        user_id=uid,
        job_id=job["id"],
        output_format=format,
        expected_revision=job["review_revision"],
    )
    if format == "json":
        return json.loads(payload)["provenance"]
    if format == "csv":
        rows = list(csv.reader(io.StringIO(payload.decode())))
        assert rows[0][-1] == "export_metadata_json"
        assert "USD millions / %" in rows[0][1]
        assert all(len(row) == len(rows[0]) for row in rows)
        manifests = [row[-1] for row in rows[1:] if row[-1]]
        assert len(manifests) == 1
        assert float(rows[1][1]) == job["result"]["series"][0]["points"][0]["y"]
        return json.loads(manifests[0])
    workbook = load_workbook(io.BytesIO(payload))
    audit = dict(list(workbook["Audit"].values)[1:])
    assert audit["Model"] == job["model_version"]
    assert audit["Value unit"] == job["result"]["y_axis"]["unit"]
    assert "USD millions / %" in workbook["Extracted data"]["B1"].value
    assert workbook["Extracted data"]["B2"].value == 12.5
    return json.loads(audit["Export metadata JSON"])


def test_every_export_carries_identical_review_and_units_without_rescaling(tmp_path, monkeypatch):
    service, uid, job, _ = recorded_job(tmp_path, monkeypatch)
    result = copy.deepcopy(job["result"])
    result["series"][0]["points"][0]["y"] = 12.5
    result["x_axis"]["unit"] = "years"
    result["y_axis"]["unit"] = "USD millions / %"
    corrected = service.save_correction(
        user_id=uid,
        job_id=job["id"],
        result=result,
        expected_revision=job["review_revision"],
    )
    approved = service.approve(
        user_id=uid,
        job_id=job["id"],
        expected_revision=corrected["review_revision"],
    )
    manifests = [export_manifest(service, uid, approved, fmt) for fmt in ("json", "csv", "xlsx")]
    assert manifests[0] == manifests[1] == manifests[2]
    manifest = manifests[0]
    assert manifest["contract"] == "unrender-export-v1"
    assert manifest["result_sha256"] == approved["result_sha256"]
    assert manifest["review_revision"] == approved["review_revision"]
    assert manifest["result_version"] == 2
    assert manifest["status"] == "approved"
    assert manifest["axes"]["x"]["unit"] == "years"
    assert manifest["axes"]["y"]["unit"] == "USD millions / %"
    assert manifest["values_rescaled_on_export"] is False
    assert manifest["extraction_receipt"] == job["extraction_receipt"]
    assert manifest["extraction_warnings"] == job["extraction_warnings"]
    assert manifest["source"]["sha256"] == job["extraction_receipt"]["source_sha256"]
    assert manifest["source"]["page_index"] == 0
    assert manifest["source"]["crop"] is None


def test_receipt_is_counted_in_correction_history_capacity(tmp_path, monkeypatch):
    service, uid, job, _ = recorded_job(tmp_path, monkeypatch)
    with service.database.connect() as conn:
        row = conn.execute(
            "SELECT chart_json,extraction_receipt_json FROM result_versions"
        ).fetchone()
    chart_bytes = len(row["chart_json"].encode())
    used = chart_bytes + len(row["extraction_receipt_json"].encode())
    # Enough for the second chart alone, but not its preserved evidence.
    service.settings = replace(service.settings, max_history_bytes_per_user=used + chart_bytes)
    with pytest.raises(ProductError) as caught:
        service.save_correction(
            user_id=uid,
            job_id=job["id"],
            result=job["result"],
            expected_revision=job["review_revision"],
        )
    assert caught.value.code == "history_storage_quota_reached"
    assert service.get_job(user_id=uid, job_id=job["id"])["result_version"] == 1


def test_changed_receipt_invalidates_an_old_approval_request(tmp_path, monkeypatch):
    service, uid, job, _ = recorded_job(tmp_path, monkeypatch)
    with service.database.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE result_versions SET extraction_receipt_json=?",
            (ExtractionReceipt().encode(),),
        )
    with pytest.raises(ProductError) as caught:
        service.approve(user_id=uid, job_id=job["id"], expected_revision=job["review_revision"])
    assert caught.value.code == "result_conflict"


@pytest.mark.parametrize("crash_statement", [1, 2])
def test_v14_upgrade_is_atomic_and_never_invents_historical_details(
    tmp_path, monkeypatch, crash_statement
):
    service, uid, job, _ = recorded_job(tmp_path, monkeypatch)
    with service.database.transaction(immediate=True) as conn:
        conn.execute("ALTER TABLE result_versions DROP COLUMN extraction_receipt_json")
        conn.execute("UPDATE schema_meta SET version=14")
    statements = 0

    def crash():
        nonlocal statements
        statements += 1
        if statements == crash_statement:
            raise RuntimeError("simulated upgrade interruption")

    service.database._migration_fault_hook = crash
    with pytest.raises(RuntimeError, match="interruption"):
        service.database.initialize()
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 14
        assert "extraction_receipt_json" not in service.database._columns(conn, "result_versions")
    service.database._migration_fault_hook = None
    service.database.initialize()
    restored = service.get_job(user_id=uid, job_id=job["id"])
    assert restored["result"] == job["result"]
    assert restored["extraction_receipt"]["capture"] == "historical_unavailable"
    assert restored["model_version"] is None
    assert "historical result" in " ".join(restored["extraction_warnings"])
    assert restored["review_revision"] != job["review_revision"]


def test_shortened_raw_hashes_full_response_and_marks_missing_completion(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False, max_result_json_bytes=1024)
    uid = customer_id(service, "raw@example.com")
    queued = _paid_job(service, uid, color="blue")
    raw = "é" * 1000
    service.extractor = SimpleNamespace(
        extract=lambda image: ExtractionOutput(
            chart=ChartData.model_validate(response()["json"]),
            raw=raw,
            extractor="saved-replay",
            model_version="old-model",
        )
    )
    assert service.process_one()
    job = service.get_job(user_id=uid, job_id=queued["id"])
    receipt = job["extraction_receipt"]
    assert receipt["raw_sha256"] == sha256(raw)
    assert receipt["stored_raw_sha256"] == sha256("é" * 512)
    assert receipt["raw_byte_count"] == 2000
    assert receipt["raw_truncated"] is True
    assert receipt["diagnostics"]["finish_reason"] == "unavailable"
    assert len(job["extraction_warnings"]) == 3


def test_invalid_provider_metadata_fails_publication_without_an_automatic_retry(
    tmp_path, monkeypatch
):
    service, uid, job, _ = recorded_job(tmp_path, monkeypatch)
    output = service.extractor.extract(b"fixture")
    diagnostics = ExtractionDiagnostics()
    # A constructed/copied Pydantic object must not bypass field validation.
    invalid = diagnostics.model_copy(update={"model_repository": "x" * MAX_RECEIPT_BYTES})
    service.extractor = SimpleNamespace(extract=lambda image: replace(output, diagnostics=invalid))
    service.reprocess(user_id=uid, job_id=job["id"])
    assert service.process_one()
    failed = service.get_job(user_id=uid, job_id=job["id"])
    assert failed["result_version"] == 1
    assert failed["error"]["code"] == "model_output_invalid"
    assert not service.process_one()


def test_demo_is_reference_data_not_claimed_model_output(tmp_path):
    service = service_for(tmp_path)
    uid, job = sample(service)
    assert job["extraction_receipt"]["origin"] == "reference_fixture"
    assert job["extraction_receipt"]["diagnostics"]["finish_reason"] == "unavailable"
    assert job["extraction_warnings"] == [
        "This example uses saved reference data. No live model inference was run."
    ]
    payload, _ = service.export(
        user_id=uid,
        job_id=job["id"],
        output_format="json",
        expected_revision=job["review_revision"],
    )
    assert json.loads(payload)["provenance"]["extraction_receipt"]["origin"] == "reference_fixture"


def test_pdf_page_crop_and_exact_provider_bytes_are_bound_to_the_receipt(tmp_path, monkeypatch):
    import pypdfium2 as pdfium

    service = service_for(tmp_path, seed_demo_account=False)
    uid = customer_id(service, "crop@example.com")
    document = pdfium.PdfDocument.new()
    document.new_page(160, 100)
    document.new_page(200, 140)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    uploaded_bytes = buffer.getvalue()
    upload = service.prepare_upload(user_id=uid, filename="report.pdf", content=uploaded_bytes)
    crop = {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.5}
    queued = service.create_job(user_id=uid, upload_id=upload["id"], page_index=1, crop=crop)
    received = []

    async def invoke(image_bytes):
        received.append(image_bytes)
        return response(provider_release="a" * 64)

    service.extractor = ModalExtractor(service.settings)
    monkeypatch.setattr(service.extractor, "_invoke", invoke)
    assert service.process_one()
    assert len(received) == 1
    assert received[0].startswith(b"\x89PNG")
    job = service.get_job(user_id=uid, job_id=queued["id"])
    receipt = job["extraction_receipt"]
    assert receipt["page_index"] == 1
    assert receipt["crop"] == crop
    assert receipt["source_sha256"] == sha256(uploaded_bytes)
    assert receipt["provider_input_sha256"] == sha256(received[0])
    assert receipt["source_sha256"] != receipt["provider_input_sha256"]
    payload, _ = service.export(
        user_id=uid,
        job_id=job["id"],
        output_format="json",
        expected_revision=job["review_revision"],
    )
    source = json.loads(payload)["provenance"]["source"]
    assert source == {
        "name": "report.pdf",
        "sha256": sha256(uploaded_bytes),
        "page_index": 1,
        "crop": crop,
    }
