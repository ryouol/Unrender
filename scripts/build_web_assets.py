"""Build favicon derivatives from the approved brand master, never tenant files."""

from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / "unrender" / "product" / "static"


def main() -> None:
    icons = STATIC / "icons"
    with Image.open(icons / "brand-mark.png") as source:
        for name, size in (
            ("favicon-16.png", 16),
            ("favicon-32.png", 32),
            ("icon-192.png", 192),
            ("icon-512.png", 512),
        ):
            source.resize((size, size), Image.Resampling.LANCZOS).save(icons / name, optimize=True)
        source.resize((256, 256), Image.Resampling.LANCZOS).save(
            icons / "favicon.ico",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        touch_icon = Image.new("RGBA", source.size, "white")
        touch_icon.alpha_composite(source.convert("RGBA"))
        touch_icon.convert("RGB").resize((180, 180), Image.Resampling.LANCZOS).save(
            icons / "apple-touch-icon.png", optimize=True
        )
    with Image.open(icons / "brand-mark-dark.png") as source:
        for size in (16, 32):
            source.resize((size, size), Image.Resampling.LANCZOS).save(
                icons / f"favicon-dark-{size}.png", optimize=True
            )


if __name__ == "__main__":
    main()
