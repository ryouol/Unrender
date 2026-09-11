"""Run on Render Cron; nonzero exit triggers the service's failure notification."""

import json
import sys
import time
import urllib.error
import urllib.request


def main() -> None:
    # Fixed origin avoids forwarding this probe to an arbitrary host.
    url = "https://unrender.onrender.com/health/operations"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
                payload = json.loads(response.read(4097))
                if response.status == 200 and payload.get("status") == "ok":
                    print("UNRENDER operational checks passed")
                    return
        except (OSError, ValueError):
            pass
        if attempt < 2:
            time.sleep(30)
    print(
        "UNRENDER operational checks failed; inspect /health/operations and service logs",
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
