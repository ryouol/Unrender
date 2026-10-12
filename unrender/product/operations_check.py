"""Run on Render Cron; nonzero exit triggers the service's failure notification."""

import http.client
import json
import sys
import time
import urllib.error
import urllib.request

_HEALTH_CHECKS = (
    "queue_timely",
    "provider_failures_below_threshold",
    "provider_latency_below_threshold",
    "credit_ledger_consistent",
    "backup_recent",
    "worker_available",
)
_DIAGNOSTIC_CHECKS = (*_HEALTH_CHECKS, "probe_available")


def _response_failure(status: int, body: bytes) -> str | None:
    """Summarize only fixed check names; never echo a body or exception message."""
    prefix = f"http_status={status}"
    if len(body) > 4096:
        return f"{prefix} response=too_large"
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return f"{prefix} response=invalid_json"
    if not isinstance(payload, dict) or payload.get("status") not in ("ok", "attention"):
        return f"{prefix} response=invalid_payload"
    checks = payload.get("checks")
    if (
        not isinstance(checks, dict)
        or not checks
        or any(type(v) is not bool for v in checks.values())
    ):
        return f"{prefix} response=invalid_payload"
    failed = [name for name in _DIAGNOSTIC_CHECKS if checks.get(name) is False]
    if any(value is False and name not in _DIAGNOSTIC_CHECKS for name, value in checks.items()):
        failed.append("unrecognized_check")
    if failed:
        return f"{prefix} failed_checks={','.join(failed)}"
    if payload["status"] != "ok" or not all(checks.get(name) is True for name in _HEALTH_CHECKS):
        return f"{prefix} response=invalid_payload"
    return None if status == 200 else f"{prefix} response=unexpected_status"


def main() -> None:
    # Fixed origin avoids forwarding this probe to an arbitrary host.
    url = "https://unrender.onrender.com/health/operations"
    for attempt in range(3):
        try:
            try:
                response = urllib.request.urlopen(url, timeout=10)  # noqa: S310
            except urllib.error.HTTPError as error:
                # The health endpoint returns useful fixed checks on HTTP 503.
                response = error
            with response:
                reason = _response_failure(response.status, response.read(4097))
        except (OSError, http.client.HTTPException):
            reason = "response=transport_error"
        if reason is None:
            print("UNRENDER operational checks passed")
            return
        print(
            f"UNRENDER operational check attempt={attempt + 1}/3 failed: {reason}",
            file=sys.stderr,
            flush=True,
        )
        if attempt < 2:
            time.sleep(10)
    print(
        "UNRENDER operational checks failed; inspect /health/operations and service logs",
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
