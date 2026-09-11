"""Exercise Google browser intent and auth fencing with the production JavaScript."""

import subprocess
from pathlib import Path


def test_google_browser_intent_and_auth_fencing() -> None:
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("browser_google.mjs"))],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
