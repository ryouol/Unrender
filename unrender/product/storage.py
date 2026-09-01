"""Validated source storage and page/crop rendering."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageOps, UnidentifiedImageError

from unrender.product.config import Settings


class InvalidUpload(ValueError):
    pass


# PDFium is not thread-safe across independent documents. Keep every native call
# behind one process-local mutex; HTTP admission limits bound how many callers can
# wait for it, while separate worker processes remain isolated.
_PDFIUM_LOCK = threading.RLock()


@dataclass(frozen=True)
class UploadInspection:
    mime_type: str
    page_count: int
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class StagedUpload:
    path: Path
    inspection: UploadInspection


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.storage_dir
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self._publication_fault_hook: Callable[[str], None] | None = None

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _private_directory(self, path: Path) -> None:
        missing: list[Path] = []
        candidate = path
        while candidate != self.root.parent and not candidate.exists():
            missing.append(candidate)
            candidate = candidate.parent
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for directory in reversed(missing):
            os.chmod(directory, 0o700)
            self._fsync_directory(directory)
            self._fsync_directory(directory.parent)
        os.chmod(path, 0o700)

    def _publication_checkpoint(self, stage: str) -> None:
        hook = self._publication_fault_hook
        if hook is not None:
            hook(stage)

    def inspect(self, content: bytes) -> UploadInspection:
        if not content:
            raise InvalidUpload("The uploaded file is empty")
        if len(content) > self.settings.max_upload_bytes:
            raise InvalidUpload(
                f"File exceeds the {self.settings.max_upload_bytes // (1024 * 1024)} MB limit"
            )
        digest = hashlib.sha256(content).hexdigest()
        if content.startswith(b"%PDF-"):
            pages = self._pdf_page_count(content)
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

    def stage_upload(self, source: BinaryIO, *, destination: Path | None = None) -> StagedUpload:
        """Copy one request spool to bounded private storage without a second RAM copy."""

        staging = self.root / "staging"
        self._private_directory(staging)
        if destination is None:
            descriptor, raw_path = tempfile.mkstemp(prefix="upload-", suffix=".tmp", dir=staging)
            path = Path(raw_path)
        else:
            if destination.parent != staging or destination.is_symlink():
                raise ValueError("Upload staging destination is outside private storage")
            descriptor = os.open(
                destination,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            path = destination
        self._fsync_directory(staging)
        total = 0
        digest = hashlib.sha256()
        try:
            with os.fdopen(descriptor, "wb") as staged_file:
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise InvalidUpload(
                            "File exceeds the "
                            f"{self.settings.max_upload_bytes // (1024 * 1024)} MB limit"
                        )
                    digest.update(chunk)
                    staged_file.write(chunk)
                staged_file.flush()
                os.fsync(staged_file.fileno())
            os.chmod(path, 0o600)
            self._fsync_directory(staging)
            self._publication_checkpoint("staging_file_durable")
            inspection = self._inspect_path(path, byte_size=total, digest=digest.hexdigest())
            return StagedUpload(path=path, inspection=inspection)
        except Exception:
            path.unlink(missing_ok=True)
            self._fsync_directory(staging)
            raise

    def _inspect_path(self, path: Path, *, byte_size: int, digest: str) -> UploadInspection:
        if byte_size <= 0:
            raise InvalidUpload("The uploaded file is empty")
        with path.open("rb") as source:
            header = source.read(5)
        if header == b"%PDF-":
            pages = self._pdf_page_count(path)
            return UploadInspection("application/pdf", pages, byte_size, digest)
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
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
        return UploadInspection(mime, 1, byte_size, digest)

    def _pdf_page_count(self, source: bytes | Path) -> int:
        with _PDFIUM_LOCK:
            try:
                with pdfium.PdfDocument(source) as document:
                    pages = len(document)
            except pdfium.PdfiumError as exc:
                if exc.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
                    raise InvalidUpload("Password-protected PDFs are not supported") from exc
                raise InvalidUpload("The PDF could not be opened") from exc
            except (OSError, ValueError) as exc:
                raise InvalidUpload("The PDF could not be opened") from exc
        if pages < 1:
            raise InvalidUpload("The PDF has no pages")
        if pages > self.settings.max_pdf_pages:
            raise InvalidUpload(
                f"PDF has {pages} pages; the limit is {self.settings.max_pdf_pages}"
            )
        return pages

    def commit_staged_upload(self, *, user_id: str, upload_id: str, staged: Path) -> Path:
        directory = self.root / "uploads" / user_id
        self._private_directory(directory)
        destination = directory / f"{upload_id}.source"
        if staged.parent != self.root / "staging" or staged.is_symlink():
            raise ValueError("Upload staging path is outside private storage")
        os.replace(staged, destination)
        os.chmod(destination, 0o600)
        with destination.open("rb") as published:
            os.fsync(published.fileno())
        self._fsync_directory(staged.parent)
        self._fsync_directory(directory)
        self._publication_checkpoint("upload_published")
        return destination

    def save_upload(self, *, user_id: str, upload_id: str, content: bytes) -> Path:
        staged = self.stage_upload(io.BytesIO(content))
        return self.commit_staged_upload(user_id=user_id, upload_id=upload_id, staged=staged.path)

    def copy_to_job(self, *, user_id: str, job_id: str, source: Path) -> Path:
        directory = self.root / "jobs" / user_id
        self._private_directory(directory)
        destination = directory / f"{job_id}.source"
        temporary = destination.with_suffix(".tmp")
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            self._fsync_directory(directory)
            self._publication_checkpoint("job_copy_published")
        except Exception:
            temporary.unlink(missing_ok=True)
            self._fsync_directory(directory)
            raise
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
            with _PDFIUM_LOCK:
                try:
                    with pdfium.PdfDocument(source) as document:
                        if not 0 <= page_index < len(document):
                            raise InvalidUpload("Selected PDF page does not exist")
                        page = document[page_index]
                        try:
                            width, height = page.get_size()
                            longest_edge = max(width, height)
                            if not 0 < longest_edge < float("inf"):
                                raise InvalidUpload("The selected PDF page has invalid dimensions")
                            scale = min(2.0, max_edge / longest_edge)
                            bitmap = page.render(scale=scale)
                            try:
                                image = bitmap.to_pil().convert("RGB").copy()
                                image.load()
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
                except InvalidUpload:
                    raise
                except pdfium.PdfiumError as exc:
                    if exc.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
                        raise InvalidUpload("Password-protected PDFs are not supported") from exc
                    raise InvalidUpload("The selected PDF page could not be rendered") from exc
                except (OSError, ValueError) as exc:
                    raise InvalidUpload("The selected PDF page could not be rendered") from exc
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
        existed = candidate.exists()
        candidate.unlink(missing_ok=True)
        if existed:
            self._fsync_directory(candidate.parent)

    def object_paths(self, *, older_than_seconds: int | None = None) -> list[Path]:
        """List only product-managed source objects for reconciliation."""

        paths: list[Path] = []
        for namespace in ("uploads", "jobs", "staging"):
            directory = self.root / namespace
            if directory.exists():
                for path in directory.rglob("*"):
                    if not path.is_file():
                        continue
                    if older_than_seconds is not None:
                        try:
                            if time.time() - path.stat().st_mtime < older_than_seconds:
                                continue
                        except FileNotFoundError:
                            continue
                    paths.append(path)
        return paths

    def ready(self) -> bool:
        """Verify the configured volume is writable without touching customer objects."""

        probe: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(prefix=".health-", dir=self.root)
            os.close(descriptor)
            probe = Path(raw_path)
            os.chmod(probe, 0o600)
            probe.unlink()
            return True
        except OSError:
            if probe is not None:
                with suppress(OSError):
                    probe.unlink(missing_ok=True)
            return False
