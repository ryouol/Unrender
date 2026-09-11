"""Google authorization code exchange; tokens and client secrets stay server-side."""

from __future__ import annotations

import hashlib
import secrets
from base64 import urlsafe_b64encode
from typing import Any
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.id_token import verify_oauth2_token

from unrender.product.config import Settings
from unrender.product.security import normalize_email


def callback_url(settings: Settings) -> str:
    return settings.base_url.rstrip("/") + "/auth/google/callback"


def authorization_url(settings: Settings, *, state: str, nonce: str, verifier: str) -> str:
    challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": callback_url(settings),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )


def exchange_code(settings: Settings, *, code: str, verifier: str, nonce: str) -> dict[str, Any]:
    with requests.Session() as session:
        response = session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": callback_url(settings),
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
            timeout=15,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError("Google sign-in failed")
        token = response.json().get("id_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ValueError("Invalid Google identity token")

        def bounded_request(*args: Any, **kwargs: Any) -> Any:
            kwargs["timeout"] = 15
            return GoogleRequest(session=session)(*args, **kwargs)

        claims = verify_oauth2_token(token, bounded_request, settings.google_client_id)
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("Invalid Google nonce")
    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or not subject.isascii()
        or not subject.isprintable()
        or claims.get("email_verified") is not True
    ):
        raise ValueError("Invalid Google account")
    claims["email"] = normalize_email(str(claims.get("email", "")))
    return claims


def owns_email(claims: dict[str, Any]) -> bool:
    # A non-Google mailbox may have changed owners since Google first verified it.
    return str(claims["email"]).endswith("@gmail.com") or bool(claims.get("hd"))
