"""FastAPI transport for the Unrender review workspace."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Awaitable
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Header,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from unrender.product.config import Settings
from unrender.product.database import Database
from unrender.product.extractors import build_extractor
from unrender.product.operations import OperationsProbe
from unrender.product.public_site import document, error_document, sitemap
from unrender.product.scheduled_backup import ScheduledBackup
from unrender.product.security import normalize_email
from unrender.product.service import ProductError, ProductService
from unrender.product.storage import InvalidUpload, Storage
from unrender.product.worker import JobWorker

logger = logging.getLogger("unrender.web")
SESSION_COOKIE = "unrender_session"
CSRF_COOKIE = "unrender_csrf"


def _security_headers(path: str, *, secure_cookies: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self'; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        ),
        "Cache-Control": "no-store" if path.startswith("/api/") else "no-cache",
    }
    if secure_cookies:
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers


class SecurityHeadersMiddleware:
    """Apply the browser policy even to outer Host/body admission failures."""

    def __init__(self, app: ASGIApp, *, secure_cookies: bool):
        self.app = app
        self.secure_cookies = secure_cookies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                for name, value in _security_headers(
                    str(scope.get("path", "")), secure_cookies=self.secure_cookies
                ).items():
                    headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            if response_started:
                raise
            logger.exception("unexpected_outer_asgi_error", exc_info=exc)
            if not str(scope.get("path", "")).startswith("/api/") and b"text/html" in dict(
                scope.get("headers", [])
            ).get(b"accept", b""):
                await error_document(500)(scope, receive, send_with_headers)
                return
            response = JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "The request could not be completed",
                    }
                },
                status_code=500,
            )
            await response(scope, receive, send_with_headers)


class BodyLimitMiddleware:
    """Bound streamed and chunked request bodies before framework parsing/spooling."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        upload_limit: int,
        result_limit: int = 1024 * 1024 + 64 * 1024,
    ):
        self.app = app
        self.upload_limit = upload_limit
        self.result_limit = result_limit

    def _limit(self, path: str, method: str) -> int:
        if path in {"/api/uploads", "/api/v1/extractions"}:
            return self.upload_limit + 1024 * 1024
        if path == "/api/billing/webhook":
            return 1024 * 1024
        if method == "PATCH" and path.startswith("/api/jobs/") and path.endswith("/result"):
            return self.result_limit
        return 256 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(str(scope.get("path", "")), str(scope.get("method", "GET")).upper())
        total = 0
        response_started = False
        too_large = False

        async def bounded_receive() -> Message:
            nonlocal total, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if too_large:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except Exception:
            if not too_large:
                raise
        if too_large and not response_started:
            response = JSONResponse(
                {
                    "error": {
                        "code": "request_too_large",
                        "message": "Request exceeds the configured size limit",
                    }
                },
                status_code=413,
                headers={"Connection": "close"},
            )
            await response(scope, receive, send)


def _is_auth_attempt(path: str, method: str) -> bool:
    return method == "POST" and path.startswith("/api/auth/") and path != "/api/auth/logout"


async def _run_admitted(operation: Awaitable[Any], semaphore: asyncio.Semaphore) -> Any:
    """Hold an acquired slot until work finishes, even if its caller disconnects."""
    task = asyncio.ensure_future(operation)

    def finish(completed: asyncio.Future) -> None:
        semaphore.release()
        # Retrieve failures even when the request stopped awaiting the task.
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(finish)
    return await asyncio.shield(task)


class ConcurrencyLimitMiddleware:
    """Reject excess process-local KDF and file-processing work before allocation."""

    def __init__(self, app: ASGIApp, *, auth_semaphore: asyncio.Semaphore, expensive_limit: int):
        self.app = app
        self.auth = auth_semaphore
        self.email = asyncio.Semaphore(1)
        self.expensive = asyncio.Semaphore(expensive_limit)

    @staticmethod
    def _group(path: str, method: str) -> str | None:
        if method == "POST" and path in {
            "/api/auth/register",
            "/api/auth/request-verification",
            "/api/auth/forgot-password",
        }:
            return "email"
        if _is_auth_attempt(path, method):
            return "auth"
        if path in {"/api/uploads", "/api/v1/extractions"} or (
            method == "GET"
            and ("/pages/" in path or path.endswith("/source") or "/export/" in path)
        ):
            return "expensive"
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        group = self._group(str(scope.get("path", "")), str(scope.get("method", "GET")))
        semaphore = (
            {"auth": self.auth, "email": self.email, "expensive": self.expensive}[group]
            if group
            else None
        )
        if semaphore is None:
            await self.app(scope, receive, send)
            return
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.05)
        except TimeoutError:
            response = JSONResponse(
                {
                    "error": {
                        "code": f"{group}_capacity_reached",
                        "message": (
                            "This process is at its safe concurrent-work limit; retry shortly"
                        ),
                    }
                },
                status_code=503,
                headers={"Retry-After": "1"},
            )
            await response(scope, receive, send)
            return
        await _run_admitted(self.app(scope, receive, send), semaphore)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictRequest):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AccountEmailRequest(StrictRequest):
    email: str = Field(max_length=254)


