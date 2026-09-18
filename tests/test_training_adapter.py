"""Actual PEFT adapter save/retention/merge on a tiny random CPU model."""

import copy

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
peft = pytest.importorskip("peft")

from unrender.train.checkpoints import verify  # noqa: E402
from unrender.train.trainer import reviewed_trainer_type  # noqa: E402


def test_standard_adapter_checkpoint_and_higher_precision_merge(tmp_path):
    transformers.set_seed(7)
    config = transformers.GPT2Config(
        vocab_size=32,
        n_positions=16,
        n_embd=8,
        n_layer=1,
        n_head=1,
        resid_pdrop=0,
        embd_pdrop=0,
        attn_pdrop=0,
    )
    base = transformers.GPT2LMHeadModel(config)
    base_state = copy.deepcopy(base.state_dict())
    model = peft.get_peft_model(
        base,
        peft.LoraConfig(
            r=2,
            lora_alpha=2,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
    )
    rows = [{"input_ids": torch.tensor([1, 2, 3, 4]), "labels": torch.tensor([-100, 2, 3, 4])}] * 4
    trainer = reviewed_trainer_type()(
        model=model,
        train_dataset=rows,
        numeric_ids=(2,),
        numeric_weight=3,
        args=transformers.TrainingArguments(
            output_dir=str(tmp_path),
            use_cpu=True,
            max_steps=2,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=2,
            save_strategy="steps",
            save_steps=1,
            save_total_limit=1,
            report_to="none",
            disable_tqdm=True,
        ),
    )
    identity = {
        name: {"test_fixture": True}
        for name in (
            "base",
            "processor",
            "source_inputs",
            "hyperparameters",
            "runtime",
            "source_code",
        )
    }
    identity["runtime"]["world_size"] = 1
    trainer.checkpoint_identity = identity
    trainer.checkpoint_model_format = "lora"
    commits = []
    trainer.checkpoint_commit = lambda: commits.append(trainer.state.global_step)
    trainer.train()
    assert commits == [1, 2]
    assert not (tmp_path / "checkpoint-1").exists()
    checkpoint = tmp_path / "checkpoint-2"
    assert verify(checkpoint, identity, model_format="lora")["step"] == 2
    model.eval()
    tokens = torch.tensor([[1, 2, 3, 4]])
    expected = model(input_ids=tokens).logits.detach()
    reloaded_base = transformers.GPT2LMHeadModel(config)
    reloaded_base.load_state_dict(base_state)
    reloaded = peft.PeftModel.from_pretrained(reloaded_base, checkpoint, local_files_only=True)
    merged = reloaded.merge_and_unload(safe_merge=True).eval()
    torch.testing.assert_close(merged(input_ids=tokens).logits, expected, atol=1e-6, rtol=1e-5)
