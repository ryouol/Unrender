"""Environment-backed product configuration with safe defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_MODEL_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MODEL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PROVIDER_RELEASE = re.compile(r"^[0-9a-f]{64}$")


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
    max_recovery_attempts: int = 1
    worker_lease_seconds: int = 45
    worker_heartbeat_seconds: int = 10
    worker_shutdown_timeout_seconds: int = 30
    allow_registration: bool = True
    seed_demo_account: bool = True
    session_ttl_hours: int = 24 * 7
    upload_ttl_hours: int = 24
    retention_days: int = 30
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 25
    max_image_pixels: int = 50_000_000
    max_user_storage_bytes: int = 250 * 1024 * 1024
    max_unattached_uploads: int = 5
    max_upload_records_per_user: int = 1_000
    max_jobs_per_user: int = 1_000
    max_upload_bytes_per_minute: int = 40 * 1024 * 1024
    rate_limit_per_minute: int = 120
    max_result_versions_per_job: int = 25
    max_history_bytes_per_user: int = 16 * 1024 * 1024
    max_result_json_bytes: int = 1_000_000
    max_storage_bytes_global: int = 10 * 1024 * 1024 * 1024
    min_free_storage_bytes: int = 256 * 1024 * 1024
    database_headroom_bytes: int = 128 * 1024 * 1024
    storage_reservation_ttl_seconds: int = 60 * 60
    max_sessions_per_user: int = 10
    max_active_api_keys_per_user: int = 10
    max_api_key_records_per_user: int = 100
    max_audit_events_per_job: int = 500
    max_audit_events_per_user: int = 5_000
    audit_retention_days: int = 90
    max_credit_ledger_records_per_user: int = 10_000
    max_database_rows_per_user: int = 30_000
    max_database_rows_global: int = 500_000
    mandatory_database_rows_per_user: int = 64
    mandatory_database_rows_global: int = 512
    max_billing_events_global: int = 100_000
    max_provider_attempts_per_job: int = 100
    idempotency_ttl_hours: int = 24 * 30
    idempotency_tombstone_days: int = 365
    max_idempotency_records_per_user: int = 10_000
    auth_rate_limit_per_minute: int = 10
    max_concurrent_auth_requests: int = 2
    max_concurrent_expensive_requests: int = 4
    provider_failure_limit_per_user_hour: int = 5
    provider_failure_limit_global_hour: int = 50
    reconciliation_grace_seconds: int = 300
    modal_app_name: str = "unrender"
    modal_function_name: str = "infer_one"
    modal_model_path: str = "runs/qwen3vl4b-table-fair/merged"
    modal_model_revision: str = ""
    modal_model_digest: str = ""
    modal_provider_release: str = ""
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

    @property
    def result_publication_reservation_bytes(self) -> int:
        """Worst-case version/current/original/raw publication for one provider attempt."""

        return self.max_result_json_bytes * 4

    @property
    def result_request_bytes(self) -> int:
        """Transport allowance for one valid result plus its JSON request envelope."""

        return self.max_result_json_bytes + 64 * 1024

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
            if not self.worker_enabled:
                raise ValueError("UNRENDER_WORKER_ENABLED must be true in production")
            if self.modal_function_name != "infer_one":
                raise ValueError("UNRENDER_MODAL_FUNCTION must be infer_one in production")
            if not _MODEL_REPOSITORY.fullmatch(self.modal_model_path):
                raise ValueError(
                    "UNRENDER_MODAL_MODEL must be an immutable model repository in production"
                )
            if not _MODEL_COMMIT.fullmatch(self.modal_model_revision.casefold()):
                raise ValueError(
                    "UNRENDER_MODAL_REVISION must be a full 40-character commit in production"
                )
            if not _PROVIDER_RELEASE.fullmatch(self.modal_model_digest.casefold()):
                raise ValueError(
                    "UNRENDER_MODAL_MODEL_DIGEST must be a 64-character model-manifest digest "
                    "in production"
                )
            if not _PROVIDER_RELEASE.fullmatch(self.modal_provider_release.casefold()):
                raise ValueError(
                    "UNRENDER_MODAL_PROVIDER_RELEASE must be a 64-character release digest "
                    "in production"
                )
        if self.max_upload_bytes <= 0 or self.max_pdf_pages <= 0:
            raise ValueError("Upload limits must be positive")
        if self.max_image_pixels <= 0 or self.rate_limit_per_minute <= 0:
            raise ValueError("Image and request limits must be positive")
        if self.max_user_storage_bytes < self.max_upload_bytes:
            raise ValueError("UNRENDER_MAX_USER_STORAGE_BYTES must allow at least one upload")
        if self.max_unattached_uploads <= 0 or self.max_upload_bytes_per_minute <= 0:
            raise ValueError("Tenant upload limits must be positive")
        if self.max_upload_records_per_user <= 0 or self.max_jobs_per_user <= 0:
            raise ValueError("Tenant record limits must be positive")
        if (
            self.max_result_versions_per_job <= 0
            or self.max_history_bytes_per_user < self.max_result_json_bytes
            or self.max_result_json_bytes <= 0
        ):
            raise ValueError("Result-history limits must be positive")
        if (
            self.max_storage_bytes_global
            < self.database_headroom_bytes
            + (self.max_upload_bytes * 2)
            + self.result_publication_reservation_bytes
            or self.min_free_storage_bytes < 0
            or self.database_headroom_bytes <= 0
            or self.storage_reservation_ttl_seconds <= 0
        ):
            raise ValueError("Global storage and free-space reserves are inconsistent")
        if (
            self.idempotency_ttl_hours <= 0
            or self.idempotency_tombstone_days <= 0
            or self.max_idempotency_records_per_user <= 0
        ):
            raise ValueError("Idempotency limits must be positive")
        bounded_state = (
            self.max_sessions_per_user,
            self.max_active_api_keys_per_user,
            self.max_api_key_records_per_user,
            self.max_audit_events_per_job,
            self.max_audit_events_per_user,
            self.audit_retention_days,
            self.max_credit_ledger_records_per_user,
            self.max_database_rows_per_user,
            self.max_database_rows_global,
            self.max_billing_events_global,
            self.max_provider_attempts_per_job,
        )
        if any(value <= 0 for value in bounded_state):
            raise ValueError("Database-state limits must be positive")
        if (
            not 0 < self.mandatory_database_rows_per_user < self.max_database_rows_per_user
            or not 0 < self.mandatory_database_rows_global < self.max_database_rows_global
        ):
            raise ValueError("Mandatory database-row reserves must fit inside hard row limits")
        if self.max_credit_ledger_records_per_user < 3:
            raise ValueError("Credit-ledger capacity must leave room for reserve/refund pairs")
        if self.max_active_api_keys_per_user > self.max_api_key_records_per_user:
            raise ValueError("Active API-key limit cannot exceed retained-key limit")
        if self.max_audit_events_per_job > self.max_audit_events_per_user:
            raise ValueError("Per-job audit limit cannot exceed the tenant audit limit")
        admission_limits = (
            self.auth_rate_limit_per_minute,
            self.max_concurrent_auth_requests,
            self.max_concurrent_expensive_requests,
            self.provider_failure_limit_per_user_hour,
            self.provider_failure_limit_global_hour,
        )
        if any(value <= 0 for value in admission_limits):
            raise ValueError("Admission and provider limits must be positive")
        if self.provider_failure_limit_per_user_hour > self.provider_failure_limit_global_hour:
            raise ValueError("Tenant provider-failure limit cannot exceed the global limit")
        if self.session_ttl_hours <= 0 or self.upload_ttl_hours <= 0 or self.retention_days <= 0:
            raise ValueError("Session, upload, and retention periods must be positive")
        if self.credit_pack_size <= 0 or self.initial_credits < 0:
            raise ValueError("Credit values must not be negative")
        if not 0 <= self.max_recovery_attempts <= 10:
            raise ValueError("UNRENDER_MAX_RECOVERY_ATTEMPTS must be between 0 and 10")
        if (
            self.worker_lease_seconds < 10
            or self.worker_heartbeat_seconds <= 0
            or self.worker_heartbeat_seconds * 2 >= self.worker_lease_seconds
            or self.worker_shutdown_timeout_seconds <= 0
        ):
            raise ValueError("Worker heartbeat must renew well inside a positive lease")
        if self.reconciliation_grace_seconds < 0:
            raise ValueError("UNRENDER_RECONCILIATION_GRACE_SECONDS cannot be negative")
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
            max_recovery_attempts=_int("UNRENDER_MAX_RECOVERY_ATTEMPTS", 1),
            worker_lease_seconds=_int("UNRENDER_WORKER_LEASE_SECONDS", 45),
            worker_heartbeat_seconds=_int("UNRENDER_WORKER_HEARTBEAT_SECONDS", 10),
            worker_shutdown_timeout_seconds=_int("UNRENDER_WORKER_SHUTDOWN_TIMEOUT_SECONDS", 30),
            allow_registration=_bool("UNRENDER_ALLOW_REGISTRATION", True),
            seed_demo_account=_bool("UNRENDER_SEED_DEMO", True),
            session_ttl_hours=_int("UNRENDER_SESSION_TTL_HOURS", 24 * 7),
            upload_ttl_hours=_int("UNRENDER_UPLOAD_TTL_HOURS", 24),
            retention_days=_int("UNRENDER_RETENTION_DAYS", 30),
            max_upload_bytes=_int("UNRENDER_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
            max_pdf_pages=_int("UNRENDER_MAX_PDF_PAGES", 25),
            max_image_pixels=_int("UNRENDER_MAX_IMAGE_PIXELS", 50_000_000),
            max_user_storage_bytes=_int("UNRENDER_MAX_USER_STORAGE_BYTES", 250 * 1024 * 1024),
            max_unattached_uploads=_int("UNRENDER_MAX_UNATTACHED_UPLOADS", 5),
            max_upload_records_per_user=_int("UNRENDER_MAX_UPLOAD_RECORDS_PER_USER", 1_000),
            max_jobs_per_user=_int("UNRENDER_MAX_JOBS_PER_USER", 1_000),
            max_upload_bytes_per_minute=_int(
                "UNRENDER_MAX_UPLOAD_BYTES_PER_MINUTE", 40 * 1024 * 1024
            ),
            rate_limit_per_minute=_int("UNRENDER_RATE_LIMIT_PER_MINUTE", 120),
            max_result_versions_per_job=_int("UNRENDER_MAX_RESULT_VERSIONS_PER_JOB", 25),
            max_history_bytes_per_user=_int(
                "UNRENDER_MAX_HISTORY_BYTES_PER_USER", 16 * 1024 * 1024
            ),
            max_result_json_bytes=_int("UNRENDER_MAX_RESULT_JSON_BYTES", 1_000_000),
            max_storage_bytes_global=_int(
                "UNRENDER_MAX_STORAGE_BYTES_GLOBAL", 10 * 1024 * 1024 * 1024
            ),
            min_free_storage_bytes=_int("UNRENDER_MIN_FREE_STORAGE_BYTES", 256 * 1024 * 1024),
            database_headroom_bytes=_int("UNRENDER_DATABASE_HEADROOM_BYTES", 128 * 1024 * 1024),
            storage_reservation_ttl_seconds=_int(
                "UNRENDER_STORAGE_RESERVATION_TTL_SECONDS", 60 * 60
            ),
            max_sessions_per_user=_int("UNRENDER_MAX_SESSIONS_PER_USER", 10),
            max_active_api_keys_per_user=_int("UNRENDER_MAX_ACTIVE_API_KEYS_PER_USER", 10),
            max_api_key_records_per_user=_int("UNRENDER_MAX_API_KEY_RECORDS_PER_USER", 100),
            max_audit_events_per_job=_int("UNRENDER_MAX_AUDIT_EVENTS_PER_JOB", 500),
            max_audit_events_per_user=_int("UNRENDER_MAX_AUDIT_EVENTS_PER_USER", 5_000),
            audit_retention_days=_int("UNRENDER_AUDIT_RETENTION_DAYS", 90),
            max_credit_ledger_records_per_user=_int(
                "UNRENDER_MAX_CREDIT_LEDGER_RECORDS_PER_USER", 10_000
            ),
            max_database_rows_per_user=_int("UNRENDER_MAX_DATABASE_ROWS_PER_USER", 30_000),
            max_database_rows_global=_int("UNRENDER_MAX_DATABASE_ROWS_GLOBAL", 500_000),
            mandatory_database_rows_per_user=_int("UNRENDER_MANDATORY_DATABASE_ROWS_PER_USER", 64),
            mandatory_database_rows_global=_int("UNRENDER_MANDATORY_DATABASE_ROWS_GLOBAL", 512),
            max_billing_events_global=_int("UNRENDER_MAX_BILLING_EVENTS_GLOBAL", 100_000),
            max_provider_attempts_per_job=_int("UNRENDER_MAX_PROVIDER_ATTEMPTS_PER_JOB", 100),
            idempotency_ttl_hours=_int("UNRENDER_IDEMPOTENCY_TTL_HOURS", 24 * 30),
            idempotency_tombstone_days=_int("UNRENDER_IDEMPOTENCY_TOMBSTONE_DAYS", 365),
            max_idempotency_records_per_user=_int(
                "UNRENDER_MAX_IDEMPOTENCY_RECORDS_PER_USER", 10_000
            ),
            auth_rate_limit_per_minute=_int("UNRENDER_AUTH_RATE_LIMIT_PER_MINUTE", 10),
            max_concurrent_auth_requests=_int("UNRENDER_MAX_CONCURRENT_AUTH_REQUESTS", 2),
            max_concurrent_expensive_requests=_int("UNRENDER_MAX_CONCURRENT_EXPENSIVE_REQUESTS", 4),
            provider_failure_limit_per_user_hour=_int(
                "UNRENDER_PROVIDER_FAILURE_LIMIT_PER_USER_HOUR", 5
            ),
            provider_failure_limit_global_hour=_int(
                "UNRENDER_PROVIDER_FAILURE_LIMIT_GLOBAL_HOUR", 50
            ),
            reconciliation_grace_seconds=_int("UNRENDER_RECONCILIATION_GRACE_SECONDS", 300),
            modal_app_name=os.getenv("UNRENDER_MODAL_APP", "unrender"),
            modal_function_name=os.getenv("UNRENDER_MODAL_FUNCTION", "infer_one"),
            modal_model_path=os.getenv("UNRENDER_MODAL_MODEL", "runs/qwen3vl4b-table-fair/merged"),
            modal_model_revision=os.getenv("UNRENDER_MODAL_REVISION", "").casefold(),
            modal_model_digest=os.getenv("UNRENDER_MODAL_MODEL_DIGEST", "").casefold(),
            modal_provider_release=os.getenv("UNRENDER_MODAL_PROVIDER_RELEASE", "").casefold(),
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            stripe_price_id=os.getenv("STRIPE_PRICE_ID", ""),
            credit_pack_size=_int("UNRENDER_CREDIT_PACK_SIZE", 100),
            initial_credits=_int("UNRENDER_INITIAL_CREDITS", 3),
        )
        settings.validate()
        return settings