class AccountEmailComplete(StrictRequest):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class Crop(StrictRequest):
    x: float
    y: float
    width: float
    height: float


class JobCreate(StrictRequest):
    upload_id: str
    page_index: int = Field(default=0, ge=0)
    crop: Crop | None = None


class ResultUpdate(StrictRequest):
    result: dict[str, Any]


class ApiKeyCreate(StrictRequest):
    name: str = Field(min_length=1, max_length=80)


def _cookies(response: Response, values: dict[str, str], settings: Settings) -> None:
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        values["session"],
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        values["csrf"],
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _clear_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        CSRF_COOKIE,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _validated_checkout_url(value: str | None) -> str:
    if not value:
        raise ProductError(
            "billing_provider_invalid", "Test checkout did not return a destination", 502
        )
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "checkout.stripe.com"
        or parsed.username
        or parsed.password
    ):
        raise ProductError(
            "billing_provider_invalid", "Test checkout returned an unexpected destination", 502
        )
    return value


def create_app(settings: Settings | None = None) -> FastAPI:
    os.umask(0o077)
    settings = settings or Settings.from_env()
    settings.validate()
    static_dir = Path(__file__).with_name("static")
    database = Database(settings.database_path)
    storage = Storage(settings)
    extractor = build_extractor(settings, static_dir)
    service = ProductService(
        settings=settings,
        database=database,
        storage=storage,
        extractor=extractor,
        static_dir=static_dir,
    )
    worker = JobWorker(service)
    backups = ScheduledBackup(settings)
    operations = OperationsProbe(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.initialize()
        if settings.worker_enabled:
            worker.start()
            backups.start()
        yield
        await run_in_threadpool(backups.stop)
        stopped = await run_in_threadpool(worker.stop)
        while not stopped and worker.is_running:
            # A dispatched provider call is deliberately not abandoned at the local
            # warning timeout: its heartbeat and fenced terminal commit must finish.
            await asyncio.sleep(0.25)

    app = FastAPI(
        title="Unrender",
        version="0.2.0",
        docs_url=None,
        openapi_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.service = service
    app.state.worker = worker
    expected_host = urlsplit(settings.base_url).hostname
    allowed_hosts = [expected_host] if expected_host else []
    if settings.environment != "production":
        allowed_hosts.extend(["testserver", "localhost", "127.0.0.1"])
    app.add_middleware(
        BodyLimitMiddleware,
        upload_limit=settings.max_upload_bytes,
        result_limit=settings.result_request_bytes,
    )
    auth_semaphore = asyncio.Semaphore(settings.max_concurrent_auth_requests)
    app.add_middleware(
        ConcurrencyLimitMiddleware,
        auth_semaphore=auth_semaphore,
        expensive_limit=settings.max_concurrent_expensive_requests,
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def secure_response(response: Response, request: Request) -> Response:
        for name, value in _security_headers(
            request.url.path, secure_cookies=settings.secure_cookies
        ).items():
            response.headers[name] = value
        return response

    def rate_group(request: Request) -> str:
        path_parts = request.url.path.strip("/").split("/")
        is_job_status = (
            request.method == "GET" and len(path_parts) == 3 and path_parts[:2] == ["api", "jobs"]
        )
        is_auth = _is_auth_attempt(request.url.path, request.method)
        return "poll" if is_job_status else "auth" if is_auth else "request"

    def rate_limit_for(group: str, *, global_capacity: bool = False) -> int:
        request_limit = (
            settings.global_rate_limit_per_minute
            if global_capacity
            else settings.rate_limit_per_minute
        )
        if group == "poll":
            return max(240, request_limit * 2)
        if group == "auth":
            return (
                settings.global_auth_rate_limit_per_minute
                if global_capacity
                else settings.auth_rate_limit_per_minute
            )
        return request_limit

    def allowed_request(bucket: str, *, group: str, global_capacity: bool = False) -> bool:
        try:
            guard = (
                database.operational_lock(exclusive=False, timeout_seconds=0)
                if settings.backup_volume_name
                else nullcontext()
            )
            with guard:
                return service.rate_limit(
                    f"{bucket}:{group}",
                    limit=rate_limit_for(group, global_capacity=global_capacity),
                )
        except TimeoutError:
            raise
        except Exception:
            return False

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        content_length = request.headers.get("content-length")
        max_request_bytes = settings.max_upload_bytes + 1024 * 1024
        if content_length:
            try:
                if int(content_length) > max_request_bytes:
                    return secure_response(
                        JSONResponse(
                            {
                                "error": {
                                    "code": "request_too_large",
                                    "message": "Request exceeds the configured size limit",
                                }
                            },
                            status_code=413,
                        ),
                        request,
                    )
            except ValueError:
                return secure_response(
                    JSONResponse(
                        {"error": {"code": "invalid_request", "message": "Invalid request size"}},
                        status_code=400,
                    ),
                    request,
                )
        group = rate_group(request)
        try:
            # Shared proxy addresses are neither tenant identities nor trusted headers.
            # Every request spends global capacity before parsing/authentication.
            allowed = request.url.path == "/health/live" or await run_in_threadpool(
                allowed_request, "global", group=group, global_capacity=True
            )
        except TimeoutError:
            return secure_response(
                JSONResponse(
                    {
                        "error": {
                            "code": "maintenance_busy",
                            "message": "A recovery snapshot is in progress. Retry shortly.",
                        }
                    },
                    status_code=503,
                    headers={"Retry-After": "10"},
                ),
                request,
            )
        if not allowed:
            return secure_response(
                JSONResponse(
                    {"error": {"code": "rate_limited", "message": "Try again in a minute"}},
                    status_code=429,
                    headers={"Retry-After": "60"},
                ),
                request,
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                expected = urlsplit(settings.base_url)
                actual = urlsplit(origin)
                if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
                    return secure_response(
                        JSONResponse(
                            {
                                "error": {
                                    "code": "origin_rejected",
                                    "message": "Request origin is not allowed",
                                }
                            },
                            status_code=403,
                        ),
                        request,
                    )
        response = await call_next(request)
        return secure_response(response, request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(set(allowed_hosts)))
    app.add_middleware(SecurityHeadersMiddleware, secure_cookies=settings.secure_cookies)

    @app.exception_handler(TimeoutError)
    async def storage_busy(_: Request, exc: TimeoutError):
        return JSONResponse(
            {
                "error": {
                    "code": "service_busy",
                    "message": "The service is temporarily busy. Retry shortly.",
                }
            },
            status_code=503,
            headers={"Retry-After": "10"},
        )

    @app.exception_handler(ProductError)
    async def product_error(_: Request, exc: ProductError):
        return JSONResponse(
            {"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status_code
        )

    @app.exception_handler(InvalidUpload)
    async def upload_error(_: Request, exc: InvalidUpload):
        return JSONResponse(
            {"error": {"code": "invalid_upload", "message": str(exc)}}, status_code=422
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        message = first.get("msg", "Check the submitted values")
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": message}}, status_code=422
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("unexpected_http_error", exc_info=exc)
        if not request.url.path.startswith("/api/") and "text/html" in request.headers.get(
            "accept", ""
        ):
            return secure_response(error_document(500), request)
        return secure_response(
            JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "The request could not be completed",
                    }
                },
                status_code=500,
            ),
            request,
        )

    def authenticated_request(request: Request, user: Any) -> Any:
        principal = hashlib.sha256(f"user:{user['id']}".encode()).hexdigest()[:24]
        group = rate_group(request)
        if not allowed_request(f"user:{principal}", group=group):
            raise ProductError("rate_limited", "Try again in a minute", 429)
        return user

    def current_user(
        request: Request,
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ):
        user = service.session_user(session)
        if not user:
            raise ProductError("authentication_required", "Sign in to continue", 401)
        return authenticated_request(request, user)

    def csrf_user(
        request: Request,
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ):
        user = service.session_user(session)
        if not user:
            raise ProductError("authentication_required", "Sign in to continue", 401)
        if not service.verify_csrf(session, csrf_header):
            raise ProductError("csrf_rejected", "Refresh the page and try again", 403)
        return authenticated_request(request, user)

    def api_user(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ):
        secret = None
        if authorization and authorization.startswith("Bearer "):
            secret = authorization.removeprefix("Bearer ").strip()
        user = service.api_key_user(secret)
        if not user:
            raise ProductError("invalid_api_key", "Provide a valid Unrender API key", 401)
        return authenticated_request(request, user)

    current_user_dependency = Depends(current_user)
    csrf_user_dependency = Depends(csrf_user)
    api_user_dependency = Depends(api_user)

    @app.get("/")
    def index():
        return document(static_dir, "/", settings.base_url)

    @app.get("/app")
    @app.get("/login")
    @app.get("/signup")
    def workspace_shell(request: Request):
        return document(static_dir, request.url.path, settings.base_url)

    @app.get("/privacy")
    def privacy():
        return document(static_dir, "/privacy", settings.base_url)

    @app.get("/terms")
    def terms():
        return document(static_dir, "/terms", settings.base_url)

    @app.get("/account")
    def account_help():
        return document(static_dir, "/account", settings.base_url)

    @app.get("/contact")
    def contact():
        return document(static_dir, "/contact", settings.base_url)

    @app.get("/robots.txt")
    def robots():
        return Response(
            "User-agent: *\nDisallow: /api/\nDisallow: /health/\n"
            f"Sitemap: {settings.base_url}/sitemap.xml\n",
            media_type="text/plain",
        )

    @app.get("/sitemap.xml")
    def public_sitemap():
        return Response(sitemap(settings.base_url), media_type="application/xml")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            return error_document(404)
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.get("/api/public-config")
    def public_config():
        return {
            "registration_open": settings.allow_registration,
            "sample_available": settings.seed_demo_account,
            "email_available": settings.email_configured,
            "email_verification_required": settings.require_email_verification,
            "initial_credits": settings.initial_credits,
            "max_upload_bytes": settings.max_upload_bytes,
            "max_image_pixels": settings.max_image_pixels,
            "max_pdf_pages": settings.max_pdf_pages,
        }

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        worker_ready = not settings.worker_enabled or worker.is_accepting
        if not database.ready() or not storage.ready() or not worker_ready:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {
            "status": "ready",
            "extractor": settings.extractor_backend,
            "worker": "running" if worker.is_accepting else "disabled",
        }

    @app.get("/health/operations")
    def operations_health():
        checks = operations.check()
        checks["worker_available"] = not settings.worker_enabled or worker.is_accepting
        healthy = all(checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "attention", "checks": checks},
            status_code=200 if healthy else 503,
        )

    @app.post("/api/auth/register", status_code=201)
    async def register(payload: Credentials, response: Response):
        await run_in_threadpool(admit_credentials, payload.email)
        # Registration shares KDF admission with sign-in, but releases it before
        # synchronous SMTP work. The outer email slot bounds the whole request.
        try:
            await asyncio.wait_for(auth_semaphore.acquire(), timeout=0.05)
        except TimeoutError as exc:
            raise ProductError(
                "auth_capacity_reached", "Authentication is busy; retry shortly", 503
            ) from exc
        values = await _run_admitted(
            run_in_threadpool(service.register, payload.email, payload.password), auth_semaphore
        )
        if values.get("verification_required"):
            await run_in_threadpool(service.request_account_email, payload.email, purpose="verify")
            return {"ok": True, "verification_required": True}
        _cookies(response, values, settings)
        return {"ok": True}

    def admit_credentials(email: str) -> None:
        try:
            normalized = normalize_email(email)
        except ValueError:
            normalized = ""
        principal = hashlib.sha256(normalized.encode()).hexdigest()[:24]
        if not allowed_request(f"account:{principal}", group="auth"):
            raise ProductError("rate_limited", "Try again in a minute", 429)

    @app.post("/api/auth/login")
    def login(payload: Credentials, response: Response):
        admit_credentials(payload.email)
        values = service.authenticate(payload.email, payload.password)
        _cookies(response, values, settings)
        return {"ok": True}

    @app.post("/api/auth/request-verification")
    def request_verification(payload: AccountEmailRequest):
        service.request_account_email(payload.email, purpose="verify")
        return {"ok": True}

    @app.post("/api/auth/forgot-password")
    def forgot_password(payload: AccountEmailRequest):
        service.request_account_email(payload.email, purpose="reset")
        return {"ok": True}

    @app.post("/api/auth/verify-email")
    def verify_email(payload: AccountEmailComplete):
        service.complete_account_email(payload.token, purpose="verify", password=payload.password)
        return {"ok": True}

    @app.post("/api/auth/reset-password")
    def reset_password(payload: AccountEmailComplete):
        service.complete_account_email(payload.token, purpose="reset", password=payload.password)
        return {"ok": True}

    @app.post("/api/auth/demo")
    def demo_login(response: Response):
        values = service.demo_session()
        _cookies(response, values, settings)
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(
        response: Response,
        _: Any = csrf_user_dependency,
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ):
        service.logout(session)
        _clear_cookies(response, settings)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: Any = current_user_dependency):
        return service.account(user["id"])

    @app.post("/api/uploads", status_code=201)
    async def create_upload(
        file: Annotated[UploadFile, File()],
        user: Any = csrf_user_dependency,
    ):
        service.require_customer_account(user["id"], "customer uploads")
        await file.seek(0)
        return await run_in_threadpool(
            service.prepare_upload_stream,
            user_id=user["id"],
            filename=file.filename or "chart",
            source=file.file,
        )

    @app.post("/api/uploads/demo", status_code=201)
    def create_demo_upload(user: Any = csrf_user_dependency):
        return service.prepare_demo_upload(user["id"])

    @app.get("/api/uploads/{upload_id}/pages/{page_index}")
    def preview_upload(
        upload_id: str,
        page_index: int,
        user: Any = current_user_dependency,
    ):
        image = service.upload_preview(
            user_id=user["id"], upload_id=upload_id, page_index=page_index
        )
        return Response(image, media_type="image/png")

    @app.post("/api/jobs", status_code=202)
    def create_job(
        payload: JobCreate,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user: Any = csrf_user_dependency,
    ):
        if idempotency_key is None:
            raise ProductError(
                "idempotency_key_required",
                "Provide an Idempotency-Key for safe retry of this job submission",
                422,
            )
        return service.create_job(
            user_id=user["id"],
            upload_id=payload.upload_id,
            page_index=payload.page_index,
            crop=payload.crop.model_dump() if payload.crop else None,
            idempotency_key=idempotency_key,
        )

    @app.get("/api/jobs")
    def list_jobs(
        cursor: str | None = None,
        limit: int = 50,
        user: Any = current_user_dependency,
    ):
        return service.list_jobs_page(user["id"], cursor=cursor, limit=limit)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, user: Any = current_user_dependency):
        return service.get_job(user_id=user["id"], job_id=job_id)

    @app.get("/api/jobs/{job_id}/source")
    def job_source(job_id: str, user: Any = current_user_dependency):
        return Response(
            service.job_source(user_id=user["id"], job_id=job_id), media_type="image/png"
        )

    @app.get("/api/jobs/{job_id}/audit")
    def job_audit(
        job_id: str,
        cursor: str | None = None,
        limit: int = 50,
        user: Any = current_user_dependency,
    ):
        return service.job_audit_page(user_id=user["id"], job_id=job_id, cursor=cursor, limit=limit)

    @app.get("/api/jobs/{job_id}/versions")
    def job_versions(
        job_id: str,
        before: int | None = None,
        user: Any = current_user_dependency,
    ):
        return service.job_versions(user_id=user["id"], job_id=job_id, before=before)

    @app.get("/api/jobs/{job_id}/versions/{version}")
    def job_version(job_id: str, version: int, user: Any = current_user_dependency):
        return service.job_version(user_id=user["id"], job_id=job_id, version=version)

    @app.patch("/api/jobs/{job_id}/result")
    def save_result(
        job_id: str,
        payload: ResultUpdate,
        user: Any = csrf_user_dependency,
    ):
        return service.save_correction(user_id=user["id"], job_id=job_id, result=payload.result)

    @app.post("/api/jobs/{job_id}/approve")
    def approve(job_id: str, user: Any = csrf_user_dependency):
        return service.approve(user_id=user["id"], job_id=job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, user: Any = csrf_user_dependency):
        return service.cancel(user_id=user["id"], job_id=job_id)

    @app.post("/api/jobs/{job_id}/reprocess", status_code=202)
    def reprocess(job_id: str, user: Any = csrf_user_dependency):
        return service.reprocess(user_id=user["id"], job_id=job_id)

    @app.get("/api/jobs/{job_id}/export/{output_format}")
    def export(
        job_id: str,
        output_format: str,
        user: Any = current_user_dependency,
    ):
        payload, mime = service.export(
            user_id=user["id"], job_id=job_id, output_format=output_format
        )
        filename = f"unrender-{job_id[:8]}.{output_format}"
        return Response(
            payload,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, user: Any = csrf_user_dependency):
        deleted = service.delete_job(user_id=user["id"], job_id=job_id)
        if deleted:
            return Response(status_code=204)
        return JSONResponse({"status": "deletion_queued"}, status_code=202)

    @app.post("/api/keys", status_code=201)
    def create_key(payload: ApiKeyCreate, user: Any = csrf_user_dependency):
        return service.create_api_key(
            user_id=user["id"],
            name=payload.name,
            expected_generation=int(user["session_generation"]),
        )

    @app.get("/api/keys")
    def list_keys(
        cursor: str | None = None,
        limit: int = 50,
        user: Any = current_user_dependency,
    ):
        return service.list_api_keys_page(user_id=user["id"], cursor=cursor, limit=limit)

    @app.delete("/api/keys")
    def revoke_all_keys(user: Any = csrf_user_dependency):
        return {"revoked": service.revoke_all_api_keys(user_id=user["id"])}

    @app.delete("/api/keys/{key_id}")
    def revoke_key(key_id: str, user: Any = csrf_user_dependency):
        return service.revoke_api_key(user_id=user["id"], key_id=key_id)

    @app.post("/api/billing/checkout", status_code=201)
    def create_checkout(user: Any = csrf_user_dependency):
        service.require_customer_account(user["id"], "test checkout")
        if not settings.billing_configured:
            raise ProductError(
                "billing_unavailable", "Test-mode credit purchases are not configured", 503
            )
        import stripe

        stripe.api_key = settings.stripe_secret_key
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
                client_reference_id=user["id"],
                customer_email=user["email"],
                metadata={
                    "user_id": user["id"],
                    "credits": str(settings.credit_pack_size),
                },
                success_url=f"{settings.base_url}/app?billing=success",
                cancel_url=f"{settings.base_url}/app?billing=cancelled",
            )
        except stripe.StripeError as exc:
            logger.warning("stripe_checkout_failed", exc_info=exc)
            raise ProductError(
                "billing_provider_unavailable",
                "Test checkout could not be started. Try again shortly.",
                503,
            ) from exc
        return {"url": _validated_checkout_url(session.url)}

    @app.post("/api/billing/webhook")
    async def billing_webhook(
        request: Request,
        stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
    ):
        if not settings.billing_configured:
            raise ProductError("billing_unavailable", "Billing webhook is not configured", 503)
        if not stripe_signature:
            raise ProductError("billing_signature_missing", "Webhook signature is missing", 400)
        import stripe

        payload = await request.body()
        try:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, settings.stripe_webhook_secret
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise ProductError(
                "billing_signature_invalid", "Webhook signature is invalid", 400
            ) from exc
        event_type = str(event["type"])
        if event_type != "checkout.session.completed":
            return {"received": True, "applied": False}
        checkout = event["data"]["object"]
        if bool(event.get("livemode")) or bool(checkout.get("livemode")):
            raise ProductError(
                "billing_live_event_rejected",
                "Live-mode billing events are not accepted by this test-only integration",
                422,
            )
        if checkout.get("payment_status") != "paid":
            return {"received": True, "applied": False}
        metadata = checkout.get("metadata") or {}
        user_id = str(metadata.get("user_id", ""))
        try:
            credits = int(metadata.get("credits", ""))
        except (TypeError, ValueError) as exc:
            raise ProductError("billing_event_invalid", "Credit metadata is invalid", 422) from exc
        if str(checkout.get("client_reference_id", "")) != user_id:
            raise ProductError(
                "billing_event_invalid", "Billing account reference does not match", 422
            )
        applied = service.apply_billing_event(
            event_id=str(event["id"]),
            event_type=event_type,
            user_id=user_id,
            credits=credits,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return {"received": True, "applied": applied}

    @app.post("/api/v1/extractions", status_code=202)
    async def api_extraction(
        file: Annotated[UploadFile, File()],
        page_index: int = 0,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user: Any = api_user_dependency,
    ):
        await file.seek(0)
        return await run_in_threadpool(
            service.submit_api_extraction_stream,
            user_id=user["id"],
            filename=file.filename or "chart",
            source=file.file,
            page_index=page_index,
            idempotency_key=idempotency_key or "",
        )

    @app.get("/api/v1/extractions/{job_id}")
    def api_get_extraction(job_id: str, user: Any = api_user_dependency):
        return service.get_job(user_id=user["id"], job_id=job_id)

    return app
