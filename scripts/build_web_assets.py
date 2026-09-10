"""Build small public-web derivatives from the existing chart fixture, not tenant files."""

from pathlib import Path

from PIL import Image, ImageOps

STATIC = Path(__file__).resolve().parents[1] / "unrender" / "product" / "static"


def main() -> None:
    icons = STATIC / "icons"
    icons.mkdir(exist_ok=True)
    with Image.open(STATIC / "demo" / "budget-quarter.webp") as source:
        square = ImageOps.pad(source.convert("RGB"), (512, 512), color="#f4f3ee")
        for name, size in (
            ("favicon-16.png", 16),
            ("favicon-32.png", 32),
            ("apple-touch-icon.png", 180),
            ("icon-192.png", 192),
            ("icon-512.png", 512),
        ):
            square.resize((size, size), Image.Resampling.LANCZOS).save(icons / name, optimize=True)
        square.save(icons / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
        width = min(240, source.width)
        source.resize((width, round(source.height * width / source.width))).save(
            STATIC / "demo" / "budget-quarter-small.webp",
            quality=82,
            method=6,
        )


if __name__ == "__main__":
    main()
