"""Integrity guards for the eval harness — the safeguards that would have caught
the dev300/Modal-test split desync (subset coverage, fingerprints, no-clobber,
resume-config, deterministic splitting, duplicate ids, output-tag uniqueness).

All hermetic: mock 'perfect' provider, tmp dirs, no API/GPU/network.
"""

import json
import random
from pathlib import Path

import pytest

from unrender.io_utils import fingerprint_ids
from unrender.schema.chart_schema import ChartData, Point, Series, canonical_json


def _gt():
    return ChartData(chart_type="bar", series=[Series(name="S", points=[
        Point(x="a", y=1.0), Point(x="b", y=2.0)])])


def _chat_row(i, labels_shown=True):
    return {
        "images": [f"data/x/{i:07d}.png"],
        "messages": [{"role": "user", "content": "P"},
                     {"role": "assistant", "content": canonical_json(_gt())}],
        "meta": {"labels_shown": labels_shown, "chart_type": "bar", "augmented": False},
    }


def _write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows))


def _make_dataset(path, n):
    _write_jsonl(path, [_chat_row(i) for i in range(1, n + 1)])


# --- fingerprints ------------------------------------------------------------

def test_fingerprint_order_independent_content_sensitive_and_dedup():
    assert fingerprint_ids(["a", "b", "c"]) == fingerprint_ids(["c", "a", "b"])  # order-independent
    assert fingerprint_ids(["a", "b"]) != fingerprint_ids(["a", "c"])            # content-sensitive
    assert fingerprint_ids(["a", "a", "b"]) == fingerprint_ids(["a", "b"])       # membership (dedup)
    fp = fingerprint_ids(["a"])
    assert isinstance(fp, str) and len(fp) == 16


# --- run() coverage + provenance --------------------------------------------

def test_run_coverage_guard_raises_on_missing_id(tmp_path):
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"; _make_dataset(data, 2)
    with pytest.raises(SystemExit, match="coverage"):
        run("perfect", "mock", str(data), str(tmp_path / "o"), 0, 0,
            only_ids={"0000001", "ZZZZZZZ"})


def test_run_records_fingerprints_and_pinned_revision(tmp_path):
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"; _make_dataset(data, 3)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0, only_ids={"0000001", "0000002"})
    meta = json.loads((out / "meta.json").read_text())
    assert meta["subset_fp"] and meta["dataset_fp"] and meta["n_subset"] == 2
    # an explicit Hub revision is recorded (the base-control fix); None would be unpinned
    out2 = tmp_path / "o2"
    run("perfect", "Some/HubModel", str(data), str(out2), 0, 0, revision="abc123")
    assert json.loads((out2 / "meta.json").read_text())["model_revision"] == "abc123"


def test_resume_config_mismatch_raises(tmp_path):
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"; _make_dataset(data, 2)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0)                       # greedy
    with pytest.raises(SystemExit, match="resume-config"):                  # different decoder
        run("perfect", "mock", str(data), str(out), 0, 0,
            gen_config={"repetition_penalty": 1.1})


# --- score() coverage, no-clobber, duplicate rows ---------------------------

def test_score_subset_does_not_clobber_full_report(tmp_path):
    from unrender.eval.run_baselines import run
    from unrender.eval.score import score
    data = tmp_path / "test.jsonl"; _make_dataset(data, 3)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0)
    pred = str(out / "predictions.jsonl")

    score(pred)                                   # full -> report.json
    full = (out / "report.json").read_text()
    score(pred, only_ids={"0000001", "0000002"})  # subset must NOT touch report.json
    assert (out / "report.json").read_text() == full
    assert any(p.name.startswith("report.subset-") for p in out.iterdir())


def test_score_coverage_guard_raises_on_missing_id(tmp_path):
    from unrender.eval.run_baselines import run
    from unrender.eval.score import score
    data = tmp_path / "test.jsonl"; _make_dataset(data, 2)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0)
    with pytest.raises(SystemExit, match="coverage"):
        score(str(out / "predictions.jsonl"), out=str(tmp_path / "x.json"),
              only_ids={"0000001", "NOPE"})


def test_score_duplicate_rows_raise(tmp_path):
    from unrender.eval.score import score
    pred = tmp_path / "predictions.jsonl"
    row = {"id": "0000001", "gt": canonical_json(_gt()), "raw": "{}", "status": "ok"}
    pred.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="duplicate"):
        score(str(pred))


# --- deterministic splitting -------------------------------------------------

def _make_manifest(d, order):
    d = Path(d)
    (d / "labels").mkdir(parents=True, exist_ok=True)
    entries = []
    for i in order:
        stem = f"{i:07d}"
        (d / "labels" / f"{stem}.json").write_text(canonical_json(_gt()))
        entries.append({"id": stem, "image": f"data/img/{stem}.png",
                        "label": str(d / "labels" / f"{stem}.json"),
                        "chart_type": "bar", "labels_shown": True, "augmented": False})
    _write_jsonl(d / "manifest.jsonl", entries)


def test_split_membership_independent_of_manifest_order(tmp_path):
    from unrender.data_gen.split_dataset import split
    order = list(range(1, 21))
    shuffled = order[:]; random.Random(99).shuffle(shuffled)
    _make_manifest(tmp_path / "a", order)       # ascending manifest
    _make_manifest(tmp_path / "b", shuffled)    # same ids, different write-order
    split(str(tmp_path / "a"), val_size=4, test_size=6, seed=7)
    split(str(tmp_path / "b"), val_size=4, test_size=6, seed=7)

    def ids(p):
        return {Path(json.loads(l)["images"][0]).stem
                for l in Path(p).read_text().splitlines() if l.strip()}
    for name in ("train", "val", "test"):
        assert ids(tmp_path / "a" / f"{name}.jsonl") == ids(tmp_path / "b" / f"{name}.jsonl")


# --- output-tag uniqueness (Modal) ------------------------------------------

def test_eval_tag_unique_per_config_and_preserves_resume_name():
    pytest.importorskip("modal")
    from modal_train import _eval_tag
    merged = "/vol/runs/qwen3vl4b-lora/merged"
    tags = {
        _eval_tag(merged, "v1", "", {}),                                    # LoRA full greedy
        _eval_tag(merged, "v1", "common300", {}),                           # LoRA subset
        _eval_tag("unsloth/Qwen3-VL-4B-Instruct", "v1", "common300", {}),   # base subset
        _eval_tag(merged, "v1", "common300", {"repetition_penalty": 1.1}),  # decoder arm
    }
    assert len(tags) == 4                                       # every config distinct
    assert _eval_tag(merged, "v1", "", {}) == "eval_v1__qwen3vl4b-lora"  # original name preserved
