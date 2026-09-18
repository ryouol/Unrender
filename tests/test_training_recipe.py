import copy

import pytest

from unrender.train.recipe import inventory, record_identity, require_revision


def identity():
    return {
        "base": {"revision": "a" * 40},
        "processor": {"files": "test-only"},
        "source_inputs": {"split": "test-only"},
        "hyperparameters": {"lr": 0.01},
        "runtime": {"world_size": 1},
        "source_code": {"source": "test-only"},
    }


@pytest.mark.parametrize("revision", ["", "main", "latest", "a" * 39, "g" * 40, None])
def test_mutable_or_invalid_revision_rejected(revision):
    with pytest.raises(ValueError, match="immutable"):
        require_revision(revision)


def test_recipe_is_persisted_and_drift_rejected(tmp_path):
    value = identity()
    record_identity(tmp_path, value)
    before = (tmp_path / "training-recipe.json").read_bytes()
    record_identity(tmp_path, value)
    for field in value:
        changed = copy.deepcopy(value)
        changed[field]["unexpected_drift"] = True
        with pytest.raises(ValueError, match="recipe changed"):
            record_identity(tmp_path, changed)
    assert (tmp_path / "training-recipe.json").read_bytes() == before


def test_old_unidentified_run_cannot_gain_a_recipe(tmp_path):
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints/checkpoint-8").mkdir()
    with pytest.raises(ValueError, match="lack a verified recipe"):
        record_identity(tmp_path, identity())
    assert not (tmp_path / "training-recipe.json").exists()


def test_inventory_records_actual_bytes(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        inventory(tmp_path)
    (tmp_path / "weights").write_bytes(b"before")
    before = inventory(tmp_path)
    (tmp_path / "weights").write_bytes(b"after")
    assert before != inventory(tmp_path)


def test_modal_training_claim_is_held_until_persistence(monkeypatch):
    from types import SimpleNamespace

    import modal_train
    from tests.test_source_review import launch_body
    from unrender.data_gen import review
    from unrender.train import sft_lora

    events, claims = [], {}

    class Claims:
        def put(self, key, value, *, skip_if_exists):
            assert skip_if_exists
            if key in claims:
                return False
            claims[key] = value
            events.append("claim")
            return True

        def get(self, key):
            return claims[key]

        def pop(self, key):
            events.append("release")
            return claims.pop(key)

    monkeypatch.setattr(
        modal_train.modal, "Dict", SimpleNamespace(from_name=lambda *a, **k: Claims())
    )
    monkeypatch.setattr(modal_train.modal, "current_function_call_id", lambda: "test-only-call")
    monkeypatch.setattr(modal_train, "VOL", SimpleNamespace(commit=lambda: events.append("commit")))
    monkeypatch.setattr(review, "require_training_sources", lambda *a: {"review": "test-only"})

    def train(**kwargs):
        assert claims["test-run"]["call_id"] == "test-only-call"
        assert kwargs["base_revision"] == "a" * 40
        events.append("train")
        kwargs["checkpoint_commit"]()

    monkeypatch.setattr(sft_lora, "train", train)
    worker = launch_body(modal_train, "train_model")
    args = dict(
        train_files="visible_fixture",
        out_name="test-run",
        base_revision="a" * 40,
        expected_source_reviews={"review": "test-only"},
    )
    worker(**args)
    assert events[:5] == ["claim", "train", "commit", "commit", "release"]
    assert not claims
    claims["test-run"] = {"token": "prior-live-or-uncertain-call"}
    with pytest.raises(ValueError, match="owned"):
        worker(**args)
    assert events.count("train") == 1
    claims.clear()

    def fail(**kwargs):
        raise RuntimeError("interrupted training")

    monkeypatch.setattr(sft_lora, "train", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        worker(**args)
    assert "test-run" in claims  # no stale-lock guessing after failure
