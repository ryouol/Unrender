"""Run with the CPU training environment; no model downloads or CUDA required."""

import math

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from unrender.train.loss import (  # noqa: E402
    AccumulatedWeightedLoss,
    validate_numeric_weight,
    weighted_causal_loss,
)


@pytest.mark.parametrize("weight", [0, -1, math.nan, math.inf, True])
def test_invalid_numeric_weight(weight):
    with pytest.raises(ValueError, match="finite and positive"):
        validate_numeric_weight(weight)


def labels():
    return torch.tensor(
        [[-100, 1, -100, -100, -100, -100, -100, -100], [-100, 2, 2, 2, 2, 2, 2, 2]]
    )


def test_partition_invariance_and_weight_one_ce():
    parameters = torch.tensor([0.1, 0.4, -0.7, 0.2, 0.5, -0.3], requires_grad=True)
    logits = parameters.expand(2, 8, 6)
    y = labels()
    joint = weighted_causal_loss(logits, y, (1,), 3)
    joint.backward()
    expected = parameters.grad.clone()
    parameters.grad = None
    parts = [weighted_causal_loss(logits[i : i + 1], y[i : i + 1], (1,), 3, 10) for i in range(2)]
    sum(parts).backward()
    torch.testing.assert_close(sum(parts), joint)
    torch.testing.assert_close(parameters.grad, expected)
    ordinary = torch.nn.functional.cross_entropy(
        logits[:, :-1].reshape(-1, 6), y[:, 1:].reshape(-1), ignore_index=-100
    )
    torch.testing.assert_close(weighted_causal_loss(logits, y, (1,), 1), ordinary)
    with pytest.raises(ValueError, match="no supervised"):
        weighted_causal_loss(logits, torch.full_like(y, -100), (1,), 3)


def test_actual_trainer_optimizer_gradients_match_including_tail(tmp_path):
    from transformers.modeling_outputs import CausalLMOutput

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.values = torch.nn.Parameter(torch.tensor([0.1, 0.4, -0.7, 0.2, 0.5, -0.3]))

        def forward(self, input_ids):
            return CausalLMOutput(logits=self.values.expand(*input_ids.shape, 6))

    class RecordingSGD(torch.optim.SGD):
        def __init__(self, parameters):
            super().__init__(parameters, lr=0.1)
            self.gradients = []

        def step(self, closure=None):
            self.gradients.append(self.param_groups[0]["params"][0].grad.clone())
            return super().step(closure)

    class Trainer(AccumulatedWeightedLoss, transformers.Trainer):
        pass

    rows = [
        {"input_ids": torch.zeros(8, dtype=torch.long), "labels": y}
        for y in [*labels(), labels()[1]]
    ]

    def run(batch_size, accumulation):
        model = Model()
        optimizer = RecordingSGD(model.parameters())
        trainer = Trainer(
            model=model,
            train_dataset=rows,
            numeric_ids=(1,),
            numeric_weight=3,
            optimizers=(optimizer, None),
            args=transformers.TrainingArguments(
                output_dir=str(tmp_path / f"{batch_size}"),
                use_cpu=True,
                max_steps=2,
                per_device_train_batch_size=batch_size,
                gradient_accumulation_steps=accumulation,
                report_to="none",
                save_strategy="no",
                max_grad_norm=0,
                lr_scheduler_type="constant",
                remove_unused_columns=False,
                disable_tqdm=True,
                seed=7,
            ),
        )
        trainer.train()
        return model.values.detach(), optimizer.gradients

    whole, whole_grads = run(2, 1)
    split, split_grads = run(1, 2)
    assert len(whole_grads) == len(split_grads) == 2
    for a, b in zip(whole_grads, split_grads, strict=True):
        torch.testing.assert_close(a, b)
    torch.testing.assert_close(whole, split)
