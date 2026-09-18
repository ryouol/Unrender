"""Regression coverage for image-token integrity and verified warm-model reuse."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image


def test_hf_preserves_all_image_tokens_past_training_tokenizer_limit(tmp_path, monkeypatch):
    from unrender.eval import providers

    image = tmp_path / "large.png"
    Image.new("RGB", (1920, 1120)).save(image)

    class Inputs(dict):
        def to(self, device):
            return self

    class Processor:
        image_processor = SimpleNamespace(
            size=SimpleNamespace(shortest_edge=65536, longest_edge=16777216)
        )

        def apply_chat_template(self, *args, **kwargs):
            return "expanded image prompt"

        def __call__(self, **kwargs):
            # Reproduce the saved training tokenizer's implicit truncation.
            if kwargs.get("truncation", True):
                raise ValueError("Mismatch in image token count: 2044 versus 2100")
            assert kwargs["images_kwargs"]["size"] == {
                "shortest_edge": 65536,
                "longest_edge": 524288,
            }
            assert self.image_processor.size.longest_edge == 16777216
            return Inputs(input_ids=np.zeros((1, 2500), dtype=int))

        def decode(self, tokens, **kwargs):
            assert list(tokens) == [7]
            return "complete output"

    class Model:
        device = "cpu"
        generation_config = SimpleNamespace(eos_token_id=7)

        def generate(self, **kwargs):
            assert kwargs["input_ids"].shape[1] == 2500
            assert kwargs["do_sample"] is False
            assert kwargs["max_new_tokens"] == 4096
            return [np.array([0] * 2500 + [7])]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=nullcontext))
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoModelForImageTextToText=None,
            AutoProcessor=None,
        ),
    )
    monkeypatch.setattr(providers, "_HF_CACHE", {("model", None): (Processor(), Model())})
    monkeypatch.setattr(providers, "HF_MODEL_CONFIG", {"max_pixels": 524288})
    monkeypatch.setattr(providers, "HF_GEN_CONFIG", {})
    timings = {}
    assert (
        providers.hf_vlm_provider(str(image), "extract", "model", timings=timings)
        == "complete output"
    )
    assert timings["finish_reason"] == "eos"
    assert timings["output_tokens"] == 1
    assert timings["max_output_tokens"] == 4096


def test_warm_verification_is_bound_to_release_and_exact_loaded_objects(monkeypatch):
    import importlib.metadata

    import modal_train
    from unrender.eval import providers

    monkeypatch.setattr(modal_train, "_INFER_VERIFIED_MODELS", {})
    monkeypatch.setattr(providers, "_HF_CACHE", {})
    monkeypatch.setattr(
        importlib.metadata, "version", lambda p: modal_train.INFER_DIRECT_DEPENDENCIES.get(p, "1")
    )
    verified = []

    def verify(model, revision, digest):
        verified.append((model, revision, digest))
        if digest == "bad":
            raise ValueError("Digest mismatch")
        return "/verified/" + digest

    def infer(image, prompt, snapshot, **kwargs):
        kwargs["timings"].update(finish_reason="eos", output_tokens=100, max_output_tokens=4096)
        providers._HF_CACHE.setdefault((snapshot, None), (object(), object()))
        return '{"chart_type":"bar","series":[{"points":[{"x":"A","y":1}]}]}'

    monkeypatch.setattr(modal_train, "_production_model_snapshot", verify)
    monkeypatch.setattr(providers, "hf_vlm_provider", infer)
    args = (b"image", "approved/model", "a" * 40, "b" * 64)
    first = modal_train.infer_one.local(*args)
    second = modal_train.infer_one.local(*args)
    assert first == second
    assert len(verified) == 1
    snapshot = "/verified/" + "b" * 64
    providers._HF_CACHE[(snapshot, None)] = (object(), object())
    modal_train.infer_one.local(*args)
    assert len(verified) == 2  # replaced model must be reverified
    providers._HF_CACHE.clear()
    modal_train.infer_one.local(*args)
    assert len(verified) == 3  # eviction must be reverified
    modal_train.infer_one.local(b"image", "approved/model", "c" * 40, "b" * 64)
    assert len(verified) == 4  # revision change never aliases another release
    with pytest.raises(ValueError, match="Digest mismatch"):
        modal_train.infer_one.local(b"image", "approved/model", "a" * 40, "bad")
    assert len(verified) == 5
