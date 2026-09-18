"""Weighted causal CE normalized over a complete optimizer batch.

Objective: sum(weight * token CE) / sum(weight), ignoring shifted -100 labels.
The denominator covers every microbatch in an accumulation window, including a
short final window. Only the single-process Trainer lifecycle is supported.
"""

from __future__ import annotations

import math


def validate_numeric_weight(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("numeric loss weight must be finite and positive")
    return float(value)


def token_weights(labels, numeric_ids, weight):
    import torch

    labels = labels[..., 1:]
    ids = torch.as_tensor(numeric_ids, dtype=torch.long, device=labels.device)
    return torch.where(torch.isin(labels, ids), weight, 1.0) * (labels != -100)


def weighted_causal_loss(logits, labels, numeric_ids, weight, denominator=None):
    from torch.nn import functional as F

    labels = labels.to(logits.device)
    weights = token_weights(labels, numeric_ids, validate_numeric_weight(weight))
    ce = F.cross_entropy(
        logits[..., :-1, :].float().reshape(-1, logits.shape[-1]),
        labels[..., 1:].reshape(-1),
        ignore_index=-100,
        reduction="none",
    ).reshape(weights.shape)
    if denominator is None:
        denominator = weights.sum()
    if float(denominator) <= 0 or not math.isfinite(float(denominator)):
        raise ValueError("optimizer batch has no supervised tokens or invalid denominator")
    return (ce * weights).sum() / denominator


class AccumulatedWeightedLoss:
    """Mixin for Trainer.get_batch_samples -> training_step -> compute_loss.

    Transformers must not divide this already normalized objective by the number
    of microbatches again. model_accepts_loss_kwargs declares that normalization
    is handled here; kwargs are consumed here and never forwarded to the model.
    Actual Qwen/CUDA integration still requires its own canary.
    """

    def __init__(self, *args, numeric_ids=(), numeric_weight=1.0, **kwargs):
        self.numeric_ids = tuple(numeric_ids)
        self.numeric_weight = validate_numeric_weight(numeric_weight)
        super().__init__(*args, **kwargs)
        if self.args.world_size != 1 or self.args.n_gpu > 1 or self.is_deepspeed_enabled:
            raise ValueError("weighted accumulation requires a single-process non-DeepSpeed run")
        self.model_accepts_loss_kwargs = True

    def get_batch_samples(self, epoch_iterator, num_batches, device):
        samples, _ = super().get_batch_samples(epoch_iterator, num_batches, device)
        if not samples:
            return samples, None
        denominator = sum(
            token_weights(batch["labels"], self.numeric_ids, self.numeric_weight).sum().item()
            for batch in samples
        )
        if denominator <= 0:
            raise ValueError("optimizer batch has no supervised tokens")
        return samples, denominator

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        # Do not mutate a collated batch (prediction_step may use its labels).
        labels = inputs["labels"]
        outputs = model(**{key: value for key, value in inputs.items() if key != "labels"})
        loss = weighted_causal_loss(
            outputs.logits, labels, self.numeric_ids, self.numeric_weight, num_items_in_batch
        )
        return (loss, outputs) if return_outputs else loss
