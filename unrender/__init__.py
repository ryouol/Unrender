"""Unrender — recover the underlying data from chart images.

A specialized vision-language model (Qwen-VL + LoRA) fine-tuned to extract the
exact data behind a chart and return it as strict JSON, which is then validated
and exported to CSV.
"""

__version__ = "0.1.0"
