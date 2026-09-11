"""Bounded operational fields for the production log stream."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


class ProductLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | int] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": str(record.msg),
        }
        for field in ("job_id", "provider", "error_code", "duration_ms"):
            value = getattr(record, field, None)
            if isinstance(value, (str, int)):
                payload[field] = value
        if record.exc_info and record.exc_info[0]:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"))
