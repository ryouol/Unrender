"""Evaluation crashes must not hide inputs or buy an uncertain request twice."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from unrender.eval import providers
from unrender.eval.ledger import LEDGER_NAME, ledger_snapshot, load_predictions, run_owner
from unrender.eval.paired_bootstrap import compare
from unrender.eval.report import build
from unrender.eval.run_baselines import _model_revision, run
from unrender.eval.score import score, score_rows


def dataset(root, count=3, *, images=False):
    rows = []
    for index in range(count):
        image = root / f"chart-{index}.png"
        if images:
            image.write_bytes(b"mock-image-bytes")
        rows.append(
            {
                "images": [str(image)],
                "messages": [
                    {"role": "user", "content": "Read the chart"},
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "chart_type": "bar",
                                "series": [
                                    {
                                        "name": "Revenue",
                                        "points": [
                                            {"x": "A", "y": index + 1.0},
                                            {"x": "B", "y": 2.0},
                                        ],
                                    }
                                ],
                            }
                        ),
                    },
                ],
                "meta": {"labels_shown": True},
            }
        )
    path = root / "data.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_sigkill_preserves_schedule_and_never_repeats_uncertain_dispatch(tmp_path, monkeypatch):
    data = dataset(tmp_path)
    output = tmp_path / "run"
    calls_file = tmp_path / "calls.jsonl"
    code = """
import json, os, signal, sys
from pathlib import Path
from unrender.eval import providers
from unrender.eval.run_baselines import run
calls = 0
def provider(image, prompt, model, gt_json=None, **kwargs):
    global calls
    calls += 1
    with open(sys.argv[3], "a") as stream:
        stream.write(json.dumps(Path(image).stem) + "\\n")
        stream.flush()
        os.fsync(stream.fileno())
    if calls == 2:
        os.kill(os.getpid(), signal.SIGKILL)
    return gt_json
providers.PROVIDERS["perfect"] = provider
run("perfect", "oracle", sys.argv[1], sys.argv[2], 0, 0)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(data), str(output), str(calls_file)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == -9, child.stderr
    rows = load_predictions(output / "predictions.jsonl")
    assert [r["attempt"]["state"] for r in rows] == ["completed", "dispatched", "pending"]
    assert [json.loads(line) for line in calls_file.read_text().splitlines()] == [
        "chart-0",
        "chart-1",
    ]
    # The initial JSONL is stale after SIGKILL, but official readers use the DB.
    stale = [json.loads(line) for line in (output / "predictions.jsonl").read_text().splitlines()]
    assert all(row["attempt"]["state"] == "pending" for row in stale)
    partial = score(str(output / "predictions.jsonl"))
    assert partial["tracks"]["0.05"]["metrics"]["n"] == 3
    assert partial["tracks"]["0.05"]["n_infra_error"] == 2
    with pytest.raises(ValueError, match="incomplete"):
        compare(rows, rows, [row["id"] for row in rows], iters=10)
    report_path = tmp_path / "comparison.md"
    report_path.write_text("prior evidence")
    with pytest.raises(ValueError, match="incomplete"):
        build([str(output)], str(report_path))
    assert report_path.read_text() == "prior evidence"
    called = []

    def provider(image, prompt, model, gt_json=None, **kwargs):
        called.append(Path(image).stem)
        return gt_json

    monkeypatch.setitem(providers.PROVIDERS, "perfect", provider)
    result_path = run("perfect", "oracle", str(data), str(output), 0, 0)
    assert called == ["chart-2"]
    rows = load_predictions(result_path)
    assert [r["attempt"]["state"] for r in rows] == ["completed", "interrupted", "completed"]
    result = score_rows(rows, 0.05)
    assert result["metrics"]["n"] == 3
    assert result["n_infra_error"] == 1
    assert result["attempt_coverage"]["all_recorded_terminal"]
    assert rows[1]["error"] == "evaluation_interrupted"
    before = result_path.read_bytes()
    run("perfect", "oracle", str(data), str(output), 0, 0)
    assert result_path.read_bytes() == before
    assert called == ["chart-2"]


