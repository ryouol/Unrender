"""Source review is explicit, complete, byte-bound and checked before GPU dispatch.

Processor outputs below are test doubles. Real CPU-processor evidence lives in
release/chart-layout-v1; these fixtures never attest to a person's review.
"""

import ast
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from unrender.data_gen.generate import generate
from unrender.data_gen.provenance import digest, json_bytes, read_split, verify_dataset
from unrender.data_gen.review import (
    CHECKS,
    PROCESSOR_RUNTIME,
    prepare,
    require_source_review,
    require_training_sources,
)
from unrender.data_gen.split_dataset import split


@pytest.fixture(scope="module")
def packet_source(tmp_path_factory):
    base = tmp_path_factory.mktemp("source-review-fixture")
    root = base / "visible_fixture"
    generate(4, str(root), base_seed=47020, v2=True, workers=1)
    split(str(root), val_size=1, test_size=1)
    generation, rows = verify_dataset(root)
    audit = base / "audit"
    audit.mkdir()
    config = b'{"test_double":true}'
    (audit / "preprocessor_config.json").write_bytes(config)
    report = {
        "contract": "qwen-image-budget-audit-v2",
        "device": "cpu",
        "packages": dict(PROCESSOR_RUNTIME),
        "processor_class": "Qwen2VLImageProcessor",
        "processor_config_sha256": digest(config),
        "datasets": {root.name: generation},
        "rows": [],
    }
    for row in rows:
        raw = (root / row["image"]).read_bytes()
        budgets = {}
        for budget in ("full", "512"):
            name = f"{row['id']}-{budget}.png"
            (audit / name).write_bytes(raw)
            budgets[budget] = {
                "raster": name,
                "raster_sha256": digest(raw),
                "image_tokens": 100,
                "reconstructed_pixels_equal_captured_resize": True,
            }
        report["rows"].append(
            {
                "dataset": root.name,
                "id": row["id"],
                "image_sha256": row["image_sha256"],
                "budgets": budgets,
            }
        )
    (audit / "report.json").write_bytes(json_bytes(report))
    prepare(root, audit, audit)
    return root


@pytest.fixture
def packet(packet_source, tmp_path):
    root = tmp_path / "relocated"
    shutil.copytree(packet_source, root)
    return root


def mark_fixture_eligible(root):
    """Explicit test-only attestation, never used to create release approvals."""
    path = root / "review/review.json"
    review = json.loads(path.read_bytes())
    for row in review["rows"]:
        row.update(
            decision="eligible",
            reviewer="Test fixture — not a human approval",
            reviewed_at="2026-09-18T12:00:00Z",
            notes="Fixture exercises the receipt gate.",
            checks=dict.fromkeys(CHECKS, True),
        )
    path.write_bytes(json_bytes(review))
    return review


def test_pending_packet_rejects_training_without_filtering_and_leaves_evaluation_readable(packet):
    assert len(read_split(packet / "train.jsonl")) == 2
    with pytest.raises(ValueError, match="2 noneligible source rows; no rows filtered"):
        require_source_review(packet / "train.jsonl")
    reviews = json.loads((packet / "review/review.json").read_bytes())
    assert len(reviews["rows"]) == 4
    assert all(row["decision"] == "pending" for row in reviews["rows"])
    assert all(not any(row["checks"].values()) for row in reviews["rows"])
    html = (packet / "review/index.html").read_text()
    assert "All decisions start pending" in html and html.count("<article>") == 4
    assert html.count("<table>") == 4


def test_review_is_portable_and_retains_exact_evidence(packet):
    mark_fixture_eligible(packet)
    receipts = require_training_sources(["train.jsonl"], ["val.jsonl"], str(packet))
    assert sum(r["source_rows"] for r in receipts.values()) == 3
    assert receipts[str(packet / "train.jsonl")]["review_sha256"] == digest(
        (packet / "review/review.json").read_bytes()
    )


@pytest.mark.parametrize("status", ["pending", "stress", "unreadable"])
def test_ineligible_validation_row_rejects_before_val_size_sampling(packet, status):
    review = mark_fixture_eligible(packet)
    val_id = Path(read_split(packet / "val.jsonl")[0]["images"][0]).stem
    next(r for r in review["rows"] if r["id"] == val_id)["decision"] = status
    (packet / "review/review.json").write_bytes(json_bytes(review))
    with pytest.raises(ValueError, match="noneligible source rows"):
        require_training_sources(["train.jsonl"], ["val.jsonl"], str(packet))


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_id",
        "duplicate_id",
        "wrong_packet",
        "string_bool",
        "incomplete",
        "anonymous",
        "no_timezone",
        "no_notes",
    ],
)
def test_invalid_or_incomplete_attestation_is_rejected(packet, mutation):
    review = mark_fixture_eligible(packet)
    row = review["rows"][0]
    if mutation == "missing_id":
        review["rows"].pop()
    elif mutation == "duplicate_id":
        review["rows"].append(row)
    elif mutation == "wrong_packet":
        review["packet_sha256"] = "a" * 64
    elif mutation == "string_bool":
        row["checks"][CHECKS[0]] = "true"
    elif mutation == "incomplete":
        row["checks"][CHECKS[0]] = False
    elif mutation == "anonymous":
        row["reviewer"] = " "
    elif mutation == "no_timezone":
        row["reviewed_at"] = "2026-09-18T12:00:00"
    elif mutation == "no_notes":
        row["notes"] = " "
    (packet / "review/review.json").write_bytes(json_bytes(review))
    with pytest.raises(ValueError, match="source review failed"):
        require_source_review(packet / "train.jsonl")


