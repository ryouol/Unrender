"""Explicit Qwen vision batches: native processor, assistant-only labels, no truncation."""

from __future__ import annotations

from copy import deepcopy


class ReviewedVisionCollator:
    def __init__(self, processor, *, max_length: int, image_tokens: int | None = None):
        if type(max_length) is not int or max_length <= 0:
            raise ValueError("max_length must be positive")
        if image_tokens is not None and (type(image_tokens) is not int or image_tokens <= 0):
            raise ValueError("image_tokens must be positive or None for the full processor input")
        self.processor = processor
        self.max_length = max_length
        self.image_tokens = image_tokens
        self.last_diagnostics = []

    def __call__(self, examples):
        import torch

        processor = self.processor
        full, prefixes, images, targets = [], [], [], []
        for example in examples:
            messages = example["messages"]
            if len(messages) != 2 or [m["role"] for m in messages] != ["user", "assistant"]:
                raise ValueError("training requires one user image turn and one assistant target")
            image_items = [c["image"] for c in messages[0]["content"] if c["type"] == "image"]
            answer = messages[1]["content"]
            if len(image_items) != 1 or len(answer) != 1 or answer[0]["type"] != "text":
                raise ValueError("one image and one complete text target are required")
            targets.append(answer[0]["text"])
            images.extend(image_items)
            full.append(
                processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
            )
            prefixes.append(
                processor.apply_chat_template(
                    messages[:1], tokenize=False, add_generation_prompt=True
                )
            )
        image_kwargs = {}
        if self.image_tokens is not None:
            factor = processor.image_processor.patch_size * processor.image_processor.merge_size
            image_kwargs = {
                "images_kwargs": {
                    "size": {
                        "shortest_edge": processor.image_processor.size.shortest_edge,
                        "longest_edge": self.image_tokens * factor**2,
                    }
                }
            }
        batch = processor(
            text=full,
            images=images,
            padding=True,
            truncation=False,
            return_tensors="pt",
            **deepcopy(image_kwargs),
        )
        prompts = processor(
            text=prefixes,
            images=images,
            padding=True,
            truncation=False,
            return_tensors="pt",
            **deepcopy(image_kwargs),
        )
        if not torch.equal(batch["image_grid_thw"], prompts["image_grid_thw"]):
            raise ValueError("image grid changed between prompt and target")
        image_id = processor.tokenizer.convert_tokens_to_ids(processor.image_token)
        batch["labels"] = torch.full_like(batch["input_ids"], -100)
        diagnostics = []
        for i, target in enumerate(targets):
            active = batch["attention_mask"][i].bool()
            ids = batch["input_ids"][i][active]
            prefix = prompts["input_ids"][i][prompts["attention_mask"][i].bool()]
            if len(ids) > self.max_length:
                raise ValueError(
                    f"complete training sequence has {len(ids)} tokens, "
                    f"above {self.max_length}; truncation is forbidden"
                )
            if len(prefix) >= len(ids) or not torch.equal(ids[: len(prefix)], prefix):
                raise ValueError("assistant boundary is not an exact prefix of the full input")
            answer = ids[len(prefix) :]
            decoded = processor.tokenizer.decode(answer, skip_special_tokens=True)
            if decoded.strip() != target.strip():
                raise ValueError("supervised labels do not retain the complete assistant target")
            grid = batch["image_grid_thw"][i]
            count = int(grid.prod().item()) // processor.image_processor.merge_size**2
            if int((ids == image_id).sum()) != count:
                raise ValueError("image token sequence does not match the actual image grid")
            if self.image_tokens is not None and count > self.image_tokens:
                raise ValueError("actual image tokens exceed the declared budget")
            positions = active.nonzero().flatten()[len(prefix) :]
            batch["labels"][i, positions] = answer
            diagnostics.append(
                {
                    "sequence_tokens": len(ids),
                    "supervised_tokens": len(answer),
                    "image_tokens": count,
                    "image_grid_thw": grid.tolist(),
                    "truncated": False,
                    "assistant_target_verified": True,
                }
            )
        self.last_diagnostics = diagnostics
        return batch
