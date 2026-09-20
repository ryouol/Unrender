"""Diagnostics must see committed outcomes and apply the primary scoring contract."""

import json

import pytest
from test_serving import CHART

from unrender.eval.failures import dump
from unrender.eval.ledger import RUN_CONTRACT, RunLedger, schedule_hash


def test_gallery_reads_ledger_and_does_not_credit_repaired_or_cached_output(tmp_path):
    schedule = [
        {
            "id": "chart",
            "image": str(tmp_path / "chart.png"),
            "image_sha256": "a" * 64,
            "gt": json.dumps(CHART),
            "meta": {},
        }
    ]
    metadata = {
        "run_contract": RUN_CONTRACT,
        "n_scheduled": 1,
        "schedule_sha256": schedule_hash(schedule),
    }
    ledger = RunLedger(tmp_path, metadata, schedule)
    try:
        path = ledger.export()
        ledger.dispatch("chart")
        ledger.complete(
            "chart",
            {"raw": "```json\n" + json.dumps(CHART) + "\n```", "pred": CHART, "status": "ok"},
        )
        text = dump(str(path), 1, 0.05).read_text()
        assert "Worst 1 predictions" in text and "cell acc 0%" in text
        assert "unparseable" in text
        # The portable file still contains the initial pending row.
        assert json.loads(path.read_text())["attempt"]["state"] == "pending"
    finally:
        ledger.close()


def test_historical_input_rejection_is_explicit_and_precedes_provider_work(tmp_path):
    from unrender.eval.dataset import load_eval_samples

    data = tmp_path / "test.jsonl"
    data.write_text(
        json.dumps(
            {
                "images": ["data/synthetic_v1/images/0002906.png"],
                "messages": [
                    {"role": "user", "content": ""},
                    {"role": "assistant", "content": json.dumps(CHART)},
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="historical repository-relative"):
        load_eval_samples(str(data))


@pytest.mark.parametrize("data", ["", "v0", "v1", "v2"])
def test_cloud_entrypoints_reject_historical_defaults_before_spawn(data):
    import modal_train

    with pytest.raises(ValueError, match="explicit current"):
        modal_train._evaluation_data_path(data)


@pytest.mark.parametrize("entrypoint", ["train", "train_model"])
@pytest.mark.parametrize("spec", ["v1:300", "common300"])
def test_chained_evaluation_rejects_before_training(entrypoint, spec, monkeypatch):
    import modal_train

    def unexpected(*args, **kwargs):
        pytest.fail("source validation or cloud work started before evaluation validation")

    monkeypatch.setattr(modal_train, "_training_source_paths", unexpected)
    fn = modal_train.train if entrypoint == "train" else modal_train.train_model.local
    with pytest.raises(ValueError, match="explicit current"):
        fn(eval_after=spec)
