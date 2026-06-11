"""Model providers: take an image + prompt, return the raw text response.

Every provider has the same signature so run_baselines.py can treat them
uniformly:  provider(image_path, prompt, model, gt_json=None, rng=None) -> str

SDK imports are lazy (inside each function) so importing this module on a
machine without the SDKs (e.g. your Mac, for scorer development) still works —
you only need a provider's SDK installed when you actually call it.

`perfect` and `noisy` are NOT real models — they fabricate predictions from the
ground truth so the scorer can be verified end-to-end without spending on APIs.
Never report them as baselines.
"""

from __future__ import annotations

import base64
import random
from typing import Callable, Dict, Optional

# Each lab's flagship at eval time — using the strongest model is what makes the
# comparison unimpeachable. Model IDs move fast; pass --model to override (e.g.
# Gemini 3.5 Pro when it lands). Qwen3-VL-4B is the iteration base, 8B the launch
# base (the 2.5 family is skipped — same Unsloth path, strictly worse base).
DEFAULT_MODELS = {
    "anthropic": "claude-fable-5",
    "openai": "gpt-5.5",
    "gemini": "gemini-3.1-pro",
    "hf": "Qwen/Qwen3-VL-4B-Instruct",        # open baseline / your fine-tune (runs on the GPU box)
    "perfect": "oracle",
    "noisy": "oracle-noisy",
}

STALE_DEFAULT: set = set()  # warn if a default is known-stale; pass --model to override any


def _b64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# Token usage from the most recent real provider call — observability only, read
# by run_baselines for the cost projection. Does NOT affect the request sent, the
# prompt, the parsing, or the scoring.
LAST_USAGE: Dict = {}


def _set_usage(input_tokens, output_tokens):
    LAST_USAGE.clear()
    LAST_USAGE.update({"input_tokens": input_tokens, "output_tokens": output_tokens})


def openai_provider(image_path, prompt, model, gt_json=None, rng=None) -> str:
    from openai import OpenAI

    client = OpenAI()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(image_path)}"}},
    ]}]
    try:
        resp = client.chat.completions.create(model=model, messages=messages, max_tokens=4096)
    except Exception as e:
        # Only retry the specific "this model rejects max_tokens" case. Real
        # failures (auth, rate limit, network) must propagate, not silently
        # trigger a second identical (paid) call that masks the true error.
        if "max_tokens" not in str(e).lower():
            raise
        resp = client.chat.completions.create(model=model, messages=messages)
    u = getattr(resp, "usage", None)
    _set_usage(getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None))
    return resp.choices[0].message.content or ""


def anthropic_provider(image_path, prompt, model, gt_json=None, rng=None) -> str:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(image_path)}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    u = getattr(msg, "usage", None)
    _set_usage(getattr(u, "input_tokens", None), getattr(u, "output_tokens", None))
    if msg.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in msg.content if b.type == "text")


def gemini_provider(image_path, prompt, model, gt_json=None, rng=None) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GOOGLE_API_KEY / GEMINI_API_KEY
    with open(image_path, "rb") as f:
        data = f.read()
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type="image/png"), prompt],
    )
    um = getattr(resp, "usage_metadata", None)
    _set_usage(getattr(um, "prompt_token_count", None), getattr(um, "candidates_token_count", None))
    # resp.text raises (not returns falsy) when a candidate has no text part —
    # e.g. a safety block or non-STOP finish. Treat that as an empty prediction.
    try:
        return resp.text or ""
    except Exception:
        return ""


# Cache for the local HF model so we load weights once, not per image.
_HF_CACHE: Dict[str, tuple] = {}


def hf_vlm_provider(image_path, prompt, model, gt_json=None, rng=None) -> str:
    """Local open-model baseline (base Qwen-VL, your fine-tune, etc.).

    Runs where torch + transformers + CUDA and the model are available — i.e.
    the rented GPU box, not your Mac. Finalize the exact model class in Phase 3;
    this uses the standard transformers image-text-to-text pattern.
    """
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from PIL import Image

    if model not in _HF_CACHE:
        proc = AutoProcessor.from_pretrained(model, trust_remote_code=True)
        net = AutoModelForImageTextToText.from_pretrained(
            model, torch_dtype="auto", device_map="auto", trust_remote_code=True
        )
        _HF_CACHE[model] = (proc, net)
    proc, net = _HF_CACHE[model]

    messages = [{"role": "user", "content": [
        {"type": "image", "image": image_path}, {"type": "text", "text": prompt}]}]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = proc(text=[text], images=[Image.open(image_path).convert("RGB")], return_tensors="pt").to(net.device)
    with torch.no_grad():
        # 4096 matches the max_tokens the frontier providers get — a dense hard
        # chart's JSON can exceed 1024 tokens, and a tighter cap here would
        # truncate (and unfairly penalize) only the local model.
        out = net.generate(**inputs, max_new_tokens=4096, do_sample=False)
    trimmed = out[0][inputs["input_ids"].shape[1]:]
    return proc.decode(trimmed, skip_special_tokens=True)


# --- Mock providers for verifying the scorer (no API, no cost) ---------------

def perfect_provider(image_path, prompt, model, gt_json=None, rng=None) -> str:
    """Returns the ground truth verbatim — should score ~100%."""
    return gt_json or ""


def noisy_provider(image_path, prompt, model, gt_json=None, rng=None) -> str:
    """Perturbs the GT (jitter ~30% of values, occasionally drop a point) so
    metrics land strictly between 0 and 1 — verifies they actually discriminate."""
    from unrender.schema.chart_schema import ChartData, canonical_json

    rng = rng or random.Random(0)
    d = ChartData.model_validate_json(gt_json)
    for s in d.series:
        for p in s.points:
            if rng.random() < 0.3:
                p.y = round(p.y * (1 + rng.uniform(-0.2, 0.2)), 3)
        if rng.random() < 0.1 and len(s.points) > 1:
            s.points.pop()
    return canonical_json(d)


PROVIDERS: Dict[str, Callable] = {
    "openai": openai_provider,
    "anthropic": anthropic_provider,
    "gemini": gemini_provider,
    "hf": hf_vlm_provider,
    "perfect": perfect_provider,
    "noisy": noisy_provider,
}
