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
import time
from collections.abc import Callable

# Each lab's flagship at eval time — using the strongest model is what makes the
# comparison unimpeachable. Model IDs move fast; pass --model to override (e.g.
# Gemini 3.5 Pro when it lands). Qwen3-VL-4B is the iteration base, 8B the launch
# base (the 2.5 family is skipped — same Unsloth path, strictly worse base).
DEFAULT_MODELS = {
    "anthropic": "claude-fable-5",
    "openai": "gpt-5.5",
    "gemini": "gemini-3.1-pro",
    "hf": "Qwen/Qwen3-VL-4B-Instruct",  # open baseline / your fine-tune (runs on the GPU box)
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
LAST_USAGE: dict = {}


def _set_usage(input_tokens, output_tokens):
    LAST_USAGE.clear()
    LAST_USAGE.update({"input_tokens": input_tokens, "output_tokens": output_tokens})


def openai_provider(image_path, prompt, model, gt_json=None, rng=None, *, timings=None) -> str:
    from openai import OpenAI

    client = OpenAI(max_retries=0, timeout=240)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{_b64(image_path)}"},
                },
            ],
        }
    ]
    resp = client.chat.completions.create(
        model=model, messages=messages, max_completion_tokens=4096
    )
    if timings is not None:
        timings["finish_reason"] = resp.choices[0].finish_reason
    u = getattr(resp, "usage", None)
    _set_usage(getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None))
    return resp.choices[0].message.content or ""


def anthropic_provider(image_path, prompt, model, gt_json=None, rng=None, *, timings=None) -> str:
    import anthropic

    client = anthropic.Anthropic(max_retries=0, timeout=240)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _b64(image_path),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    if timings is not None:
        timings["finish_reason"] = msg.stop_reason
    u = getattr(msg, "usage", None)
    _set_usage(getattr(u, "input_tokens", None), getattr(u, "output_tokens", None))
    if msg.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in msg.content if b.type == "text")


def gemini_provider(image_path, prompt, model, gt_json=None, rng=None, *, timings=None) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        http_options=types.HttpOptions(
            timeout=240_000, retry_options=types.HttpRetryOptions(attempts=1)
        )
    )
    with open(image_path, "rb") as f:
        data = f.read()
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type="image/png"), prompt],
    )
    if timings is not None:
        candidates = getattr(resp, "candidates", None) or []
        reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        timings["finish_reason"] = getattr(reason, "value", reason) or "unrecorded"
    um = getattr(resp, "usage_metadata", None)
    _set_usage(getattr(um, "prompt_token_count", None), getattr(um, "candidates_token_count", None))
    # resp.text raises (not returns falsy) when a candidate has no text part —
    # e.g. a safety block or non-STOP finish. Treat that as an empty prediction.
    try:
        return resp.text or ""
    except Exception:
        return ""


# Cache for the local HF model so we load weights once, not per image. Keyed by
# (model, revision) so a pinned base and an unpinned one never alias each other.
_HF_CACHE: dict[tuple, tuple] = {}

# Load-time config for the local HF provider (currently a pinned Hub `revision`),
# set by run_baselines before the loop. Separate from HF_GEN_CONFIG because it
# selects WHICH weights/processor load, not how they decode. Empty => Hub default.
# A pinned revision matters for the base-model control: the LoRA was trained on
# the Unsloth mirror, so its base must be pinned to the matching processor, not an
# unpinned Hub HEAD that can drift.
HF_MODEL_CONFIG: dict = {}

# Decoding config for the local HF provider, set by run_baselines from CLI flags
# (or modal_train) so the decoder sweep can vary decoding WITHOUT touching this
# call site. Empty dict => greedy (do_sample=False, 4096 cap), the control arm.
# Recognized keys: repetition_penalty, max_new_tokens, do_sample, temperature,
# top_p, no_repeat_ngram_size. Only hf_vlm_provider reads it.
HF_GEN_CONFIG: dict = {}


def generation_finish_reason(tokens, eos_token_id, max_output_tokens: int) -> str:
    """Conservatively classify a single generated sequence, before decoding.

    Reaching the cap wins over EOS: generation configs may force EOS at the limit.
    Without an observed EOS below the cap, completion is not established.
    """
    if len(tokens) >= max_output_tokens:
        return "length"
    eos_ids = eos_token_id if isinstance(eos_token_id, (list, tuple)) else [eos_token_id]
    if len(tokens) and int(tokens[-1]) in eos_ids:
        return "eos"
    return "unknown"