@pytest.mark.parametrize(
    "artifact",
    [
        "review/protocol.md",
        "review/processor-audit.json",
        "review/preprocessor_config.json",
        "review/processor/0000000-512.png",
    ],
)
def test_altered_review_inputs_revoke_the_gate(packet, artifact):
    mark_fixture_eligible(packet)
    path = packet / artifact
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        require_source_review(packet / "train.jsonl")


def test_old_manual_splits_and_test_split_cannot_be_used_as_training_sources(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_bytes(json_bytes({"images": ["old.png"], "messages": []}))
    with pytest.raises(ValueError, match="current generated bundle"):
        require_source_review(path)
    with pytest.raises(ValueError, match="roles"):
        require_training_sources(["test.jsonl"], [], str(tmp_path))


def test_local_train_rejects_pending_review_before_cuda_imports(packet, monkeypatch):
    from unrender.train.sft_lora import train

    monkeypatch.setitem(sys.modules, "unsloth", None)
    with pytest.raises(ValueError, match="noneligible source rows"):
        train(["train.jsonl"], str(packet / "out"), data_root=str(packet))
    assert not (packet / "out").exists()


def test_training_batch_detects_image_change_after_source_validation(packet, monkeypatch):
    from unrender.train.sft_lora import build_dataset, load_records

    class Dataset:
        @staticmethod
        def from_list(records):
            return SimpleNamespace(with_transform=lambda callback: callback)

    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(Dataset=Dataset))
    records = load_records(["train.jsonl"], str(packet), 1, 0)
    transform = build_dataset(records)
    batch = {key: [r[key] for r in records] for key in records[0]}
    assert len(transform(batch)["messages"]) == 2
    image = Path(records[0]["image"])
    image.write_bytes(image.read_bytes() + b" ")
    with pytest.raises(ValueError, match="image changed after source review"):
        transform(batch)


def launch_body(module, name):
    """Run the actual local-entrypoint body without activating a Modal app."""
    tree = ast.parse(Path(module.__file__).read_text())
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    function.decorator_list = []
    namespace = vars(module).copy()
    exec(compile(ast.Module(body=[function], type_ignores=[]), module.__file__, "exec"), namespace)
    return namespace[name]


def test_cloud_entrypoint_does_not_allocate_gpu_after_failed_cpu_gate(monkeypatch):
    import modal_train

    gpu = []

    def rejected(**kwargs):
        raise ValueError("pending source review")

    monkeypatch.setattr(modal_train, "preflight", SimpleNamespace(remote=rejected))
    monkeypatch.setattr(
        modal_train, "train_model", SimpleNamespace(spawn=lambda **k: gpu.append(k))
    )
    with pytest.raises(ValueError, match="pending source review"):
        launch_body(modal_train, "train")(train_files="visible_fixture", base_revision="a" * 40)
    assert gpu == []


def test_cloud_entrypoint_binds_cpu_review_to_worker(monkeypatch):
    import modal_train

    received = []
    evidence = {"fixture": {"review_sha256": "a" * 64}}
    monkeypatch.setattr(
        modal_train,
        "preflight",
        SimpleNamespace(remote=lambda **kwargs: {"source_reviews": evidence}),
    )

    def spawn(**kwargs):
        received.append(kwargs)
        return SimpleNamespace(object_id="test-call")

    monkeypatch.setattr(modal_train, "train_model", SimpleNamespace(spawn=spawn))
    launch_body(modal_train, "train")(train_files="visible_fixture", base_revision="a" * 40)
    assert received[0]["expected_source_reviews"] == evidence


def test_cpu_preflight_checks_both_splits_and_honors_the_step_cap(packet, tmp_path, monkeypatch):
    import modal_train

    mark_fixture_eligible(packet)
    target = tmp_path / "volume/data/synthetic_visible_fixture"
    target.parent.mkdir(parents=True)
    packet.rename(target)
    monkeypatch.setattr(modal_train, "V", str(tmp_path / "volume"))
    report = launch_body(modal_train, "preflight")(
        train_files="visible_fixture", val_files="visible_fixture", max_steps=30
    )
    assert len(report["source_reviews"]) == 2
    assert sum(r["source_rows"] for r in report["source_reviews"].values()) == 3
    assert report["estimated_optimizer_steps"] == 30
    assert "unverified" in report["limits"]


@pytest.mark.parametrize("expected", [None, {"fixture": {"review_sha256": "old"}}])
def test_worker_rejects_missing_or_changed_cpu_evidence_before_training(monkeypatch, expected):
    import modal_train
    from unrender.data_gen import review
    from unrender.train import sft_lora

    trained = []
    monkeypatch.setattr(review, "require_training_sources", lambda *args: {"new": "receipt"})
    monkeypatch.setattr(sft_lora, "train", lambda **kwargs: trained.append(kwargs))
    with pytest.raises(ValueError, match="CPU preflight is missing"):
        launch_body(modal_train, "train_model")(
            train_files="visible_fixture", expected_source_reviews=expected
        )
    assert trained == []


def test_geometry_training_is_rejected_before_cpu_or_gpu_dispatch(monkeypatch):
    import modal_train

    calls = []
    monkeypatch.setattr(
        modal_train, "preflight", SimpleNamespace(remote=lambda **k: calls.append(k))
    )
    with pytest.raises(ValueError, match="geometry conversion is not approved"):
        launch_body(modal_train, "train")(train_files="visible_fixture", geometry=True)
    assert not calls


@pytest.mark.parametrize("name", ["", "v1", "v2,v1,v0", "visible_x,visible_x", "../outside"])
def test_cloud_dataset_selection_rejects_historical_empty_duplicate_or_escaped_names(name):
    import modal_train

    with pytest.raises(ValueError):
        modal_train._training_source_paths(name, "")
