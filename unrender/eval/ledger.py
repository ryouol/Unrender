"""Crash-durable scheduling and single-writer ownership for evaluation runs.

The database is authoritative. JSONL is a portable snapshot, never a dispatch log.
An uncertain dispatch is retained, not retried. SDK-internal retries are separate.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from unrender.io_utils import read_jsonl

LEDGER_NAME = "run.sqlite3"
RUN_CONTRACT = "scheduled-evaluation-v1"


def schedule_hash(schedule: list[dict]) -> str:
    return hashlib.sha256(json.dumps(schedule, sort_keys=True).encode()).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def run_owner(directory: Path):
    """Fail fast if another process owns this run; OS releases ownership on crash."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit("evaluation run is already owned by another process") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class RunLedger:
    def __init__(self, directory: Path, metadata: dict, schedule: list[dict]):
        self.directory = directory
        self.path = directory / LEDGER_NAME
        if not self.path.exists() and any(
            (directory / name).exists() for name in ("predictions.jsonl", "meta.json")
        ):
            raise SystemExit("resume-config lacks a durable schedule; use a fresh output directory")
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA synchronous=FULL")
        try:
            with self.conn:
                self.conn.execute("CREATE TABLE IF NOT EXISTS run (metadata_json TEXT NOT NULL)")
                self.conn.execute(
                    "CREATE TABLE IF NOT EXISTS samples ("
                    "id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,"
                    "payload_json TEXT NOT NULL,"
                    "state TEXT NOT NULL CHECK(state IN "
                    "('pending','dispatched','completed','interrupted','input_error')),"
                    "started_at TEXT,ended_at TEXT,result_json TEXT)"
                )
                old = self.conn.execute("SELECT metadata_json FROM run").fetchall()
                if old:
                    if len(old) != 1:
                        raise SystemExit("invalid run ledger metadata")
                    stored = json.loads(old[0][0])
                    for key in sorted(set(stored) | set(metadata)):
                        if key not in stored or key not in metadata or stored[key] != metadata[key]:
                            raise SystemExit(
                                f"resume-config mismatch on '{key}'; use a fresh directory"
                            )
                    previous = [
                        json.loads(row[0])
                        for row in self.conn.execute(
                            "SELECT payload_json FROM samples ORDER BY ordinal"
                        )
                    ]
                    if previous != schedule:
                        raise SystemExit(
                            "resume-config mismatch on scheduled inputs or image content"
                        )
                else:
                    if any(
                        (directory / name).exists() for name in ("predictions.jsonl", "meta.json")
                    ):
                        raise SystemExit(
                            "run ledger is empty but prior artifacts exist; refusing redispatch"
                        )
                    if self.conn.execute("SELECT 1 FROM samples LIMIT 1").fetchone():
                        raise SystemExit("run ledger has samples without metadata")
                    self.conn.execute("INSERT INTO run VALUES (?)", (json.dumps(metadata),))
                    self.conn.executemany(
                        "INSERT INTO samples(id,ordinal,payload_json,state) "
                        "VALUES (?,?,?,'pending')",
                        [(row["id"], index, json.dumps(row)) for index, row in enumerate(schedule)],
                    )
        except BaseException:
            self.conn.close()
            raise

    def recover(self) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE samples SET state='interrupted',ended_at=? WHERE state='dispatched'",
                (now(),),
            )

    def pending(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.conn.execute(
                "SELECT payload_json FROM samples WHERE state='pending' ORDER BY ordinal"
            )
        ]

    def dispatch(self, sample_id: str) -> None:
        with self.conn:
            changed = self.conn.execute(
                "UPDATE samples SET state='dispatched',started_at=? WHERE id=? AND state='pending'",
                (now(), sample_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("evaluation sample is not pending")

    def complete(self, sample_id: str, result: dict, *, dispatched: bool = True) -> None:
        with self.conn:
            changed = self.conn.execute(
                "UPDATE samples SET state=?,result_json=?,ended_at=? WHERE id=? AND state=?",
                (
                    "completed" if dispatched else "input_error",
                    json.dumps(result, allow_nan=False),
                    now(),
                    sample_id,
                    "dispatched" if dispatched else "pending",
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("evaluation sample changed before completion")

    def export(self) -> Path:
        rows, _ = ledger_snapshot(self.path)
        path = self.directory / "predictions.jsonl"
        atomic_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        return path

    def close(self) -> None:
        self.conn.close()


def ledger_snapshot(path: Path) -> tuple[list[dict], dict]:
    """Read all scheduled rows from one consistent, read-only database snapshot."""
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        metadata = json.loads(conn.execute("SELECT metadata_json FROM run").fetchone()[0])
        if metadata.get("run_contract") != RUN_CONTRACT:
            raise ValueError("unsupported evaluation ledger contract")
        records = conn.execute("SELECT * FROM samples ORDER BY ordinal").fetchall()
        payloads = [json.loads(record["payload_json"]) for record in records]
        if (
            len(records) != metadata["n_scheduled"]
            or schedule_hash(payloads) != metadata["schedule_sha256"]
        ):
            raise ValueError("evaluation ledger schedule integrity failure")
        rows = []
        for record in records:
            payload = json.loads(record["payload_json"])
            result = (
                json.loads(record["result_json"])
                if record["result_json"]
                else {
                    "raw": "",
                    "pred": None,
                    "usage": {},
                    "status": "infra_error",
                    "parse_errors": [],
                    "error": "evaluation_" + record["state"],
                    "generation": {"finish_reason": "unrecorded"},
                }
            )
            rows.append(
                {
                    **payload,
                    **result,
                    "attempt": {
                        "state": record["state"],
                        "started_at": record["started_at"],
                        "ended_at": record["ended_at"],
                    },
                }
            )
        return rows, metadata
    finally:
        conn.close()


def load_predictions(path: str | Path) -> list[dict]:
    """Official readers prefer the live ledger to a possibly stale JSONL snapshot."""
    path = Path(path)
    ledger = path if path.name == LEDGER_NAME else path.parent / LEDGER_NAME
    if path.name in {LEDGER_NAME, "predictions.jsonl"} and ledger.exists():
        return ledger_snapshot(ledger)[0]
    rows = read_jsonl(path)
    meta = prediction_metadata(path)
    if meta.get("run_contract") is not None:
        if meta["run_contract"] != RUN_CONTRACT:
            raise ValueError("unsupported evaluation snapshot contract")
        keys = ("id", "image", "image_sha256", "gt", "meta")
        try:
            scheduled = [{key: row[key] for key in keys} for row in rows]
            if (
                len(rows) != meta["n_scheduled"]
                or schedule_hash(scheduled) != meta["schedule_sha256"]
            ):
                raise ValueError("evaluation snapshot schedule integrity failure")
        except KeyError as exc:
            raise ValueError("evaluation snapshot lacks scheduled-input evidence") from exc
    return rows


def attempt_coverage(rows: list[dict]) -> dict:
    states = Counter((row.get("attempt") or {}).get("state", "unrecorded") for row in rows)
    return {
        "recorded_rows": len(rows),
        "states": dict(sorted(states.items())),
        "attempt_states_recorded": bool(rows) and "unrecorded" not in states,
        "all_recorded_terminal": bool(rows)
        and not any(s in states for s in ("unrecorded", "pending", "dispatched")),
    }


def require_terminal_attempts(rows: list[dict]) -> None:
    if any((row.get("attempt") or {}).get("state") in {"pending", "dispatched"} for row in rows):
        raise ValueError(
            "evaluation schedule is incomplete; comparisons cannot promote partial runs"
        )


def prediction_metadata(path: str | Path) -> dict:
    path = Path(path)
    ledger = path if path.name == LEDGER_NAME else path.parent / LEDGER_NAME
    if path.name in {LEDGER_NAME, "predictions.jsonl"} and ledger.exists():
        return ledger_snapshot(ledger)[1]
    meta = path.parent / "meta.json"
    return json.loads(meta.read_text()) if meta.exists() else {}
