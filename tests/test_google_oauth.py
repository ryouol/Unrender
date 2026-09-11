"""Verify real signed Google-shaped JWTs against the official validation library."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, exceptions, jwt
from test_product import settings_for

from unrender.product import google_oauth


@pytest.fixture(scope="module")
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "test-only")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=5))
        .not_valid_after(datetime.now(UTC) + timedelta(minutes=5))
        .sign(key, hashes.SHA256())
    )
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return crypt.RSASigner.from_string(private), certificate.public_bytes(
        serialization.Encoding.PEM
    ).decode()


@pytest.mark.parametrize(
    "scenario",
    [
        "valid",
        "audience",
        "issuer",
        "expired",
        "signature",
        "nonce",
        "unverified",
        "subject",
        "provider",
        "missing_token",
    ],
)
def test_exchange_validates_signature_claims_pkce_and_bounded_transport(
    tmp_path, monkeypatch, signing_key, scenario
):
    settings = settings_for(
        tmp_path,
        base_url="http://localhost",
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="secret-only-for-test",
    )
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "sub": "account-123",
        "aud": settings.google_client_id,
        "iat": now - 5,
        "exp": now + 300,
        "nonce": "browser-nonce",
        "email_verified": True,
        "email": "person@gmail.com",
    }
    replacement = {
        "audience": ("aud", "another-client"),
        "issuer": ("iss", "https://attacker.example"),
        "expired": ("exp", now - 30),
        "nonce": ("nonce", "another-browser"),
        "unverified": ("email_verified", False),
        "subject": ("sub", ""),
    }
    if scenario in replacement:
        name, value = replacement[scenario]
        claims[name] = value
    signer, certificate = signing_key
    token = jwt.encode(signer, claims, key_id="test-key").decode()
    if scenario == "signature":
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        token = ".".join(parts)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert url == "https://oauth2.googleapis.com/token"
            assert kwargs["timeout"] == 15 and kwargs["allow_redirects"] is False
            assert kwargs["data"]["code_verifier"] == "pkce-verifier"
            assert kwargs["data"]["client_secret"] == settings.google_client_secret
            assert kwargs["data"]["redirect_uri"] == "http://localhost/auth/google/callback"
            return SimpleNamespace(
                status_code=401 if scenario == "provider" else 200,
                json=lambda: {} if scenario == "missing_token" else {"id_token": token},
            )

    def certificates(*args, **kwargs):
        assert kwargs["timeout"] == 15
        return SimpleNamespace(status=200, data=json.dumps({"test-key": certificate}).encode())

    monkeypatch.setattr(google_oauth.requests, "Session", Session)
    monkeypatch.setattr(google_oauth, "GoogleRequest", lambda **kwargs: certificates)
    if scenario == "valid":
        result = google_oauth.exchange_code(
            settings, code="one-use-code", verifier="pkce-verifier", nonce="browser-nonce"
        )
        assert result["sub"] == "account-123"
    else:
        with pytest.raises((ValueError, exceptions.GoogleAuthError)):
            google_oauth.exchange_code(
                settings, code="one-use-code", verifier="pkce-verifier", nonce="browser-nonce"
            )


def test_google_configuration_is_explicit_and_only_https_or_loopback(tmp_path, monkeypatch):
    baseline = settings_for(
        tmp_path,
        base_url="http://localhost",
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="test-only",
    )
    baseline.validate()
    for changes in (
        {"google_client_secret": ""},
        {"google_client_id": "invalid"},
        {"base_url": "http://public.example"},
    ):
        with pytest.raises(ValueError, match="Google"):
            replace(baseline, **changes).validate()
    assert not google_oauth.owns_email({"email": "person@external.example", "email_verified": True})
    assert google_oauth.owns_email(
        {"email": "person@workspace.example", "email_verified": True, "hd": "workspace.example"}
    )
