"""Canonical Trainer composition, imported lazily for CPU-only config tooling."""


def reviewed_trainer_type():
    from transformers import Trainer

    from unrender.train.checkpoints import SealBeforeRetention
    from unrender.train.loss import AccumulatedWeightedLoss

    class ReviewedTrainer(SealBeforeRetention, AccumulatedWeightedLoss, Trainer):
        pass

    return ReviewedTrainer
