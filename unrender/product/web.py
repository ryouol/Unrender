"""FastAPI transport for the Unrender review workspace."""

from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from unrender.product.config import Settings
from unrender.product.database import Database
from unrender.product.extractors import build_extractor
from unrender.product.service import ProductError, ProductService
from unrender.product.storage import InvalidUpload, Storage
from unrender.product.worker import JobWorker

logger = logging.getLogger("unrender.web")
SESSION_COOKIE = "unrender_session"
CSRF_COOKIE = "unrender_csrf"


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictRequest):
    email: str = Field(max_length=254)
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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.initialize()
        if settings.worker_enabled:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(
        title="Unrender",
        version="0.2.0",
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(set(allowed_hosts)))
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def secure_response(response: Response, request: Request) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache"
        )
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

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
        client = request.client.host if request.client else "unknown"
        bucket = hashlib.sha256(client.encode("utf-8")).hexdigest()[:24]
        if request.url.path not in {"/health/live", "/health/ready"}:
            try:
                allowed = service.rate_limit(bucket)
            except Exception:
                allowed = False
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

    def current_user(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ):
        user = service.session_user(session)
        if not user:
            raise ProductError("authentication_required", "Sign in to continue", 401)
        return user

    def csrf_user(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ):
        user = service.session_user(session)
        if not user:
            raise ProductError("authentication_required", "Sign in to continue", 401)
        if not service.verify_csrf(session, csrf_header):
            raise ProductError("csrf_rejected", "Refresh the page and try again", 403)
        return user

    def api_user(authorization: Annotated[str | None, Header()] = None):
        secret = None
        if authorization and authorization.startswith("Bearer "):
            secret = authorization.removeprefix("Bearer ").strip()
        user = service.api_key_user(secret)
        if not user:
            raise ProductError("invalid_api_key", "Provide a valid Unrender API key", 401)
        return user

    current_user_dependency = Depends(current_user)
    csrf_user_dependency = Depends(csrf_user)
    api_user_dependency = Depends(api_user)

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/privacy")
    def privacy():
        return FileResponse(static_dir / "privacy.html")

    @app.get("/terms")
    def terms():
        return FileResponse(static_dir / "terms.html")

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        if not database.ready() or not settings.storage_dir.exists():
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready", "extractor": settings.extractor_backend}

    @app.post("/api/auth/register", status_code=201)
    def register(payload: Credentials, response: Response):
        values = service.register(payload.email, payload.password)
        _cookies(response, values, settings)
        return {"ok": True}

    @app.post("/api/auth/login")
    def login(payload: Credentials, response: Response):
        values = service.authenticate(payload.email, payload.password)
        _cookies(response, values, settings)
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
        content = await file.read(settings.max_upload_bytes + 1)
        return service.prepare_upload(
            user_id=user["id"], filename=file.filename or "chart", content=content
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
    def create_job(payload: JobCreate, user: Any = csrf_user_dependency):
        return service.create_job(
            user_id=user["id"],
            upload_id=payload.upload_id,
            page_index=payload.page_index,
            crop=payload.crop.model_dump() if payload.crop else None,
        )

    @app.get("/api/jobs")
    def list_jobs(user: Any = current_user_dependency):
        return {"items": service.list_jobs(user["id"])}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, user: Any = current_user_dependency):
        return service.get_job(user_id=user["id"], job_id=job_id)

    @app.get("/api/jobs/{job_id}/source")
    def job_source(job_id: str, user: Any = current_user_dependency):
        return Response(
            service.job_source(user_id=user["id"], job_id=job_id), media_type="image/png"
        )

    @app.get("/api/jobs/{job_id}/audit")
    def job_audit(job_id: str, user: Any = current_user_dependency):
        return {"items": service.job_audit(user_id=user["id"], job_id=job_id)}

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

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, user: Any = csrf_user_dependency):
        service.delete_job(user_id=user["id"], job_id=job_id)
        return Response(status_code=204)

    @app.post("/api/keys", status_code=201)
    def create_key(payload: ApiKeyCreate, user: Any = csrf_user_dependency):
        return service.create_api_key(user_id=user["id"], name=payload.name)

    @app.get("/api/keys")
    def list_keys(user: Any = current_user_dependency):
        return {"items": service.list_api_keys(user_id=user["id"])}

    @app.delete("/api/keys/{key_id}")
    def revoke_key(key_id: str, user: Any = csrf_user_dependency):
        return service.revoke_api_key(user_id=user["id"], key_id=key_id)

    @app.post("/api/billing/checkout", status_code=201)
    def create_checkout(user: Any = csrf_user_dependency):
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
                success_url=f"{settings.base_url}/?billing=success",
                cancel_url=f"{settings.base_url}/?billing=cancelled",
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
        user: Any = api_user_dependency,
    ):
        content = await file.read(settings.max_upload_bytes + 1)
        upload = service.prepare_upload(
            user_id=user["id"], filename=file.filename or "chart", content=content
        )
        return service.create_job(
            user_id=user["id"], upload_id=upload["id"], page_index=page_index, crop=None
        )

    @app.get("/api/v1/extractions/{job_id}")
    def api_get_extraction(job_id: str, user: Any = api_user_dependency):
        return service.get_job(user_id=user["id"], job_id=job_id)

    return app


app = create_app()
