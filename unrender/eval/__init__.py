"""Evaluation: score model predictions against ground truth, run baselines.

Design: model inference and scoring are decoupled. Each model run writes a
`predictions.jsonl` (with every raw response saved). The scorer reads those
files, so you can re-score for free whenever you tweak a metric — you never
re-call (re-pay) an API to change how you measure.
"""

__all__ = ["aggregate", "score_sample"]


def __getattr__(name):
    if name in __all__:
        from unrender.eval import metrics

        return getattr(metrics, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
