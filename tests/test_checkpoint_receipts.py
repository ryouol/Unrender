"""Byte-bound checkpoint identity, interrupted saves and retention ordering."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from unrender.train.checkpoints import (
    IDENTITY_FIELDS,
    RECEIPT,
    SealBeforeRetention,
    latest,
    seal,
    verify,
)


@pytest.fixture
def identity():
    value = {name: {"fixture": name} for name in IDENTITY_FIELDS}
    value["runtime"]["world_size"] = 1
    return value


def checkpoint(root: Path, step=4, best=None):
    path = root / f"checkpoint-{step}"
    path.mkdir(parents=True)
    for name in (
        "training_args.bin",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
        "model.safetensors",
        "config.json",
    ):
        (path / name).write_bytes(b"opaque test fixture; never unpickle")
    (path / "trainer_state.json").write_text(
        json.dumps(
            {
                "global_step": step,
                "is_world_process_zero": True,
                "is_local_process_zero": True,
                "best_model_checkpoint": str(best) if best else None,
            }
        )
    )
    return path


def test_complete_receipt_roundtrip_and_numeric_latest(tmp_path, identity):
    for step in (4, 12, 8):
        path = checkpoint(tmp_path, step)
        first = seal(path, identity, model_format="full")
        assert seal(path, identity, model_format="full") == first
        assert verify(path, identity, model_format="full")["step"] == step
    assert latest(tmp_path, identity, model_format="full").name == "checkpoint-12"


def test_framework_config_integer_keys_and_tuples_survive_json_receipt(tmp_path, identity):
    identity["base"].update(id2label={0: "zero", 1: "one"}, shape=(16, 16))
    path = checkpoint(tmp_path)
    seal(path, identity, model_format="full")
    assert verify(path, identity, model_format="full")["step"] == 4


@pytest.mark.parametrize("field", sorted(IDENTITY_FIELDS))
def test_any_changed_recipe_component_rejects_resume(tmp_path, identity, field):
    path = checkpoint(tmp_path)
    seal(path, identity, model_format="full")
    identity[field]["changed"] = True
    with pytest.raises(ValueError, match="identity"):
        verify(path, identity, model_format="full")


@pytest.mark.parametrize(
    "name",
    ["model.safetensors", "optimizer.pt", "scheduler.pt", "rng_state.pth", "training_args.bin"],
)
def test_changed_checkpoint_bytes_reject_without_unpickling(tmp_path, identity, name):
    path = checkpoint(tmp_path)
    seal(path, identity, model_format="full")
    (path / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="inventory changed"):
        verify(path, identity, model_format="full")


def test_incomplete_newer_save_never_causes_unrecorded_rollback(tmp_path, identity):
    good = checkpoint(tmp_path)
    seal(good, identity, model_format="full")
    (tmp_path / "checkpoint-8").mkdir()
    with pytest.raises(ValueError, match="no completion receipt"):
        latest(tmp_path, identity, model_format="full")
    assert good.is_dir() and (tmp_path / "checkpoint-8").is_dir()


def test_missing_rng_and_scaler_never_publish_receipt(tmp_path, identity):
    path = checkpoint(tmp_path)
    (path / "rng_state.pth").unlink()
    with pytest.raises(ValueError, match="rng_state"):
        seal(path, identity, model_format="full")
    assert not (path / RECEIPT).exists()
    (path / "rng_state.pth").write_bytes(b"rng")
    with pytest.raises(ValueError, match="scaler.pt"):
        seal(path, identity, model_format="full", fp16=True)
    assert not (path / RECEIPT).exists()


def test_step_mismatch_and_symlink_reject(tmp_path, identity):
    path = checkpoint(tmp_path)
    state_path = path / "trainer_state.json"
    state = json.loads(state_path.read_bytes())
    state["global_step"] = 8
    state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="state step"):
        seal(path, identity, model_format="full")
    state["global_step"] = 4
    state_path.write_text(json.dumps(state))
    (path / "linked").symlink_to(state_path)
    with pytest.raises(ValueError, match="symbolic link"):
        seal(path, identity, model_format="full")


def test_best_checkpoint_is_verified_and_cannot_escape_run(tmp_path, identity):
    best = checkpoint(tmp_path)
    seal(best, identity, model_format="full")
    newer = checkpoint(tmp_path, 8, best)
    seal(newer, identity, model_format="full")
    (best / "optimizer.pt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="inventory changed"):
        verify(newer, identity, model_format="full")
    outside = checkpoint(tmp_path / "different", 4)
    invalid = checkpoint(tmp_path, 12, outside)
    with pytest.raises(ValueError, match="outside this run"):
        seal(invalid, identity, model_format="full")


def test_receipt_precedes_retention_and_failure_preserves_old_checkpoints(
    tmp_path, identity, monkeypatch
):
    import sys

    old = checkpoint(tmp_path, 4)
    seal(old, identity, model_format="full")
    current = checkpoint(tmp_path, 8)
    calls = []

    def rotate(**kwargs):
        assert kwargs["save_total_limit"] == 1
        assert verify(current, identity, model_format="full")["step"] == 8
        calls.append("retention allowed")

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(save=lambda args, path: path.write_bytes(b"restored args")),
    )
    monkeypatch.setitem(
        sys.modules, "transformers.trainer_utils", SimpleNamespace(rotate_checkpoints=rotate)
    )

    class Parent:
        def _save_checkpoint(self, model, trial):
            assert self.args.save_total_limit is None

        def _get_output_dir(self, trial):
            return str(tmp_path)

    class Trainer(SealBeforeRetention, Parent):
        checkpoint_identity = identity
        checkpoint_model_format = "full"
        args = SimpleNamespace(world_size=1, push_to_hub=False, save_total_limit=1, fp16=False)
        state = SimpleNamespace(global_step=8, best_model_checkpoint=None)

    trainer = Trainer()
    (current / "rng_state.pth").unlink()
    with pytest.raises(ValueError, match="missing"):
        trainer._save_checkpoint(None, None)
    assert not calls and old.is_dir() and trainer.args.save_total_limit == 1
    (current / "rng_state.pth").write_bytes(b"rng")
    trainer._save_checkpoint(None, None)
    assert calls == ["retention allowed"]


def test_failed_receipt_publication_does_not_create_false_completion(
    tmp_path, identity, monkeypatch
):
    import unrender.train.checkpoints as module

    path = checkpoint(tmp_path)

    def fail(*args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(module.os, "link", fail)
    with pytest.raises(OSError, match="publication interrupted"):
        seal(path, identity, model_format="full")
    assert not (path / RECEIPT).exists()
    assert not list(tmp_path.glob(".receipt-*"))


def test_retention_does_not_require_obsolete_best_dependencies(tmp_path, identity):
    import shutil

    oldest = checkpoint(tmp_path, 10)
    seal(oldest, identity, model_format="full")
    prior = checkpoint(tmp_path, 20, oldest)
    seal(prior, identity, model_format="full")
    best = checkpoint(tmp_path, 30)
    seal(best, identity, model_format="full")
    newest = checkpoint(tmp_path, 40, best)
    seal(newest, identity, model_format="full")
    shutil.rmtree(oldest)
    assert latest(tmp_path, identity, model_format="full") == newest
    # The selected checkpoint's best weights are still required.
    shutil.rmtree(best)
    with pytest.raises(ValueError, match="no completion receipt"):
        latest(tmp_path, identity, model_format="full")


def test_best_weights_do_not_require_their_own_old_best(tmp_path, identity):
    import shutil

    old = checkpoint(tmp_path, 10)
    seal(old, identity, model_format="full")
    best = checkpoint(tmp_path, 20, old)
    seal(best, identity, model_format="full")
    newest = checkpoint(tmp_path, 30, best)
    seal(newest, identity, model_format="full")
    shutil.rmtree(old)
    assert verify(newest, identity, model_format="full")["step"] == 30
