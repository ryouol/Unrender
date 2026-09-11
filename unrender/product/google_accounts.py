"""One-use browser-bound OAuth attempts and explicit native-account linking."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from unrender.product.google_oauth import owns_email
from unrender.product.security import normalize_email, random_token, token_hash
from unrender.product.service import ProductError, ProductService, timestamp, utcnow

OAUTH_TTL_SECONDS = 600
MAX_OAUTH_ATTEMPTS = 250


class GoogleAccounts:
    def __init__(self, service: ProductService):
        self.service = service

    def begin(
        self, browser: str, *, mode: str = "signin", session: str = "", intent: str = ""
    ) -> dict[str, str]:
        if not self.service.settings.google_configured:
            raise ProductError("google_unavailable", "Google sign-in is not available", 503)
        state, nonce, verifier = (random_token() for _ in range(3))
        with self.service.database.transaction(immediate=True) as conn:
            conn.execute("DELETE FROM oauth_attempts WHERE expires_at<=?", (timestamp(),))
            if (
                conn.execute("SELECT COUNT(*) FROM oauth_attempts").fetchone()[0]
                >= MAX_OAUTH_ATTEMPTS
            ):
                raise ProductError("auth_capacity_reached", "Sign-in is busy; retry shortly", 503)
            user = self._session(conn, session) if mode != "signin" else None
            if mode == "link" and user is not None:
                self.service.require_recent_auth(conn, user_id=user["id"], session_token=session)
            self.service._insert_row(
                conn,
                "INSERT INTO oauth_attempts(state_hash,browser_hash,nonce,verifier,mode,user_id,"
                "session_hash,session_generation,expires_at,client_nonce) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    token_hash(state),
                    token_hash(browser),
                    nonce,
                    verifier,
                    mode,
                    user["id"] if user else None,
                    token_hash(session) if user else None,
                    user["session_generation"] if user else None,
                    timestamp(utcnow() + timedelta(seconds=OAUTH_TTL_SECONDS)),
                    intent,
                ),
                user_id=user["id"] if user else None,
            )
        return {"state": state, "nonce": nonce, "verifier": verifier}

    def consume(self, *, state: str, browser: str, session: str) -> sqlite3.Row:
        with self.service.database.transaction(immediate=True) as conn:
            attempt = conn.execute(
                "DELETE FROM oauth_attempts WHERE state_hash=? AND browser_hash=? "
                "AND expires_at>? RETURNING *",
                (token_hash(state), token_hash(browser), timestamp()),
            ).fetchone()
            if not attempt:
                raise ProductError("google_expired", "Sign-in expired; please start again", 400)
            if attempt["mode"] != "signin":
                self._bound_user(conn, attempt, session)
            return attempt

    @staticmethod
    def _session(conn: sqlite3.Connection, session: str) -> sqlite3.Row:
        user = conn.execute(
            "SELECT users.* FROM users JOIN sessions ON sessions.user_id=users.id "
            "WHERE sessions.token_hash=? AND sessions.expires_at>? AND users.account_active=1 "
            "AND sessions.session_generation=users.session_generation",
            (token_hash(session), timestamp()),
        ).fetchone()
        if not user or user["account_kind"] != "customer":
            raise ProductError("authentication_required", "Sign in again to continue", 401)
        return user

    def _bound_user(
        self, conn: sqlite3.Connection, attempt: sqlite3.Row, session: str
    ) -> sqlite3.Row:
        user = self._session(conn, session)
        if (
            attempt["session_hash"] != token_hash(session)
            or attempt["user_id"] != user["id"]
            or attempt["session_generation"] != user["session_generation"]
        ):
            raise ProductError("google_expired", "Account session changed; start again", 400)
        return user

    def finish(self, attempt: sqlite3.Row, claims: dict[str, Any], session: str) -> str:
        subject, email = claims["sub"], normalize_email(claims["email"])
        with self.service.database.transaction(immediate=True) as conn:
            identity = conn.execute(
                "SELECT user_id FROM google_identities WHERE subject=?", (subject,)
            ).fetchone()
            if attempt["mode"] != "signin":
                user = self._bound_user(conn, attempt, session)
                if attempt["mode"] == "reauthenticate":
                    if not identity or identity["user_id"] != user["id"]:
                        raise ProductError(
                            "google_account_mismatch", "Choose your connected Google account", 409
                        )
                    conn.execute(
                        "UPDATE sessions SET reauthenticated_at=? WHERE token_hash=?",
                        (timestamp(), token_hash(session)),
                    )
                else:
                    self.service.require_recent_auth(
                        conn, user_id=user["id"], session_token=session
                    )
                    if identity and identity["user_id"] != user["id"]:
                        raise ProductError(
                            "google_already_linked", "That Google account is already connected", 409
                        )
                    existing = conn.execute(
                        "SELECT subject FROM google_identities WHERE user_id=?", (user["id"],)
                    ).fetchone()
                    if existing and existing["subject"] != subject:
                        raise ProductError(
                            "google_already_linked",
                            "This workspace already has a Google account",
                            409,
                        )
                    if not existing:
                        self._insert_identity(conn, subject, user["id"])
                    if email == user["email"] and owns_email(claims):
                        conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))
                    self.service._audit(conn, user_id=user["id"], event_type="google_connected")
                return str(user["id"])
            if identity:
                return str(identity["user_id"])
            if not self.service.settings.allow_registration:
                raise ProductError("registration_closed", "New accounts are currently closed", 403)
            if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                raise ProductError(
                    "google_link_required",
                    "Sign in with your password, then connect Google in Settings",
                    409,
                )
            user_id = self.service._id()
            self.service._insert_row(
                conn,
                "INSERT INTO users(id,email,password_hash,password_enabled,account_active,"
                "email_verified,credit_balance,created_at) VALUES (?,?,'!',0,1,?,0,?)",
                (user_id, email, owns_email(claims), timestamp()),
                user_id=None,
            )
            if self.service.settings.initial_credits:
                self.service._change_credits(
                    conn,
                    user_id=user_id,
                    delta=self.service.settings.initial_credits,
                    reason="welcome_allowance",
                    idempotency_key=f"welcome:{user_id}",
                )
            self._insert_identity(conn, subject, user_id)
            self.service._audit(conn, user_id=user_id, event_type="account_created")
            return user_id

    def _insert_identity(self, conn: sqlite3.Connection, subject: str, user_id: str) -> None:
        self.service._insert_row(
            conn,
            "INSERT INTO google_identities(subject,user_id,created_at) VALUES (?,?,?)",
            (subject, user_id, timestamp()),
            user_id=user_id,
        )

    def complete_login(self, *, user_id: str, session: str, intent: str) -> dict[str, Any]:
        with self.service.database.transaction(immediate=True) as conn:
            self._session(conn, session)
            consumed = conn.execute(
                "UPDATE sessions SET oauth_login_nonce=NULL WHERE token_hash=? AND user_id=? "
                "AND oauth_login_nonce=? AND created_at>? RETURNING id",
                (
                    token_hash(session),
                    user_id,
                    intent,
                    timestamp(utcnow() - timedelta(seconds=OAUTH_TTL_SECONDS)),
                ),
            ).fetchone()
            if not consumed:
                raise ProductError(
                    "google_expired", "Google sign-in completion expired; start again", 403
                )
        return self.service.account(user_id)
