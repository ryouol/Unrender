"""Evaluation: score model predictions against ground truth, run baselines.

Design: model inference and scoring are decoupled. Each model run writes a
`predictions.jsonl` (with every raw response saved). The scorer reads those
files, so you can re-score for free whenever you tweak a metric — you never
re-call (re-pay) an API to change how you measure.
"""

from unrender.eval.metrics import aggregate, score_sample

__all__ = ["aggregate", "score_sample"]
