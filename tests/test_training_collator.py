"""Real pinned processor checks; set UNRENDER_TEST_PROCESSOR to its local snapshot."""

import os

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from PIL import Image  # noqa: E402

from unrender.train.collator import ReviewedVisionCollator  # noqa: E402


@pytest.fixture(scope="module")
def processor():
    snapshot = os.environ.get("UNRENDER_TEST_PROCESSOR")
    if not snapshot:
        pytest.skip("explicit local pinned Qwen processor required; tests never download")
    return transformers.AutoProcessor.from_pretrained(snapshot, local_files_only=True)


def example(size, target):
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": Image.new("RGB", size, "white")},
                    {"type": "text", "text": "Extract this chart without guessing."},
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": target}]},
        ]
    }


@pytest.mark.parametrize("budget", [None, 512])
@pytest.mark.parametrize("padding", ["left", "right"])
def test_actual_qwen_grid_complete_target_and_padding(processor, budget, padding):
    old = processor.tokenizer.padding_side
    processor.tokenizer.padding_side = padding
    try:
        targets = ['{"series":[]}', '{"series":[{"points":[{"x":"日本","y":3.14159}]}]}']
        rows = [example((640, 480), targets[0]), example((1800, 1300), targets[1])]
        collator = ReviewedVisionCollator(processor, max_length=8192, image_tokens=budget)
        batch = collator(rows)
        assert (batch["labels"][batch["attention_mask"] == 0] == -100).all()
        for i, target in enumerate(targets):
            labels = batch["labels"][i]
            supervised = labels[labels != -100]
            assert (
                processor.tokenizer.decode(supervised, skip_special_tokens=True).strip() == target
            )
            assert collator.last_diagnostics[i]["assistant_target_verified"]
            if budget:
                assert collator.last_diagnostics[i]["image_tokens"] <= budget
        assert batch["image_grid_thw"].shape == (2, 3)
    finally:
        processor.tokenizer.padding_side = old


def test_oversized_sequence_is_rejected_not_truncated(processor):
    collator = ReviewedVisionCollator(processor, max_length=32, image_tokens=512)
    with pytest.raises(ValueError, match="truncation is forbidden"):
        collator([example((640, 480), '{"series":[]}')])
