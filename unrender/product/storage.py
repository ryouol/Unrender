"""Validated source storage and page/crop rendering."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

from unrender.product.config import Settings


class InvalidUpload(ValueError):
    pass


@dataclass(frozen=True)
class UploadInspection:
    mime_type: str
    page_count: int
    byte_size: int
    sha256: str


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.storage_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def inspect(self, content: bytes) -> UploadInspection:
        if not content:
            raise InvalidUpload("The uploaded file is empty")
        if len(content) > self.settings.max_upload_bytes:
            raise InvalidUpload(
                f"File exceeds the {self.settings.max_upload_bytes // (1024 * 1024)} MB limit"
            )
        digest = hashlib.sha256(content).hexdigest()
        if content.startswith(b"%PDF-"):
            try:
                document = pymupdf.open(stream=content, filetype="pdf")
            except (pymupdf.FileDataError, RuntimeError) as exc:
                raise InvalidUpload("The PDF could not be opened") from exc
            try:
                if document.needs_pass:
                    raise InvalidUpload("Password-protected PDFs are not supported")
                pages = document.page_count
                if pages < 1:
                    raise InvalidUpload("The PDF has no pages")
                if pages > self.settings.max_pdf_pages:
                    raise InvalidUpload(
                        f"PDF has {pages} pages; the limit is {self.settings.max_pdf_pages}"
                    )
            finally:
                document.close()
            return UploadInspection("application/pdf", pages, len(content), digest)

        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                image_format = (image.format or "").upper()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise InvalidUpload("Upload a PNG, JPEG, WebP, or PDF file") from exc
        if image_format not in {"PNG", "JPEG", "WEBP"}:
            raise InvalidUpload("Upload a PNG, JPEG, WebP, or PDF file")
        if width < 32 or height < 32:
            raise InvalidUpload("Image is too small to extract")
        if width * height > self.settings.max_image_pixels:
            raise InvalidUpload("Image dimensions exceed the safety limit")
        mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[image_format]
        return UploadInspection(mime, 1, len(content), digest)

    def save_upload(self, *, user_id: str, upload_id: str, content: bytes) -> Path:
        directory = self.root / "uploads" / user_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{upload_id}.source"
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(content)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        return destination

    def copy_to_job(self, *, user_id: str, job_id: str, source: Path) -> Path:
        directory = self.root / "jobs" / user_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{job_id}.source"
        temporary = destination.with_suffix(".tmp")
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        return destination

    def page_png(
        self,
        *,
        source: Path,
        mime_type: str,
        page_index: int,
        crop: dict[str, float] | None = None,
        max_edge: int = 2200,
    ) -> bytes:
        if mime_type == "application/pdf":
            document = pymupdf.open(source)
            try:
                if not 0 <= page_index < document.page_count:
                    raise InvalidUpload("Selected PDF page does not exist")
                page = document.load_page(page_index)
                scale = min(2.0, max_edge / max(page.rect.width, page.rect.height))
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            finally:
                document.close()
        else:
            if page_index != 0:
                raise InvalidUpload("Images contain one page")
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.load()

        if crop:
            x = float(crop["x"])
            y = float(crop["y"])
            width = float(crop["width"])
            height = float(crop["height"])
            if not (
                0 <= x < 1
                and 0 <= y < 1
                and 0.05 <= width <= 1
                and 0.05 <= height <= 1
                and x + width <= 1.000001
                and y + height <= 1.000001
            ):
                raise InvalidUpload("Crop must stay within the source page")
            left = round(x * image.width)
            top = round(y * image.height)
            right = round((x + width) * image.width)
            bottom = round((y + height) * image.height)
            image = image.crop((left, top, right, bottom))

        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def delete(self, path: str | Path) -> None:
        candidate = Path(path).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ValueError("Refusing to delete a path outside product storage")
        candidate.unlink(missing_ok=True)