def hf_vlm_provider(image_path, prompt, model, gt_json=None, rng=None, *, timings=None) -> str:
    """Local open-model baseline (base Qwen-VL, your fine-tune, etc.).

    Runs where torch + transformers + CUDA and the model are available — i.e.
    the rented GPU box, not your Mac. Finalize the exact model class in Phase 3;
    this uses the standard transformers image-text-to-text pattern.
    """
    started = time.perf_counter()
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor

    imported = time.perf_counter()
    if timings is not None:
        timings["imports_seconds"] = imported - started
    rev = HF_MODEL_CONFIG.get("revision")
    key = (model, rev)
    if key not in _HF_CACHE:
        # Only pass `revision` when actually pinning. Passing revision=None
        # explicitly (vs omitting it) routes a LOCAL model dir through a hub-lookup
        # code path that, in current transformers, hits a 'dict has no model_type'
        # crash — the probe (which omits revision) loads the same merged model fine.
        rev_kw = {"revision": rev} if rev else {}
        proc = AutoProcessor.from_pretrained(model, trust_remote_code=False, **rev_kw)
        net = AutoModelForImageTextToText.from_pretrained(
            model,
            dtype="auto",
            device_map="auto",
            trust_remote_code=False,
            use_safetensors=True,
            **rev_kw,
        )
        _HF_CACHE[key] = (proc, net)
    proc, net = _HF_CACHE[key]
    loaded = time.perf_counter()
    if timings is not None:
        timings["model_load_seconds"] = loaded - imported

    messages = [
        {
            "role": "user",
            "content": [{"type": "image", "image": image_path}, {"type": "text", "text": prompt}],
        }
    ]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_kwargs = {}
    if max_pixels := HF_MODEL_CONFIG.get("max_pixels"):
        # Qwen's fast processor reads `size`, not an AutoProcessor max_pixels
        # override. Pass it per request so the cached processor stays immutable.
        image_kwargs["images_kwargs"] = {
            "size": {
                "shortest_edge": proc.image_processor.size.shortest_edge,
                "longest_edge": max_pixels,
            }
        }
    inputs = proc(
        text=[text],
        images=[Image.open(image_path).convert("RGB")],
        return_tensors="pt",
        # Saved training tokenizers may default to max_length=2048. Cutting an
        # expanded image token sequence makes Qwen3-VL reject the whole request.
        truncation=False,
        **image_kwargs,
    ).to(net.device)
    # 4096 matches the max_tokens the frontier providers get — a dense hard
    # chart's JSON can exceed 1024 tokens, and a tighter cap here would truncate
    # (and unfairly penalize) only the local model. HF_GEN_CONFIG (set by the
    # caller) overrides for the decoder sweep; an empty config is greedy decoding.
    gen_kwargs = {
        "max_new_tokens": HF_GEN_CONFIG.get("max_new_tokens") or 4096,
        "do_sample": bool(HF_GEN_CONFIG.get("do_sample", False)),
    }
    for k in ("repetition_penalty", "temperature", "top_p", "no_repeat_ngram_size"):
        if HF_GEN_CONFIG.get(k):
            gen_kwargs[k] = HF_GEN_CONFIG[k]
    preprocessed = time.perf_counter()
    if timings is not None:
        timings["preprocess_seconds"] = preprocessed - loaded
    with torch.no_grad():
        out = net.generate(**inputs, **gen_kwargs)
    trimmed = out[0][inputs["input_ids"].shape[1] :]
    decoded = proc.decode(trimmed, skip_special_tokens=True)
    if timings is not None:
        timings["generate_decode_seconds"] = time.perf_counter() - preprocessed
        timings["input_tokens"] = inputs["input_ids"].shape[1]
        timings["output_tokens"] = len(trimmed)
        timings["max_output_tokens"] = gen_kwargs["max_new_tokens"]
        timings["finish_reason"] = generation_finish_reason(
            trimmed, net.generation_config.eos_token_id, gen_kwargs["max_new_tokens"]
        )
    return decoded


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


PROVIDERS: dict[str, Callable] = {
    "openai": openai_provider,
    "anthropic": anthropic_provider,
    "gemini": gemini_provider,
    "hf": hf_vlm_provider,
    "perfect": perfect_provider,
    "noisy": noisy_provider,
}
