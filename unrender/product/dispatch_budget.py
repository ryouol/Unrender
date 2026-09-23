"""Global dispatch admission that survives account and chart deletion."""

import sqlite3


def reserve_dispatch(conn: sqlite3.Connection, day: str, limit: int) -> bool:
    """Called inside the job's immediate transaction; uncertain attempts stay reserved."""
    conn.execute(
        "INSERT OR IGNORE INTO dispatch_budget(id,day,used,paused) VALUES (1,?,0,0)",
        (day,),
    )
    # A backwards clock adjustment must not replenish today's allowance.
    conn.execute("UPDATE dispatch_budget SET day=?,used=0 WHERE id=1 AND day<?", (day, day))
    return (
        conn.execute(
            "UPDATE dispatch_budget SET used=used+1 WHERE id=1 AND paused=0 AND used<?",
            (limit,),
        ).rowcount
        == 1
    )


def status(conn: sqlite3.Connection, day: str, limit: int) -> dict[str, object]:
    row = conn.execute("SELECT day,used,paused FROM dispatch_budget WHERE id=1").fetchone()
    used = int(row["used"]) if row and row["day"] >= day else 0
    return {
        "utc_day": day,
        "reserved_dispatches": used,
        "daily_limit": limit,
        "remaining_dispatches": max(0, limit - used),
        "paused": bool(row and row["paused"]),
        "unit": "dispatches, not dollars",
    }
