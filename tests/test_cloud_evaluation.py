"""Cloud orchestration fences; real Volume/container-loss evidence remains separate."""

from types import SimpleNamespace

import pytest

import modal_train
from unrender.eval import run_baselines


@pytest.mark.parametrize("failure", [None, "reload", "commit", "run"])
def test_cloud_owner_and_persistence_order(monkeypatch, failure):
    claims, events = {}, []

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

    def action(name):
        events.append(name)
        if failure == name:
            raise OSError(name)

    def run(**kwargs):
        action("run")
        kwargs["persist"]()
        return "predictions.jsonl"

    monkeypatch.setattr(
        modal_train.modal, "Dict", SimpleNamespace(from_name=lambda *a, **k: Claims())
    )
    monkeypatch.setattr(modal_train.modal, "current_function_call_id", lambda: "test-only")
    monkeypatch.setattr(
        modal_train,
        "VOL",
        SimpleNamespace(reload=lambda: action("reload"), commit=lambda: action("commit")),
    )
    monkeypatch.setattr(run_baselines, "run", run)
    if failure:
        with pytest.raises(OSError, match=failure):
            modal_train._cloud_evaluation(out=f"{modal_train.V}/outputs/test")
        assert claims
        with pytest.raises(ValueError, match="already owned"):
            modal_train._cloud_evaluation(out=f"{modal_train.V}/outputs/test")
    else:
        modal_train._cloud_evaluation(out=f"{modal_train.V}/outputs/test")
        assert events == ["claim", "reload", "run", "commit", "commit", "release"]
        assert not claims
