"""A scheduled provider call cannot secretly issue an application-level retry."""

import sys
from types import SimpleNamespace

import pytest

from unrender.eval import providers


@pytest.mark.parametrize("fails", [True, False])
def test_openai_single_attempt_completion_and_options(tmp_path, monkeypatch, fails):
    image = tmp_path / "x.png"
    image.write_bytes(b"test")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if fails:
            raise ValueError("max_tokens unsupported")
        return SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="partial"))
            ],
        )

    def client(**kwargs):
        assert kwargs == {"max_retries": 0, "timeout": 240}
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=client))
    timing = {}
    if fails:
        with pytest.raises(ValueError):
            providers.openai_provider(str(image), "prompt", "model", timings=timing)
    else:
        assert providers.openai_provider(str(image), "prompt", "model", timings=timing) == "partial"
        assert timing["finish_reason"] == "length"
    assert len(calls) == 1
    assert calls[0]["max_completion_tokens"] == 4096
