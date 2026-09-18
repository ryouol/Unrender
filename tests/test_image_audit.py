"""Offline image-audit provenance and exact augmentation replay boundaries."""

import json
import shutil

import pytest

from analysis.audit_image_budget import _inputs
from analysis.replay_augmentation import replay
from unrender.data_gen.generate import generate
from unrender.data_gen.provenance import digest, json_bytes


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("image-audit")
    generate(1, str(root), base_seed=47020, v2=True, workers=1)
    return root


def test_exact_replay_retains_stages_and_does_not_overwrite(bundle, tmp_path):
    report = replay(bundle, "0000000", tmp_path)
    assert report["final_image_matches_recorded_bytes"] is True
    assert report["stages"][0]["name"] == "native"
    assert report["stages"][-1]["sha256"] == report["source_image_sha256"]
    assert len(report["stages"]) > 2  # this saved failure exercises actual degradations
    with pytest.raises(ValueError, match="fresh directory"):
        replay(bundle, "0000000", tmp_path)


@pytest.mark.parametrize(
    "artifact", ["manifest.jsonl", "images/0000000.png", "labels/0000000.json"]
)
def test_processor_audit_rejects_altered_artifacts(bundle, tmp_path, artifact):
    shutil.copytree(bundle, tmp_path, dirs_exist_ok=True)
    path = tmp_path / artifact
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        _inputs(tmp_path)


def test_processor_audit_rejects_manifest_path_escape_even_if_receipt_is_rehashed(bundle, tmp_path):
    shutil.copytree(bundle, tmp_path, dirs_exist_ok=True)
    row = json.loads((tmp_path / "manifest.jsonl").read_text())
    row["image"] = "../outside.png"
    raw = json_bytes(row)
    (tmp_path / "manifest.jsonl").write_bytes(raw)
    receipt = json.loads((tmp_path / "generation.json").read_text())
    receipt["manifest_sha256"] = digest(raw)
    (tmp_path / "generation.json").write_bytes(json_bytes(receipt))
    with pytest.raises(ValueError, match="escaped"):
        _inputs(tmp_path)


def test_replay_rejects_different_generator_source(bundle, tmp_path, monkeypatch):
    import analysis.replay_augmentation as module

    monkeypatch.setattr(module, "recipe", lambda **kwargs: {})
    with pytest.raises(ValueError, match="recorded generator sources"):
        replay(bundle, "0000000", tmp_path)
    assert not list(tmp_path.iterdir())
