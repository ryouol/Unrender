"""Environment-backed product configuration with safe defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_MODEL_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MODEL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    """All mutable deployment choices live outside application code."""

    data_dir: Path
    environment: str = "development"
    base_url: str = "http://127.0.0.1:8000"
    extractor_backend: str = "replay"
    worker_enabled: bool = True
    allow_registration: bool = True
    seed_demo_account: bool = True
    session_ttl_hours: int = 24 * 7
    upload_ttl_hours: int = 24
    retention_days: int = 30
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 25
    max_image_pixels: int = 50_000_000
    rate_limit_per_minute: int = 120
    modal_app_name: str = "unrender"
    modal_function_name: str = "infer-one"
    modal_model_path: str = "runs/qwen3vl4b-table-fair/merged"
    modal_model_revision: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    credit_pack_size: int = 100
    initial_credits: int = 3

    @property
    def database_path(self) -> Path:
        return self.data_dir / "unrender.sqlite3"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    @property
    def billing_configured(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret and self.stripe_price_id)

    def validate(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("UNRENDER_ENV must be development, test, or production")
        if self.extractor_backend not in {"replay", "modal"}:
            raise ValueError("UNRENDER_EXTRACTOR must be replay or modal")
        parsed_base_url = urlsplit(self.base_url)
        if (
            parsed_base_url.scheme not in {"http", "https"}
            or not parsed_base_url.hostname
            or parsed_base_url.username
            or parsed_base_url.password
            or parsed_base_url.query
            or parsed_base_url.fragment
            or parsed_base_url.path not in {"", "/"}
        ):
            raise ValueError("UNRENDER_BASE_URL must be an HTTP(S) origin without a path")
        if self.environment == "production":
            if parsed_base_url.scheme != "https":
                raise ValueError("UNRENDER_BASE_URL must use HTTPS in production")
            if self.extractor_backend == "replay":
                raise ValueError("Replay extraction is demo-only and cannot run in production")
            if self.seed_demo_account:
                raise ValueError("UNRENDER_SEED_DEMO must be false in production")
            if self.allow_registration:
                raise ValueError("UNRENDER_ALLOW_REGISTRATION must be false in production")
            if not _MODEL_REPOSITORY.fullmatch(self.modal_model_path):
                raise ValueError(
                    "UNRENDER_MODAL_MODEL must be an immutable model repository in production"
                )
            if not _MODEL_COMMIT.fullmatch(self.modal_model_revision.casefold()):
                raise ValueError(
                    "UNRENDER_MODAL_REVISION must be a full 40-character commit in production"
                )
        if self.max_upload_bytes <= 0 or self.max_pdf_pages <= 0:
            raise ValueError("Upload limits must be positive")
        if self.max_image_pixels <= 0 or self.rate_limit_per_minute <= 0:
            raise ValueError("Image and request limits must be positive")
        if self.session_ttl_hours <= 0 or self.upload_ttl_hours <= 0 or self.retention_days <= 0:
            raise ValueError("Session, upload, and retention periods must be positive")
        if self.credit_pack_size <= 0 or self.initial_credits < 0:
            raise ValueError("Credit values must not be negative")
        stripe_values = (
            self.stripe_secret_key,
            self.stripe_webhook_secret,
            self.stripe_price_id,
        )
        if any(stripe_values) and not all(stripe_values):
            raise ValueError("Stripe test billing needs a secret, webhook secret, and price")
        if self.stripe_secret_key and not self.stripe_secret_key.startswith("sk_test_"):
            raise ValueError("Only Stripe test-mode secret keys are allowed")
        if self.stripe_webhook_secret and not self.stripe_webhook_secret.startswith("whsec_"):
            raise ValueError("STRIPE_WEBHOOK_SECRET must be a webhook signing secret")
        if self.stripe_price_id and not self.stripe_price_id.startswith("price_"):
            raise ValueError("STRIPE_PRICE_ID must reference a Price")

    @classmethod
    def from_env(cls) -> Settings:
        raw_dir = os.getenv("UNRENDER_DATA_DIR", ".unrender-data")
        settings = cls(
            data_dir=Path(raw_dir).expanduser().resolve(),
            environment=os.getenv("UNRENDER_ENV", "development").strip().lower(),
            base_url=os.getenv("UNRENDER_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            extractor_backend=os.getenv("UNRENDER_EXTRACTOR", "replay").strip().lower(),
            worker_enabled=_bool("UNRENDER_WORKER_ENABLED", True),
            allow_registration=_bool("UNRENDER_ALLOW_REGISTRATION", True),
            seed_demo_account=_bool("UNRENDER_SEED_DEMO", True),
            session_ttl_hours=_int("UNRENDER_SESSION_TTL_HOURS", 24 * 7),
            upload_ttl_hours=_int("UNRENDER_UPLOAD_TTL_HOURS", 24),
            retention_days=_int("UNRENDER_RETENTION_DAYS", 30),
            max_upload_bytes=_int("UNRENDER_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
            max_pdf_pages=_int("UNRENDER_MAX_PDF_PAGES", 25),
            max_image_pixels=_int("UNRENDER_MAX_IMAGE_PIXELS", 50_000_000),
            rate_limit_per_minute=_int("UNRENDER_RATE_LIMIT_PER_MINUTE", 120),
            modal_app_name=os.getenv("UNRENDER_MODAL_APP", "unrender"),
            modal_function_name=os.getenv("UNRENDER_MODAL_FUNCTION", "infer-one"),
            modal_model_path=os.getenv("UNRENDER_MODAL_MODEL", "runs/qwen3vl4b-table-fair/merged"),
            modal_model_revision=os.getenv("UNRENDER_MODAL_REVISION", ""),
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            stripe_price_id=os.getenv("STRIPE_PRICE_ID", ""),
            credit_pack_size=_int("UNRENDER_CREDIT_PACK_SIZE", 100),
            initial_credits=_int("UNRENDER_INITIAL_CREDITS", 3),
        )
        settings.validate()
        return settings
