"""Existing accounts retain access and data when deletion indexes are installed."""

import pytest
from test_library import chart_for
from test_product import customer_id, service_for

from unrender.product.database import SCHEMA_VERSION


def test_schema13_upgrade_preserves_accounts_and_indexes_bulk_deletion(tmp_path):
    service = service_for(tmp_path, seed_demo_account=False)
    owner = customer_id(service)
    job = chart_for(service, owner)
    before = service.get_job(user_id=owner, job_id=job["id"])
    indexed_columns = (
        ("credit_ledger", "user_id"),
        ("sessions", "user_id"),
        ("uploads", "user_id"),
        ("api_keys", "user_id"),
        ("pending_deletions", "user_id"),
        ("storage_reservations", "user_id"),
        ("jobs", "upload_id"),
        ("audit_rollups", "job_id"),
    )
    with service.database.transaction(immediate=True) as conn:
        for table, column in indexed_columns:
            conn.execute(f"DROP INDEX {table}_{column}_idx")
        conn.execute("UPDATE schema_meta SET version=13")

    # A failed migration rolls back both the version and newly created indexes.
    def interrupt():
        raise RuntimeError("interrupted upgrade")

    service.database._migration_fault_hook = interrupt
    with pytest.raises(RuntimeError, match="interrupted"):
        service.database.initialize()
    service.database._migration_fault_hook = None
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 13
    service.database.initialize()
    service.database.initialize()
    assert service.get_job(user_id=owner, job_id=job["id"]) == before
    assert service.account(owner)["credits"] == 2
    with service.database.connect() as conn:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
        for table, column in indexed_columns:
            plan = conn.execute(
                f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE {column}=?", (owner,)
            ).fetchall()
            assert any(f"{table}_{column}_idx" in row["detail"] for row in plan)
