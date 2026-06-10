"""Degrade clean renders to look like real-world captures.

The synthetic->real gap is the project's #1 technical risk: a model trained on
pristine matplotlib output falls apart on a blurry screenshot of a PDF. These
augmentations (blur, JPEG recompression, rescale, slight rotation, brightness,
noise, grayscale) are applied probabilistically so the model sees the same chart
under many capture conditions. All implemented with Pillow + numpy — no native
deps, reliable on Apple Silicon.
"""

from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _jpeg(img: Image.Image, rng: random.Random) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.randint(30, 90))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _rescale(img: Image.Image, rng: random.Random) -> Image.Image:
    """Downscale then upscale to wreck fine detail like a low-res screenshot."""
    w, h = img.size
    factor = rng.uniform(0.4, 0.85)
    small = img.resize((max(1, int(w * factor)), max(1, int(h * factor))), Image.BILINEAR)
    return small.resize((w, h), Image.BILINEAR)


def _rotate(img: Image.Image, rng: random.Random) -> Image.Image:
    angle = rng.uniform(-2.5, 2.5)
    return img.rotate(angle, resample=Image.BILINEAR, expand=False, fillcolor=(255, 255, 255))


def _brightness_contrast(img: Image.Image, rng: random.Random) -> Image.Image:
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.8, 1.2))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.8, 1.2))
    return img


def _noise(img: Image.Image, rng: random.Random) -> Image.Image:
    arr = np.asarray(img).astype(np.int16)
    sigma = rng.uniform(4, 18)
    gen = np.random.default_rng(rng.randint(0, 2**31 - 1))
    arr = arr + gen.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _grayscale(img: Image.Image, _rng: random.Random) -> Image.Image:
    return img.convert("L").convert("RGB")


# (apply-probability, op) — tuned so most images get 1-3 mild degradations.
_OPS = [
    (0.40, lambda i, r: i.filter(ImageFilter.GaussianBlur(radius=r.uniform(0.4, 1.4)))),
    (0.50, _jpeg),
    (0.35, _rescale),
    (0.25, _rotate),
    (0.45, _brightness_contrast),
    (0.30, _noise),
    (0.12, _grayscale),
]


def augment_image(img: Image.Image, rng: random.Random) -> Image.Image:
    """Apply a random subset of degradations. Order is fixed; presence is random."""
    for prob, op in _OPS:
        if rng.random() < prob:
            img = op(img, rng)
    return img
