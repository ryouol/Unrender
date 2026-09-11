"""Google identities preserve native account ownership and spend controls."""

from __future__ import annotations

import pytest
from test_product import service_for

from unrender.product.database import SCHEMA_VERSION
from unrender.product.service import ProductError

PASSWORD = "a long original password"


def test_v10_migration_preserves_password_accounts_and_sessions(tmp_path):
    service = service_for(tmp_path)
    account = service.register("owner@example.com", PASSWORD)
    owner = service.session_user(account["session"])["id"]
    with service.database.transaction() as conn:
        conn.execute("DROP TABLE google_identities")
        conn.execute("DROP TABLE oauth_attempts")
        conn.execute("ALTER TABLE users DROP COLUMN password_enabled")
        conn.execute("ALTER TABLE sessions DROP COLUMN reauthenticated_at")
        conn.execute("UPDATE schema_meta SET version=10")
    service.database.initialize()
    assert service.session_user(account["session"])["id"] == owner
    assert service.account(owner)["password_enabled"]
    assert not service.account(owner)["google_connected"]
    assert service.account(owner)["credits"] == 3
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("invalidated", ["expired", "another_session", "revoked", "old_proof"])
def test_sensitive_actions_require_recent_auth_bound_to_live_session(tmp_path, invalidated):
    service = service_for(tmp_path)
    first = service.register("owner@example.com", PASSWORD)
    owner = service.session_user(first["session"])["id"]
    second = service.authenticate("owner@example.com", PASSWORD)
    with service.database.transaction() as conn:
        with pytest.raises(ProductError, match="Confirm your identity"):
            service.require_recent_auth(conn, user_id=owner, session_token=first["session"])
    with pytest.raises(ProductError, match="Password is incorrect"):
        service.reauthenticate_password(
            user_id=owner, session_token=first["session"], password="wrong"
        )
    service.reauthenticate_password(
        user_id=owner, session_token=first["session"], password=PASSWORD
    )
    with service.database.transaction() as conn:
        service.require_recent_auth(conn, user_id=owner, session_token=first["session"])
        if invalidated == "expired":
            conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        elif invalidated == "revoked":
            conn.execute("UPDATE users SET session_generation=session_generation+1")
        elif invalidated == "old_proof":
            conn.execute("UPDATE sessions SET reauthenticated_at='2000-01-01T00:00:00+00:00'")
        with pytest.raises(ProductError, match="Confirm your identity"):
            service.require_recent_auth(
                conn,
                user_id=owner,
                session_token=second["session"]
                if invalidated == "another_session"
                else first["session"],
            )
