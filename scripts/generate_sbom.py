#!/usr/bin/env python3
"""Generate the checked-in CycloneDX inventory from the hash-locked runtime."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "requirements-app.lock"
OUTPUT_PATH = ROOT / "release" / "sbom.cdx.json"
PACKAGE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def locked_components() -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        match = PACKAGE.match(line)
        if match:
            name, version = match.groups()
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": version,
                    "purl": f"pkg:pypi/{name.lower()}@{version}",
                }
            )
    return sorted(components, key=lambda item: item["name"].casefold())


def main() -> None:
    lock_digest = hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, lock_digest)}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "unrender",
                "version": "0.2.0",
            },
            "properties": [
                {"name": "unrender:requirements-app-lock-sha256", "value": lock_digest},
                {
                    "name": "unrender:license-review-status",
                    "value": "inventory-only; see release/dependency-license-policy.json",
                },
            ],
        },
        "components": locked_components(),
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