def test_cross_process_owner_prevents_overlapping_provider_calls(tmp_path, monkeypatch):
    data = dataset(tmp_path)
    output = tmp_path / "run"
    script = """
import sys
from pathlib import Path
from unrender.eval.ledger import run_owner
with run_owner(Path(sys.argv[1])):
    print("owned", flush=True)
    sys.stdin.read()
"""
    with subprocess.Popen(
        [sys.executable, "-c", script, str(output)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as owner:
        try:
            assert owner.stdout.readline().strip() == "owned"
            calls = []
            monkeypatch.setitem(providers.PROVIDERS, "perfect", lambda *a, **k: calls.append(1))
            with pytest.raises(SystemExit, match="owned"):
                run("perfect", "oracle", str(data), str(output), 0, 0)
            assert calls == []
        finally:
            owner.stdin.close()
            owner.wait(timeout=10)
    with run_owner(output):
        pass


def test_missing_real_input_is_counted_without_dispatch(tmp_path, monkeypatch):
    data = dataset(tmp_path, count=2)
    calls = []
    monkeypatch.setitem(providers.PROVIDERS, "openai", lambda *a, **k: calls.append(1))
    path = run("openai", "test-only", str(data), str(tmp_path / "run"), 0, 0)
    rows = load_predictions(path)
    assert calls == []
    assert all(r["attempt"]["state"] == "input_error" for r in rows)
    assert all(r["attempt"]["started_at"] is None for r in rows)
    assert score_rows(rows, 0.05)["n_infra_error"] == 2


def test_input_content_drift_refuses_resume_even_with_same_dataset_bytes(tmp_path):
    data = dataset(tmp_path, count=1, images=True)
    output = tmp_path / "run"
    run("perfect", "oracle", str(data), str(output), 0, 0)
    (tmp_path / "chart-0.png").write_bytes(b"changed image bytes")
    with pytest.raises(SystemExit, match="schedule"):
        run("perfect", "oracle", str(data), str(output), 0, 0)


def test_local_weights_hash_recursive_bytes_not_mtime_or_size(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "nested").mkdir()
    weights = root / "nested" / "weights.bin"
    weights.write_bytes(b"before")
    old_stat = weights.stat()
    before = _model_revision(str(root))
    weights.write_bytes(b"after!")
    os.utime(weights, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert weights.stat().st_size == old_stat.st_size
    assert _model_revision(str(root)) != before


def test_ground_truth_and_duplicate_ids_fail_before_any_call(tmp_path, monkeypatch):
    data = dataset(tmp_path, count=1)
    text = data.read_text()
    data.write_text(text + text)
    called = []
    monkeypatch.setitem(providers.PROVIDERS, "perfect", lambda *a, **k: called.append(1))
    with pytest.raises(SystemExit, match="duplicate"):
        run("perfect", "oracle", str(data), str(tmp_path / "run"), 0, 0)
    row = json.loads(text)
    row["messages"][1]["content"] = '{"chart_type":"bar","series":[]}'
    data.write_text(json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="ground truth"):
        run("perfect", "oracle", str(data), str(tmp_path / "run"), 0, 0)
    assert called == []


def test_hf_completion_metadata_is_saved_without_claiming_mock_completion(tmp_path, monkeypatch):
    data = dataset(tmp_path, count=1, images=True)

    def fake_hf(image, prompt, model, gt_json=None, timings=None, **kwargs):
        timings.update(finish_reason="length", output_tokens=4096, max_output_tokens=4096)
        return gt_json

    monkeypatch.setitem(providers.PROVIDERS, "hf", fake_hf)
    path = run("hf", "test/model", str(data), str(tmp_path / "hf"), 0, 0, revision="a" * 40)
    rows = load_predictions(path)
    assert rows[0]["generation"]["finish_reason"] == "length"
    assert score_rows(rows, 0.05)["generation_finish_reasons"] == {"length": 1}
    # Raw chart accuracy and production acceptability are separate measurements.
    assert score_rows(rows, 0.05)["metrics"]["cell_f1"] == 1
    mocked = run("perfect", "oracle", str(data), str(tmp_path / "mock"), 0, 0)
    assert load_predictions(mocked)[0]["generation"]["finish_reason"] == "not_applicable_reference"


def test_legacy_jsonl_cannot_be_used_as_a_dispatch_resume_log(tmp_path):
    data = dataset(tmp_path)
    output = tmp_path / "old-run"
    output.mkdir()
    (output / "predictions.jsonl").write_text("")
    with pytest.raises(SystemExit, match="durable schedule"):
        run("perfect", "oracle", str(data), str(output), 0, 0)
    assert not (output / LEDGER_NAME).exists()


def test_resume_of_noisy_reference_is_stable_per_input(tmp_path, monkeypatch):
    data = dataset(tmp_path)
    real = providers.noisy_provider
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return real(*args, **kwargs)

    monkeypatch.setitem(providers.PROVIDERS, "noisy", interrupted)
    output = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        run("noisy", "oracle", str(data), str(output), 0, 42)
    monkeypatch.setitem(providers.PROVIDERS, "noisy", real)
    resumed = load_predictions(run("noisy", "oracle", str(data), str(output), 0, 42))
    complete = load_predictions(run("noisy", "oracle", str(data), str(tmp_path / "whole"), 0, 42))
    assert resumed[2]["raw"] == complete[2]["raw"]
    _, meta = ledger_snapshot(output / LEDGER_NAME)
    assert meta["n_scheduled"] == 3


def test_portable_snapshot_and_live_schedule_reject_missing_inputs(tmp_path):
    data = dataset(tmp_path)
    output = tmp_path / "run"
    run("perfect", "oracle", str(data), str(output), 0, 0)
    copy = tmp_path / "portable"
    copy.mkdir()
    for name in ("predictions.jsonl", "meta.json"):
        shutil.copyfile(output / name, copy / name)
    assert len(load_predictions(copy / "predictions.jsonl")) == 3
    exported = (copy / "predictions.jsonl").read_text().splitlines()
    (copy / "predictions.jsonl").write_text("\n".join(exported[:2]) + "\n")
    with pytest.raises(ValueError, match="schedule integrity"):
        load_predictions(copy / "predictions.jsonl")
    with sqlite3.connect(output / LEDGER_NAME) as conn:
        conn.execute("DELETE FROM samples WHERE ordinal=2")
    with pytest.raises(ValueError, match="schedule integrity"):
        load_predictions(output / "predictions.jsonl")


def test_live_metadata_is_read_from_the_authoritative_ledger(tmp_path):
    data = dataset(tmp_path, count=1)
    output = tmp_path / "run"
    run("perfect", "oracle", str(data), str(output), 0, 0)
    (output / "meta.json").write_text(json.dumps({"model": "incorrect-publication-label"}))
    result = score(str(output / "predictions.jsonl"))
    assert result["model"] == "oracle"
